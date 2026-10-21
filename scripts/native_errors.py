"""Regenerate reviewed native exception checks from the pinned active C profile.

Run after a native-errors build, which supplies generated qstr/root-pointer headers.
Only the separate audit tree and output directory are written. Review the new
recipe/diff before replacing native/micropython/native-error-edits.json.
"""
import argparse, concurrent.futures, hashlib, json, os, re, shutil, subprocess, sys
from micropython import prepare_and_verify
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
PORT = ROOT / "native/micropython/port"
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--output", type=Path, default=ROOT / ".cache/native-error-review")
parser.add_argument("--headers", type=Path, default=ROOT / "build/native-errors/counter/vm")
options = parser.parse_args()
OUTPUT = options.output.resolve()
OUTPUT.mkdir(parents=True, exist_ok=True)
MP = ROOT / ".cache/native-error-audit/micropython-1.29.0"
archive = ROOT / ".cache/micropython-v1.29.0.tar.gz"
if not MP.exists():
    import tarfile
    with tarfile.open(archive) as tar:
        tar.extractall(MP.parent, filter="data")
prepare_and_verify(archive, MP, "errors")
emdir = Path(shutil.which("emcc")).resolve().parent
emroot = Path(os.environ.get("EMSCRIPTEN_ROOT", emdir if (emdir / "emcc.py").exists() else emdir / "../libexec")).resolve()
EMCC = str(emroot / "emcc.py")
SOURCES = {str(p.relative_to(MP)): p.read_bytes().decode("latin1")
           for p in (MP / "py").glob("*") if p.suffix in (".c", ".h")}

def walk(node):
    yield node
    for child in node.get('inner',[]):yield from walk(child)

def point(loc):
    return loc.get('expansionLoc',loc)

def span(node):
    begin,end=map(point,(node['range']['begin'],node['range']['end']))
    return begin['offset'],end['offset']+end['tokLen']

def balanced_end(text,start):
    # Only extending a macro token to its complete lexical invocation.
    begin=text.find('(',start)
    if begin<0:raise ValueError('macro without arguments')
    depth=0; quoted=None; escaped=False
    for i in range(begin,len(text)):
        char=text[i]
        if quoted:
            if escaped:escaped=False
            elif char=='\\':escaped=True
            elif char==quoted:quoted=None
        elif char in ('"',"'"):quoted=char
        elif char=='(':depth+=1
        elif char==')':
            depth-=1
            if not depth:return i+1
    raise ValueError('unclosed macro')

def call_span(node,text):
    a,b=node['range']['begin'],node['range']['end']
    if 'spellingLoc' in a and a.get('expansionLoc',{}).get('isMacroArgExpansion'):
        a=a['spellingLoc']
    else:a=point(a)
    if 'spellingLoc' in b and b.get('expansionLoc',{}).get('isMacroArgExpansion'):
        b=b['spellingLoc']
    else:b=point(b)
    start,end=a['offset'],b['offset']+b['tokLen']
    if end<=start+len(re.match(r'\w*',text[start:])[0]):end=balanced_end(text,start)
    return start,end

def extract(path):
    command=[sys.executable,EMCC,'-std=c99','-DNDEBUG','-fwrapv','-I'+str(PORT),'-I'+str(ROOT/'native'),'-I'+str(MP),
             '-I'+str(options.headers.resolve()),'-I'+str(options.headers.resolve().parent),'-fsyntax-only','-Xclang','-ast-dump=json',str(path)]
    result=subprocess.run(command,env={**os.environ,'EM_CONFIG':str(ROOT/'.cache/emscripten-config.py')},capture_output=True)
    if result.returncode:raise RuntimeError(str(path)+'\n'+result.stderr.decode()[:3000])
    tree=json.loads(result.stdout);functions=[]
    for node in tree.get('inner',[]):
        if node.get('kind')!='FunctionDecl':continue
        body=next((n for n in node.get('inner',[]) if n['kind']=='CompoundStmt'),None)
        if not body:continue
        loc=node['loc']; pos=loc['spellingLoc'] if loc.get('expansionLoc',{}).get('isMacroArgExpansion') else point(loc)
        offset=pos.get('offset');name=node['name'];body_start,body_end=span(body)
        candidates=[key for key,text in SOURCES.items() if text[offset:offset+len(name)]==name
                    and text[body_start:body_start+1]=='{' and text[body_end-1:body_end]=='}']
        if not candidates:continue
        if len(candidates)!=1:raise ValueError(('ambiguous definition',name,candidates))
        file=candidates[0];text=SOURCES[file]
        # Inline header definitions participate in propagation too.
        calls=[];tries=[]
        for child in walk(body):
            if child.get('kind')=='CallExpr':
                target=child['inner'][0]
                while target.get('inner') and target['kind'] in ('ImplicitCastExpr','ParenExpr','UnaryOperator'):
                    target=target['inner'][0]
                decl=target.get('referencedDecl',{})
                callee=decl.get('name') if decl.get('kind')=='FunctionDecl' else None
                start,end=call_span(child,text)
                if not (body_start<start<end<body_end):continue
                calls.append(dict(start=start,end=end,callee=callee,void=child['type'].get('qualType')=='void'))
            elif child.get('kind')=='IfStmt':
                start,end=span(child)
                prefix=text[start:start+150]
                match=re.match(r'if\s*\(\s*nlr_push\(&([A-Za-z_]\w*)\)\s*==\s*0\s*\)',prefix)
                if match:
                    then,other=child['inner'][-2:]
                    if then['kind']!='CompoundStmt' or other['kind']!='CompoundStmt':raise ValueError('unsupported NLR guard')
                    a,b=span(then);c,d=span(other)
                    tries.append(dict(variable=match[1],start=a,end=b,catch=c+1,label='native_catch_'+str(c)))
        functions.append(dict(file=file,name=name,body_start=body_start,body_end=body_end,
                              result=node['type']['qualType'].split('(')[0].strip(),calls=calls,tries=tries,
                              noreturn=any('NoReturn' in n['kind'] for n in node.get('inner',[]))))
    return functions

cache=OUTPUT/'analysis.json'
fingerprint = hashlib.sha256((PORT / "mpconfigport.h").read_bytes()
    + b"".join(SOURCES[name].encode("latin1") for name in sorted(SOURCES))
    + Path(__file__).read_bytes()).hexdigest()
stamp = OUTPUT / "analysis.sha256"
if cache.exists() and stamp.exists() and stamp.read_text() == fingerprint:
    functions=json.loads(cache.read_text())
else:
    units=[p for p in (MP/'py').glob('*.c') if re.search(r'\b'+re.escape(p.stem)+r'\.o\b',(MP/'py/py.mk').read_text())]
    functions=[]
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        for index,items in enumerate(pool.map(extract,units)):
            functions.extend(items)
            if index%20==0:print('Analyzed',index+1,'of',len(units),flush=True)
    unique={ (n['file'],n['name'],n['body_start']):n for n in functions};functions=list(unique.values())
    cache.write_text(json.dumps(functions,separators=(',',':')))
    stamp.write_text(fingerprint)
# Port stdout routines can fail while allocating their Casper print buffer.
raising={'nlr_jump','mp_hal_stdout_tx_strn','mp_hal_stdout_tx_strn_cooked'}
while True:
    marked={f['name'] for f in functions if any(c['callee'] is None or c['callee'] in raising for c in f['calls'])}
    extended=raising|marked
    if extended==raising:break
    raising=extended
print('Functions:',len(functions),'can raise:',len(raising),'NLR guards:',sum(len(f['tries']) for f in functions),flush=True)
# Store just the reviewed call-site metadata, never compiler-dependent AST ids.
(OUTPUT/'raising.json').write_text(json.dumps(sorted(raising),indent=2))

terminal_names={f['name'] for f in functions if f['noreturn']}
for text in SOURCES.values():
    terminal_names.update(re.findall(r'\b(?:MP_NORETURN|NORETURN)\b[^;{}]*?\b(\w+)\s*\(',text))
insertions={};skip={'nlr_jump','nlr_push_tail','nlr_pop','nlr_push_jump_callback','nlr_pop_jump_callback','nlr_call_jump_callbacks'}
for f in functions:
    if f['name'] not in raising or f['name'] in skip:continue
    file=f['file'];text=SOURCES[file];edits=insertions.setdefault(file,{})
    callbacks=any(c['callee']=='nlr_push_jump_callback' for c in f['calls'])
    if callbacks:edits.setdefault(f['body_start']+1,[]).append('\n    nlr_jump_callback_node_t *native_callbacks = MP_STATE_THREAD(nlr_jump_callback_top);\n')
    default='return;' if f['result']=='void' else 'return ('+f['result']+'){0};'
    if callbacks:default='mp_native_unwind_callbacks(native_callbacks); '+default
    for guard in f['tries']:
        edits.setdefault(guard['catch'],[]).append('\n'+guard['label']+':;\n')
    calls={ (c['start'],c['end']):c for c in f['calls'] if c['callee'] is None or c['callee'] in raising}
    for call in calls.values():
        start,end=call['start'],call['end'];exit=default
        if text[start:end].startswith('CHECK('):continue
        guards=[g for g in f['tries'] if g['start']<start<g['end']]
        if guards:
            guard=min(guards,key=lambda g:g['end']-g['start'])
            if f['name']=='mp_execute_bytecode':exit='mp_native_catch(&'+guard['variable']+'); goto exception_handler;'
            else:exit='mp_native_catch(&'+guard['variable']+'); goto '+guard['label']+';'
        elif f['name']=='mp_execute_bytecode':exit='nlr.ret_val = mp_native_take_exception(); goto unwind_loop;'
        macro='MP_NATIVE_CALL_VOID' if call['void'] else 'MP_NATIVE_CALL'
        if call['callee'] and (call['callee'].startswith('mp_raise_') or call['callee'] in terminal_names or call['callee'] in ('nlr_jump','m_malloc_fail')):macro='MP_NATIVE_RAISE'
        edits.setdefault(start,[]).append(macro+'(')
        edits.setdefault(end,[]).insert(0,', '+exit+')')
    # Do not insert an unused native_catch label in the VM's existing handler.
    if f['name']=='mp_execute_bytecode':
        for g in f['tries']:edits[g['catch']]=[item for item in edits[g['catch']] if g['label'] not in item]
manifest={}
for file,edits in insertions.items():
    source=SOURCES[file];active={str(i):''.join(values) for i,values in sorted(edits.items()) if values}
    if not active:continue
    manifest[file]={'sha256':hashlib.sha256(source.encode('latin1')).hexdigest(),'insertions':active}
recipe = {"version": 1, "micropython": "1.29.0", "profile": "errors",
          "portConfigSha256": hashlib.sha256((PORT / "mpconfigport.h").read_bytes()).hexdigest(),
          "portMakefileSha256": hashlib.sha256((PORT / "Makefile").read_bytes()).hexdigest(),
          "files": {name: manifest[name] for name in sorted(manifest)}}
(OUTPUT / "native-error-edits.json").write_text(json.dumps(recipe, indent=2) + "\n")
print('Changed files:',len(manifest),'call checks:',sum(len(m['insertions']) for m in manifest.values())//2,flush=True)
for key in manifest:print(key,flush=True)
