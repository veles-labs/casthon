import assert from 'node:assert/strict';
import { readFileSync, writeFileSync, statSync, mkdirSync } from 'node:fs';
import { resolve } from 'node:path';
import { createHash, createECDH, createPrivateKey, sign } from 'node:crypto';
import { blake2b } from '@noble/hashes/blake2.js';
import { blake3 } from '@noble/hashes/blake3.js';
import { setTimeout as sleep } from 'node:timers/promises';
import { DevnetClient } from './mcp.mjs';

const root = resolve(import.meta.dirname, '..');
const output = resolve(root, process.env.CSPR_BUILD_DIR ?? 'build');
const cache = resolve(root, '.cache');
mkdirSync(cache, { recursive: true });
const wasm = resolve(output, 'basic.wasm');
const network = `casthon-py-poc-${Date.now()}`;
const node = { network_name: network, node_id: 1 };
const report = { network, asset: '2.2.0', started: new Date().toISOString(),
  wasm: { bytes: statSync(wasm).size, sha256: createHash('sha256').update(readFileSync(wasm)).digest('hex') },
  priceUsdPerCspr: 0.0027,
  transactions: [], observations: [] };
const client = new DevnetClient();
let spawned = false;
let signer;
let account;
let contractHash;
const call = (name, args) => client.call(name, args);
const save = (name, value) => writeFileSync(resolve(cache, `devnet-${name}.json`), JSON.stringify(value, null, 2) + '\n');

function execution(response) {
  const wrapped = response.execution_info?.execution_result;
  const result = wrapped?.Version2 ?? wrapped?.V2 ?? wrapped;
  assert(result && 'error_message' in result, 'Expected Casper V2 execution result');
  return result;
}

async function submit(label, constructor, args, expectedError) {
  console.log(`Submitting ${label}`);
  const made = await call(constructor, { ...node, signer_path: signer,
    payment_amount: label === 'install' || ['ffi-context','ffi-groups','ffi-versions_legacy','ffi-versions'].includes(label)
      ? 800_000_000_000 : 100_000_000_000, ...args });
  const sent = await call('send_transaction_signed', { ...node, signer_path: signer, transaction: made.transaction });
  const response = await call('wait_transaction', { ...node, transaction_hash: sent.transaction_hash,
    timeout_seconds: 50, poll_interval_millis: 1000 });
  save(label, response);
  const result = execution(response);
  const net = BigInt(result.cost) - BigInt(result.refund ?? 0);
  const summary = { label, hash: sent.transaction_hash, consumed: result.consumed,
    cost: result.cost, refund: result.refund,
    gasPriceMotes: result.current_price,
    consumedCspr: Number(result.consumed) * result.current_price / 1e9,
    consumedUsd: Number(result.consumed) * result.current_price / 1e9 * report.priceUsdPerCspr,
    netChargeMotes: net.toString(), chargedCspr: Number(net) / 1e9,
    chargedUsd: Number(net) / 1e9 * report.priceUsdPerCspr, error: result.error_message };
  report.transactions.push(summary);
  console.log(JSON.stringify(summary));
  if (expectedError) assert.match(result.error_message ?? '', expectedError);
  else assert.equal(result.error_message, null, `${label} failed`);
  return response;
}

async function query(key, path = []) {
  return call('rpc_query_global_state', { ...node, key, path });
}

async function observe(expected) {
  const response = await query(contractHash, ['count']);
  save(`count-${expected}`, response);
  const value = response.stored_value?.CLValue;
  assert(value, 'Counter storage must be a CLValue');
  assert.equal(value.cl_type, 'U32');
  assert.equal(Number(value.parsed), expected);
  assert.equal(Buffer.from(value.bytes, 'hex').readUInt32LE(), expected);
  report.observations.push(expected);
  console.log(`Persistent count = ${expected}`);
}

async function observeField(name, type, expected) {
  const response = await query(contractHash, [name]);
  save(`${name}-${expected}`, response);
  const value = response.stored_value?.CLValue;
  assert.equal(value?.cl_type, type);
  assert.equal(String(value.parsed), String(expected));
  report.observations.push({ name, type, value: String(expected) });
}

async function invoke(entry, args = [], error) {
  return submit(entry, 'make_transaction_contract_call', {
    transaction_contract_hash: contractHash, session_entry_point: entry, session_args: args,
  }, error);
}
const amount = value => [{ name: 'amount', type: 'U32', value: String(value) }];

try {
  await client.initialize();
  console.log(`Starting isolated Casper 2.2.0 devnet ${network}`);
  const started = await call('spawn_network', { network_name: network, asset: '2.2.0',
    node_count: 4, users: 1, delay: 3, port_offset: Number(process.env.DEVNET_PORT_OFFSET ?? 2800),
    force_setup: false });
  spawned = true;
  save('network', started);
  const ready = await call('wait_network_ready', { network_name: network, timeout_seconds: 50 });
  save('ready', ready);
  assert.equal(ready.ready, true, 'Network did not become ready');
  // REST may report genesis before the RPC sidecar connects to the binary API.
  let rpcReady = false;
  for (let attempt = 0; attempt < 50; attempt++) {
    try {
      const chainspec = await call('rpc_query', { ...node, method: 'info_get_chainspec' });
      if (chainspec.error) throw new Error(JSON.stringify(chainspec.error));
      const spec = Buffer.from(chainspec.result.chainspec_bytes.chainspec_bytes, 'hex').toString();
      assert.match(spec, /max_stack_height\s*=\s*500/);
      report.stackLimitVerified = 500;
      save('chainspec', chainspec);
      rpcReady = true;
      break;
    } catch {
      await sleep(1000);
    }
  }
  assert(rpcReady, 'RPC sidecar did not become ready');
  const accounts = await call('list_derived_accounts', { network_name: network });
  save('accounts', accounts);
  const user = accounts.find(value => value.kind === 'user') ?? accounts[0];
  assert(user, 'No derived account');
  signer = user.path;
  account = `account-hash-${user.account_hash}`;
  if (!process.env.FFI_ONLY) {
  await submit('install', 'make_transaction_session_wasm', {
    wasm_path: wasm, session_args: [], is_install_upgrade: true,
  });
  const response = await query(account);
  save('account', response);
  const namedKeys = response.stored_value?.Account?.named_keys;
  contractHash = namedKeys?.find(value => value.name === 'py_basic')?.key;
  assert(contractHash, 'Installer did not create py_basic named key');
  report.contractHash = contractHash;
  const storedContract = await query(contractHash);
  save('contract', storedContract);
  // Independent expected ABI passed explicitly during version registration.
  const entryPoints = [
    ['add_big', {amount:'U256'}, 'Unit'], ['add_fractional', {amount:'U32'}, 'Unit'],
    ['fail_after_write', {}, 'Unit'],
    ['get', {}, 'U32'], ['get_big', {}, 'U256'], ['get_mode', {}, 'U8'],
    ['increment', {}, 'Unit'], ['increment_by', {amount:'U32'}, 'Unit'],
    ['mode_name', {}, 'String'], ['set_mode', {mode:'U8'}, 'Unit'],
  ].map(([name,args,returns]) => ({name,args,returns}));
  assert.deepEqual(storedContract.stored_value.Contract.entry_points.map(ep => ({
    name: ep.name, args: Object.fromEntries(ep.args.map(p => [p.name, p.cl_type])), returns: ep.ret,
  })), entryPoints);
  report.abiMatches = true;
  await observe(0);
  await invoke('increment');
  await observe(1);
  await invoke('increment_by', amount(5));
  await observe(6);
  await invoke('add_fractional', amount(1));
  await observe(6);
  await observeField('mode', 'U8', 1);
  await observeField('total', 'U256', 0);
  await submit('typed-get-return', 'make_transaction_session_wasm', {
    wasm_path: resolve(output, 'readback.wasm'), is_install_upgrade: false,
    session_args: [{ name: 'contract_hash', type: 'ByteArray<32>', value: `0x${contractHash.replace(/^hash-/, '')}` },
      { name: 'expected', type: 'U32', value: '6' }],
  });
  await invoke('increment_by', [], /MissingArgument|missing argument/i);
  await observe(6);
  await invoke('increment_by', [{ name: 'amount', type: 'String', value: 'longer than a u32' }], /InvalidArgument|invalid argument|User error: 3/i);
  await observe(6);
  await invoke('set_mode', [{ name: 'mode', type: 'U8', value: '0' }]);
  await observeField('mode', 'U8', 0);
  await invoke('increment', [], /User error: 100/);
  await invoke('add_fractional', amount(3), /User error: 100/);
  await observe(6);
  await invoke('set_mode', [{ name: 'mode', type: 'U8', value: '2' }], /InvalidArgument|invalid argument/i);
  await observeField('mode', 'U8', 0);
  await invoke('set_mode', [{ name: 'mode', type: 'U8', value: '1' }]);
  await invoke('fail_after_write', [], /User error: 101/);
  await observe(6);
  const large = (1n << 200n) + (1n << 64n) + 123n;
  const bigAmount = n => [{ name: 'amount', type: 'U256', value: String(n) }];
  await invoke('add_big', bigAmount(large));
  await observeField('total', 'U256', large);
  const max = (1n << 256n) - 1n;
  await invoke('add_big', bigAmount(max - large));
  await observeField('total', 'U256', max);
  await invoke('add_big', bigAmount(1), /InvalidArgument|invalid argument/i);
  await observeField('total', 'U256', max);
  await invoke('get_big');
  await invoke('get_mode');
  await invoke('mode_name');
  await invoke('add_fractional', amount(3));
  await observe(7);
  await invoke('add_fractional', amount(4));
  await observe(9);
  await invoke('increment_by', amount(0xffffffff - 9));
  await observe(0xffffffff);
  await invoke('add_fractional', amount(1));
  await observe(0xffffffff);
  await invoke('add_fractional', amount(2), /InvalidArgument|invalid argument/i);
  await observe(0xffffffff);
  await invoke('increment', [], /InvalidArgument|invalid argument/i);
  await observe(0xffffffff);
  const smokeWasm = resolve(output, 'api_smoke.wasm');
  report.apiSmokeWasm = {bytes:statSync(smokeWasm).size,sha256:createHash('sha256').update(readFileSync(smokeWasm)).digest('hex')};
  await submit('low-level-host-api', 'make_transaction_session_wasm', {
    wasm_path:smokeWasm,session_args:[],is_install_upgrade:false,
  });
  const smokeAccount = (await query(account)).stored_value.Account;
  const smokeKey = name => smokeAccount.named_keys.find(k => k.name === name)?.key;
  assert.equal(smokeKey('api_smoke_caller'),account);
  assert(!smokeKey('temporary'));
  assert.equal((await query(smokeKey('api_smoke_count'))).stored_value.CLValue.parsed,'12');
  assert.equal((await query(smokeKey('api_smoke_protocol'))).stored_value.CLValue.parsed,'2.2.0');
  const state = await call('rpc_query',{...node,method:'chain_get_state_root_hash',params:{}});
  const dictionary = await call('rpc_query',{...node,method:'state_get_dictionary_item',params:{
    state_root_hash:state.result.state_root_hash,dictionary_identifier:{URef:{seed_uref:smokeKey('api_smoke_dictionary'),dictionary_item_key:'answer'}},
  }});
  assert.equal(dictionary.result.stored_value.CLValue.parsed,'42');
  report.lowLevelHostApiMatches=true;
  await submit('install-counter', 'make_transaction_session_wasm', {
    wasm_path:resolve(output, 'counter.wasm'),session_args:[],is_install_upgrade:true,
    payment_amount:800_000_000_000,
  });
  await submit('low-level-cross-contract-return', 'make_transaction_session_wasm', {
    wasm_path:smokeWasm,is_install_upgrade:false,session_args:[
      {name:'operation',type:'String',value:'call_counter'},
      {name:'amount',type:'U32',value:'7'}, {name:'expected',type:'U32',value:'7'},
    ],
  });
  await observe(0xffffffff);
  const dispatchWasm = resolve(output, 'dispatch_smoke.wasm');
  report.dispatchSmokeWasm = {bytes:statSync(dispatchWasm).size,
    sha256:createHash('sha256').update(readFileSync(dispatchWasm)).digest('hex')};
  for (const [operation, error] of [
    ['internal_return', undefined], ['uncaught', /User error: 42/],
    ['unexpected', /User error: 610/], ['api', /MissingKey/],
    ['invalid_return', /InvalidArgument/], ['invalid_serialized', /InvalidArgument/],
    ['invalid_code', /InvalidArgument/],
    ['host_error_uncaught', /MissingArgument/],
    ['ret_then_revert', /User error: 47/], ['ret_then_error', /User error: 48/],
    ['ret_invalid_payload', /InvalidArgument/], ['ret_invalid_type', /InvalidArgument/],
    ['ret_missing_payload', /InvalidArgument/], ['ret_bad_property', /InvalidArgument/],
    ['ret_invalid_value', /InvalidArgument/], ['ret_invalid_serialized', /InvalidArgument/],
    ['revert', /User error: 43/], ['revert_subclass', /User error: 46/],
    ['revert_replaced', /User error: 44/], ['invalid_revert_code', /InvalidArgument/],
    ['storage_decode', /Read/], ['caught_read_then_abi', /InvalidArgument/],
    ['value_not_found', /ValueNotFound/], ['dictionary_key_too_long', /DictionaryItemKeyTooLarge \[36\]/],
    ['native_escape', /User error: 610/], ['caught', undefined], ['explicit_ret', undefined],
    ['caught_revert', undefined], ['api_caught', undefined], ['user_caught', undefined],
    ['storage_errors_caught', undefined],
    ['host_error_caught', undefined], ['bridge_error_caught', undefined],
    ['dictionary_policy_caught', undefined], ['crypto_error_caught', undefined],
    ['wire_types', undefined],
    ['ret_finally', undefined], ['normal_return_finally', undefined],
    ['ret_replaced', undefined], ['revert_then_ret', undefined],
    ['ret_then_return', undefined], ['ret_caught', undefined],
    ['ret_subclass', undefined], ['ret_unit', undefined], ['ret_native_escape', undefined],
    ['assertion', /User error: 610/], ['debug', undefined],
  ]) {
    await submit('dispatch-' + operation, 'make_transaction_session_wasm', {
      wasm_path:dispatchWasm, is_install_upgrade:false,
      session_args:[{name:'operation', type:'String', value:operation},
        ...(operation === 'assertion' ? [{name:'expected', type:'U32', value:'8'}] : [])],
    }, error);
    if (operation.startsWith('ret_') || ['host_error_uncaught', 'host_error_caught',
         'bridge_error_caught', 'dictionary_policy_caught', 'crypto_error_caught',
         'revert_then_ret', 'normal_return_finally',
         'uncaught', 'revert', 'revert_subclass', 'revert_replaced',
         'storage_decode', 'caught_read_then_abi', 'value_not_found',
         'dictionary_key_too_long', 'caught', 'caught_revert', 'api_caught',
         'user_caught', 'storage_errors_caught'].includes(operation)) {
      const keys = (await query(account)).stored_value.Account.named_keys;
      const trace = keys.find(key => key.name === 'dispatch_trace')?.key;
      if (error) assert(!trace, 'Uncaught error did not roll back writes');
      else assert.equal(Number((await query(trace)).stored_value.CLValue.parsed),
        operation.startsWith('ret_') || ['revert_then_ret', 'normal_return_finally'].includes(operation)
          ? 19 : operation === 'caught' ? 13 : operation === 'storage_errors_caught' ? 4 : 17);
    }
  }
  report.dispatchMatches = true;
  report.hostErrorsUnwind = true;
  report.wireTypesMatch = true;
  const nativeWasm = resolve(output, 'native_unwind.wasm');
  report.nativeUnwindWasm = {bytes:statSync(nativeWasm).size,
    sha256:createHash('sha256').update(readFileSync(nativeWasm)).digest('hex')};
  for (const [operation, name, kind, error] of [
    ['uncaught','list_load','error',/User error: 610/],
    ['uncaught','property','error',/User error: 71/],
    ['uncaught','constructor','revert',/User error: 73/],
    ['uncaught','import','error',/User error: 72/],
    ['matrix','','error',undefined],
    ['caught','property','ret',undefined],
    ['caught','constructor','revert',undefined],
    ['caught','sort','ret',undefined],
    ['caught','map','revert',undefined],
    ['uncaught','property','ret',undefined],
    ['uncaught','constructor','ret',undefined],
    ['uncaught','sort','ret',undefined],
  ]) {
    await submit('native-'+operation+'-'+name+'-'+kind,'make_transaction_session_wasm', {
      wasm_path:nativeWasm,is_install_upgrade:false,
      session_args:[{name:'operation',type:'String',value:operation},
        {name:'case',type:'String',value:name},{name:'kind',type:'String',value:kind}],
    },error);
    const keys=(await query(account)).stored_value.Account.named_keys;
    const trace=keys.find(key=>key.name==='native_trace')?.key;
    if(error) assert(!trace,'Native failure did not roll back cleanup writes');
    else assert.equal(Number((await query(trace)).stored_value.CLValue.parsed),19);
    if(operation==='matrix') {
      const flag=keys.find(key=>key.name==='native_matrix_ok')?.key;
      assert.equal(Number((await query(flag)).stored_value.CLValue.parsed),52);
    }
  }
  report.nativeUnwindingMatches=true;
  }
  const ffiWasm = resolve(output,'ffi_smoke.wasm');
  report.ffiSmokeWasm = {bytes:statSync(ffiWasm).size,sha256:createHash('sha256').update(readFileSync(ffiWasm)).digest('hex')};
  const ffiInvoke = async (operation,extra=[],expectedError) => {
    await submit('ffi-'+operation,'make_transaction_session_wasm', {
      wasm_path:ffiWasm,is_install_upgrade:['context','groups','versions_legacy','versions','missing_export'].includes(operation),
      session_args:[{name:'operation',type:'String',value:operation},...extra],
    },expectedError);
    if (!expectedError) {
      const value=(await query(account)).stored_value.Account;
      const flag=value.named_keys.find(key=>key.name==='ffi_'+operation+'_ok')?.key;
      assert(flag, operation+' success marker missing');
      assert.equal((await query(flag)).stored_value.CLValue.parsed,true);
    }
  };
  for(const operation of ['context','keys','funds','groups','versions_legacy','versions','dictionaries']) {
    await ffiInvoke(operation,operation==='funds'
      ? [{name:'amount',type:'U512',value:'50000000000'}] : []);
  }
  await ffiInvoke('missing_export',[],/Function not found: unexported/);
  report.missingExportRejected=true;
  const privateBytes=Buffer.alloc(32); privateBytes[31]=1;
  const curve=createECDH('secp256k1'); curve.setPrivateKey(privateBytes);
  const publicBytes=curve.getPublicKey(undefined,'compressed');
  const der=Buffer.concat([Buffer.from('30740201010420','hex'),privateBytes,
    Buffer.from('a00706052b8104000aa144034200','hex'),curve.getPublicKey(undefined,'uncompressed')]);
  const privateKey=createPrivateKey({key:der,format:'der',type:'sec1'});
  const signature=sign('sha256',Buffer.from('Casper'),{key:privateKey,dsaEncoding:'ieee-p1363'});
  // k256 accepts canonical low-S signatures.
  const order=BigInt('0xfffffffffffffffffffffffffffffffebaaedce6af48a03bbfd25e8cd0364141');
  const s=BigInt('0x'+signature.subarray(32).toString('hex'));
  if(s>order/2n) Buffer.from((order-s).toString(16).padStart(64,'0'),'hex').copy(signature,32);
  await ffiInvoke('crypto',[
    {name:'signature',type:'String',value:signature.toString('hex')},
    {name:'public_key',type:'String',value:publicBytes.toString('hex')},
  ]);
  await ffiInvoke('crypto_bad',[],/InvalidArgument.*\[3\]/);
  await ffiInvoke('standard_payment',[],/Missing system contract hash: standard payment/);
  await ffiInvoke('messages');
  const ffiAccount=(await query(account)).stored_value.Account;
  const ffiKey=name=>ffiAccount.named_keys.find(key=>key.name===name)?.key;
  const expectedHashes=[blake2b(Buffer.from('Casper'),{dkLen:32}),blake3(Buffer.from('Casper')),
    createHash('sha256').update('Casper').digest()];
  for(let index=0;index<expectedHashes.length;index++) {
    const value=(await query(ffiKey('ffi_hash_'+index))).stored_value.CLValue;
    const bytes=Buffer.from(value.bytes,'hex');
    assert.equal(bytes.readUInt32LE(),32);
    assert.deepEqual(bytes.subarray(4),Buffer.from(expectedHashes[index]));
  }
  const ffiRoot=(await call('rpc_query',{...node,method:'chain_get_state_root_hash',params:{}})).result.state_root_hash;
  for(const [name,expected] of [['ffi_first_purse','5000000000'],['ffi_second_purse','10000000000']]) {
    const balance=await call('rpc_query',{...node,method:'state_get_balance',params:{state_root_hash:ffiRoot,purse_uref:ffiKey(name)}});
    assert.equal(balance.result.balance_value,expected);
  }
  report.fullFfiMatches=true;
  report.passed = true;
  console.log('All devnet checks passed');
} catch (error) {
  report.passed = false;
  report.failure = error.message;
  if (spawned) {
    const logs = await call('get_node_logs', { ...node, stream: 'stdout', limit: 100 }).catch(() => null);
    if (logs) save('failure-logs', logs);
  }
  throw error;
} finally {
  report.finished = new Date().toISOString();
  writeFileSync(resolve(output, 'devnet-report.json'), JSON.stringify(report, null, 2) + '\n');
  if (spawned) {
    await call('despawn_network', { network_name: network, purge: false });
    report.networkStopped = true;
    writeFileSync(resolve(output, 'devnet-report.json'), JSON.stringify(report, null, 2) + '\n');
    console.log(`Stopped ${network}; network files retained for inspection`);
  }
  client.close();
}
