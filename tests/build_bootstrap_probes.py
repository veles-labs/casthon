"""Freeze broken dispatcher modules into an isolated copy of the real VM."""
import contextlib
import hashlib
import json
import os
from pathlib import Path
import runpy
import shlex
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
from softfloat import build as build_softfloat

CASES = {
    "unexpected": ("raise ValueError('broken bootstrap')", 65538, "C_DISPATCH_BOOTSTRAP:ValueError"),
    "api": ("from casthon import User\nraise User(81)", 65538, "C_DISPATCH_BOOTSTRAP:User"),
    "abi": ("from casthon import ABIError\nraise ABIError('broken bootstrap')", 3, "C_DISPATCH_BOOTSTRAP:ABIError"),
    "revert": ("from casthon import Revert\nraise Revert(65618)", 65618, "C_DISPATCH_BOOTSTRAP:Revert"),
    "ret": ("from casthon import Ret\nraise Ret(b'\\x04\\x00\\x00\\x00\\x01\\x00\\x00\\x00\\x04')", 65538, "C_DISPATCH_BOOTSTRAP:Ret"),
    "missing_dispatch": ("from casthon.return_value import validate_return_payload", 65538, "C_DISPATCH_BOOTSTRAP:AttributeError"),
    "bad_code": ("from casthon import Revert\nclass BadCode(Revert):\n def __init__(self): pass\n @property\n def code(self): raise ValueError('bad code')\nraise BadCode()", 3, "C_DISPATCH_INVALID_API_CODE"),
}

IMPORT_CASES = {
    "import_unexpected": ("raise ValueError('contract import')", 65536 + 610, "C_DISPATCH_UNEXPECTED:ValueError"),
    "import_api": ("from casthon import UserError\nraise UserError(81)", 65536 + 81, "C_DISPATCH_API:User"),
    "import_revert": ("from casthon import Revert\nraise Revert(65618)", 65618, "C_DISPATCH_REVERT:Revert"),
    "import_ret": ("from casthon import Ret\nraise Ret(b'\\x04\\x00\\x00\\x00\\x01\\x00\\x00\\x00\\x04')", None, "C_DISPATCH_RET:Ret"),
}


def run(*args, env=None):
    subprocess.run(list(map(str, args)), check=True, cwd=ROOT, env=env, stdout=sys.stderr)


def main():
    output = Path(sys.argv[1]).resolve()
    report = json.loads((output / "dispatch_smoke-build-report.json").read_text())
    runtime = "asyncify" if report["asyncify"] else "native-errors"
    heap_mode = report.get("heap", {}).get("mode", "static")
    work = ROOT / ".cache/dispatcher-bootstrap" / runtime / heap_mode
    validator = ROOT / "tools/wasm-softfloat/target/release/wasm-softfloat"
    fingerprint = hashlib.sha256(Path(__file__).read_bytes()
        + (output / "dispatch_smoke-build-report.json").read_bytes()
        + validator.read_bytes()).hexdigest()
    manifest = work / "report.json"
    if manifest.exists() and json.loads(manifest.read_text())["fingerprint"] == fingerprint:
        print(manifest)
        return
    if work.exists():
        shutil.rmtree(work)
    work.mkdir(parents=True)
    generated = work / "generated"
    shutil.copytree(output / "dispatch_smoke", generated)
    port = work / "port"
    source_port = ROOT / (".cache/procedural-" + runtime + "/port")
    shutil.copytree(source_port, port, ignore=shutil.ignore_patterns("micropython", "asyncify"))
    # The sources are identical to the already-built VM. Keep their timestamps
    # older than the copied objects so only frozen bytecode is rebuilt.
    for path in port.rglob("*"):
        if path.is_file():
            os.utime(path, (1, 1))
    vm = generated / "vm"
    runtime_build = Path(report.get("cache", {}).get("runtimeBuild", str(vm))) if report["asyncify"] else vm
    config = ROOT / ".cache/emscripten-config.py"
    settings = runpy.run_path(str(config))
    emroot = Path(settings["LLVM_ROOT"]).parent.parent
    emcc = [sys.executable, emroot / "emcc.py"]
    env = {**os.environ, "EM_CONFIG": str(config), "EMSDK_PYTHON": sys.executable}
    with contextlib.redirect_stdout(sys.stderr):
        library, flags, exports = build_softfloat(ROOT, ROOT / ".cache", emcc, env)
    compiler = ROOT / ".cache/procedural/compiler" / ("micropython-" + report["micropython"]) / "mpy-cross/build/mpy-cross"
    micropython = ROOT / (".cache/procedural-" + runtime) / "runtime" / ("micropython-" + report["micropython"])
    optimizer = Path(settings["BINARYEN_ROOT"]) / "bin/wasm-opt"
    records = []
    original_dispatcher = (generated / "module_0.mpy").read_bytes()
    for name, (source, code, diagnostic) in {**CASES, **IMPORT_CASES}.items():
        importing = name in IMPORT_CASES
        if importing:
            (generated / "module_0.mpy").write_bytes(original_dispatcher)
        filename, index = ("contract.py", 2) if importing else ("_cspr_dispatcher.py", 0)
        fixture = generated / filename
        fixture.write_text(source + "\n")
        # The generated modules sort before the SDK packages.
        run(compiler, "-O0", "-msmall-int-bits=31", "-s", filename,
            "-o", generated / f"module_{index}.mpy", fixture)
        # Rapid variants can share a filesystem timestamp. Always regenerate
        # and relink the frozen module rather than relying on mtime ordering.
        for filename in ("frozen_content.c", "frozen_content.o", "contract.raw.wasm"):
            (vm / filename).unlink(missing_ok=True)
        run("make", "-s", "-j6", "-C", port, f"TOP={micropython}", f"BUILD={runtime_build}", f"CONTRACT_BUILD={vm}",
            "HEAP=" + heap_mode,
            f"GENERATED={generated}", "CC=" + shlex.join(map(str, emcc)), f"PYTHON={sys.executable}",
            f"SOFTFLOAT_LIB={library}", "SOFTFLOAT_FLAGS=" + shlex.join(flags),
            "SOFTFLOAT_EXPORTS=" + shlex.join(exports), env=env)
        mvp = work / "mvp.wasm"
        run(optimizer, vm / "contract.raw.wasm", "-g", "--enable-bulk-memory", "--enable-sign-ext",
            "--enable-nontrapping-float-to-int", "--llvm-memory-copy-fill-lowering", "--signext-lowering", "-o", mvp)
        lowered_input = mvp
        if report["asyncify"]:
            lowered_input = work / "asyncify.wasm"
            run(optimizer, mvp, "--disable-bulk-memory", "--disable-sign-ext", "--no-inline=cspr_*",
                "--no-inline=dispatch_body", "-Oz", "--asyncify", "--pass-arg=asyncify-imports@", "-o", lowered_input)
        lowered = work / "softfloat.wasm"
        run(validator, lowered_input, lowered)
        wasm = work / (name + ".wasm")
        run(optimizer, lowered, "-Oz", "--mvp-features", "--strip-debug", "--strip-producers",
            "--strip-target-features", "-o", wasm)
        run(validator, "--instrument", wasm, work / (name + ".metered.wasm"))
        records.append({"name": name, "code": code, "diagnostic": diagnostic, "stage": "import" if importing else "bootstrap"})
    manifest.write_text(json.dumps({"fingerprint": fingerprint, "runtime": runtime,
        "work": str(work), "cases": records}, indent=2) + "\n")
    print(manifest)


if __name__ == "__main__":
    main()
