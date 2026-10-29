# Testing contracts

The normal feedback loop runs contract source and the real `casthon` library under
CPython. The scoped host changes; contract functions remain ordinary Python.
`casthon.testing` is development-only and is excluded from frozen contract Wasm.

For a step-by-step overview with command output, see the
[website testing guide](../website/testing.html).

```sh
make setup         # Development environment, type checker and Wasmtime
make test          # Native Python tests; no network, Node or Wasm build
make typecheck
make build
make test-wasm     # Frozen MicroPython/C adapter and independent host fixtures
make test-live     # Explicitly starts a class-owned Casper devnet
```

`make test-native` is an alias for the native suite. `make test-all` builds the
artifacts and runs all three suites. Python 3.11+ is supported. Make uses
`.venv/bin/python` when present and otherwise `python3.14`; override it with
`PYTHON=...`.

## Ordinary Python unit tests

Use `MockHost` and `use_host` with unittest or pytest. A new host per test gives
fresh state. The real runtime/storage functions and codecs run unchanged.

```python
import unittest
from casthon import AccountHash
from casthon.testing import MockHost, use_host
from contracts.counter import Counter


class TestCounter(unittest.TestCase):
    def test_increment(self):
        alice = AccountHash(bytes([1]) * 32)
        host = MockHost(caller=alice)
        with use_host(host):
            counter = Counter(0)
            counter.increment_by(5)
            self.assertEqual(counter.get(), 5)
```

These calls do not inject named arguments or introduce transaction boundaries.
Python exceptions retain their normal meaning and traceback. A direct function
that writes and then raises leaves the write in this fixture, just as ordinary
Python code would. Use the invocation harness to test transactional behavior.

`use_host` uses context-local binding and restores the previous host on exit.
The SDK itself is not monkeypatched. The `raw=True` option accepts a transport
whose methods return `(status, value)`, useful for SDK boundary tests.

### Print debugging in native tests

`casthon test` invokes pytest with the project's Python interpreter. Native
contract calls therefore use ordinary CPython `print()`, independent of any
debug or release Wasm profile. Pytest captures stdout by default and includes
it in a failed test's report; passing tests normally keep it hidden.
`--capture=tee-sys` displays output while retaining pytest's capture for
failure reports. `-s` displays output but disables capture.

From the Casthon source checkout, run the existing
[Hello installer test](../tests/test_contract_packages.py):

```sh
casthon test -- tests/test_contract_packages.py -q -k hello_installer --capture=tee-sys
```

Example output (test count and timing may vary):

```text
Greeting finished
Greeting finished
Greeting finished
.                                                                        [100%]
1 passed, 5 deselected in 0.02s
```

The three lines come from `Hello.greet`'s `finally` block during its successful,
caught-error, and reverting calls. The last invocation prints before its state
write is rolled back. For the compiled contract, see
[captured contract prints](#captured-contract-prints): debug Wasm uses the
Casper host, whereas release Wasm is silent.

## Native entrypoint invocation

`ContractHarness` accepts a module or a `Contract` subclass. It discovers explicit
exports or inherited class entrypoints and normalizes their annotations using the same policy as the builder. Argument loading and return
encoding use the same invocation function as the Wasm dispatcher.
`@export_contract` on a class selects its inherited entrypoints when that module
is the root. Imported decorated classes do not add exports to the importing
module; explicit `export_contract(ImportedClass)` selection remains supported.

```python
from casthon import CLU32
from casthon.testing import ContractHarness, MockHost
from contracts import counter

host = MockHost()
session = ContractHarness(counter, host=host)
session.invoke("call")
contract_hash = host.accounts[host.caller]["py_counter"]
token = ContractHarness(counter.Counter, host=host, contract=contract_hash)

token.invoke("increment_by", {"amount": CLU32(5)})
assert token.invoke("get").value == 5
```

The installer executes normally, including explicit package creation and version
registration. Account and stored-contract named keys occupy separate namespaces.
`.at(hash)` selects the stored context; it does not infer a contract from the
entrypoint's name. Registered stored metadata and Wasm export selection stay
independent. Class state and inherited entrypoints also work through the same
harness; owner/pause errors are ordinary Python exceptions in these tests. Each
class invocation uses `Counter.bind()` inside the host context and transaction.
This creates a fresh view of stored state without running `__init__`. Constructors
run explicitly during installation or unit-fixture setup. Ordinary constructor
attributes are not restored on a bound view; persistent values belong in declared
storage fields. Use `Counter.bind()` for direct local calls against existing
context state, and `Counter(initial)` when creating new, independent state.

The same host routes cross-contract calls to the Python module associated with
each installed hash. A session can therefore use the deployed-contract API in
native tests:

```python
from casthon import CLKey
from contracts import counter_session

caller = ContractHarness(counter_session, host=host)
result = caller.invoke("call", {
    "contract": CLKey(contract_hash), "amount": CLU32(5), "expected": CLU32(10),
})
assert result.value == 10  # The preceding example already incremented by five.
```

Each callee uses its registered metadata and stored context. An uncaught callee
failure aborts the mock transaction even if calling Python intercepts its signal;
successful calls are also rolled back if the session subsequently fails. The
Wasm and live suites separately deploy the Python counter and execute
`counter_session.py`, checking its single `call` export, returned values,
dictionary updates and rollback across the contract boundary.

An invocation commits after successful return serialization. An escaping
`ApiError`, `Revert`, codec error or other exception rolls back named keys,
cells, dictionaries, allocations and package/version state. `Ret` is successful
completion after its payload is validated. Errors caught inside contract code
leave earlier writes intact. Unexpected Python errors retain their original
traceback; the native harness does not convert them into User error 610.

`InvocationResult.value` decodes the returned CLValue; `.cl_value` preserves its
explicit type and `.payload` provides serialized bytes. A normal unannotated
`None` return has no CLValue. An annotated `-> None` has a Unit CLValue.

Pass `caller=AccountHash(...)` to exercise caller-dependent behavior. Typed
arguments use ordinary CLValue objects. To test malformed bytes explicitly:

```python
with self.assertRaises(ABIError):
    token.invoke("increment_by", raw_args={"amount": b"bad"})
```

`MockHost(strict_arguments=True)` additionally checks registered argument
CLTypes before Python runs. Missing non-Option metadata arguments then fail even
when the Python function has a default. The default is `False`, matching this
devnet test configuration. `raw_args` cannot claim CLType validation.

Dynamic unit fixtures can pass an explicit `exports={"name": function}` mapping
instead of providing a source module with export markers.

Presence-aware arguments use `OptionalArg[T]`. Test absence by leaving the
argument out of the invocation dictionary; test an explicitly nullable value
with `CLValue(Optional[T], None)`. The shared dispatcher supplies `MISSING` or a
Python default only for absence. Malformed supplied bytes still fail. Factories
leave these dynamic arguments out of required stored metadata, which also
permits omission under strict node validation. `tests/test_optional_args.py`,
`tests/wasm/test_wasm_typed_exports.py` and `tests/live/test_optional_args.py`
cover the native, frozen and live paths, including typed cross-contract calls.

Enum annotations preserve their Python member types: an `EventsMode` state property
returns `EventsMode`, and a typed remote call decodes an enum return into a
member. The underlying CLType remains U8. Chain queries expose that U8 value;
the Python enum domain comes from the contract's annotations. Enum tests cover
invalid discriminants, unrelated enum members, nullable values and canonical
member identities on CPython, frozen Wasm and a live node.

## State and fault injection

`host.context(account=..., caller=...)` and `host.context(contract=..., caller=...)`
select a namespace for direct fixture setup. Use these with `use_host(host)` when
calling SDK functions directly. Host contexts restore on exit.

The public state includes `accounts`, `contracts`, `cells`, `dictionaries`,
`packages` and `entry_points`. Named-key maps hold Key instances. Cell and
dictionary values hold complete serialized CLValues; cell indices are 32-byte
URef addresses. This makes malformed stored bytes explicit test data.

`host.fail_next("dictionary_put", Read())` injects one transport failure. It is
consumed once even when the invocation rolls back. `host.calls` retains the
operation trace across rollback, so tests can inspect cleanup attempts.

The model supports URefs, named keys, dictionaries, selected addable integers,
caller/arguments/time/phase, Blake2b and basic public contract version
registration. URef reads/writes/adds validate context capabilities and access
rights. Passing a URef argument does not manufacture caller ownership.

Unsupported host calls raise `UnsupportedHostCall`; invalid simulated
capabilities raise `MockAccessError`. Both derive from BaseException so a
contract's broad `except Exception` cannot hide missing test support. They are
test failures, not fabricated Casper API statuses.

The mock does not implement gas, consensus, purse transfers, cryptographic
verification, cross-contract host execution, package access/group policy or all
58 FFI operations. It does not reset Python module globals between invocations.
Persistent contract state belongs in host storage. Wasm and live tests verify
the compiler/interpreter and actual engine behavior.

## Live network tests

`LiveNetworkTest` starts one fresh managed network per test class and registers
class cleanup before startup. Subclass setup failure still triggers cleanup.
The same `DevnetNetwork` owner can be used directly as a context manager or in a
pytest fixture. There is no JavaScript dependency for live testing.

Live tests are opt-in: run `casthon test --live`, set `CSPR_LIVE_TESTS=1` when
invoking Python directly, or use `make test-live`. Without the opt-in the base class skips.
`casthon test --live` selects `tests/live` by default. Pass pytest arguments after
`--`, for example `casthon test --live -- -q -k counter` or
`casthon test --live -- tests/live/test_counter.py -x`. When explicitly requested, missing tools,
assets or startup failures fail the suite. Install `casper-devnet` and the pinned
protocol asset; compiling source additionally requires the documented Wasm
toolchain. Starting with prebuilt Wasm avoids the build dependency.

Set `CSPR_DEVNET_BIN` to select a particular launcher build for live tests, for
example `CSPR_DEVNET_BIN=../casper-devnet-launcher/target/debug/casper-devnet`.
This overrides the test class's `binary` setting for that run.

```python
from casthon import CLU32
from casthon.testing import LiveNetworkTest


class TestCounter(LiveNetworkTest):
    protocol_version = "2.2.0"

    def test_increment(self):
        alice = self.funded_account("alice")
        wasm = self.build("contracts/counter.py")
        self.network.deploy(wasm, signer=alice).assert_success()
        token = self.network.named_keys(alice)["py_counter"]
        self.network.call(token, "increment_by", signer=alice,
                          args={"amount": CLU32(5)}).assert_success()
        self.assertEqual(self.network.simulate(token, "get", caller=alice).value, 5)
        self.assertEqual(self.network.query(token, path=["count"]).value, 5)
```

`network.simulate(contract, entry, caller=account, args=...)` uses Veles Labs
`casper-cli transaction call --simulate --raw --initiator account-hash-...`.
It executes locally against a pinned root from the live network's RPC. No private
key is requested, no transaction is submitted, and simulated writes are discarded.
Use `network.call(...)` to commit a change, then simulate a getter to inspect its return:

```python
result = self.network.simulate(token, "get", caller=alice).assert_success()
self.assertEqual(result.value, 5)
print(result.consumed, result.block_height, result.state_root_hash)
```

`SimulationResult.value` decodes the returned CLValue bytes; `.cl_value` exposes
the serialized CLValue and `.raw` retains the full JSON result. Execution errors
support `.assert_failure(pattern)`; accessing `.value` asserts success first.
Transport errors, invalid output, and a missing simulator raise `DevnetError`.
The simulator's key-enumeration restriction still applies. Node transaction
receipts retain their normal behavior and do not expose entrypoint return bytes.

Simulation uses its own CLI configuration and state cache under the test's
diagnostics directory. It does not change the user's wallet or active network.
Choose the backend with `casthon --casper-cli /path/to/casper-cli test --live`,
`CSPR_CASPER_CLI_BIN`, or a `LiveNetworkTest.casper_cli` class attribute. Attached
`DevnetNetwork` instances need `rpc_endpoint` or `port_offset` for simulation.

`funded_account("alice")` derives an identity from the configured seed and test
method ID, then funds it once from `user-1`. Another method gets a different
Alice, independent of test order. Override `motes=` to choose the amount. Deploy
a fresh contract per method; sharing a class network does not rewind blockchain
state. Genesis accounts are available as `network.accounts["user-1"]` etc.

Accounts expose `.account_hash`, `.public_key`, `.path` and lazily derived PEM
`.secret_key` bytes. Signing delegates to casper-devnet using the derivation
path. Secret material is excluded from account repr and framework reports.

The client exposes `deploy`, `call`, `simulate`, `submit`, `transfer`, `query`, `named_keys`,
`dictionary`, `balance`, `rpc` and `tool`. Transfer amounts are integer motes;
entrypoint arguments are explicit CLValues. `rpc` and `tool` provide access to
additional node/tool capabilities without adding another mock implementation.
Queries accept explicit state-root or block identifiers where supported.

Transaction methods wait for execution and return `TransactionReceipt` with
hash, block hash, consumed gas, cost and raw execution data. Submission/RPC
failures raise `DevnetError`; waiting can raise `TimeoutError`. An executed
contract failure remains a receipt: use `.assert_failure(pattern)` or inspect
`.error`. `.assert_success()` verifies execution, not merely admission.

Receipts do not contain a contract's returned CLValue. Query persistent state or
execute a session wrapper that captures/checks the return. The live example in
`tests/live/test_counter.py` exercises the native U32 readback wrapper as well as
dictionary queries, owner-only pause controls, ownership transfer, typed Python
session calls, transfers, errors, deterministic keys and Optional values.

`build_contract()` and `LiveNetworkTest.build()` cache artifacts by source,
helper modules, SDK/compiler/runtime inputs and build flags. They verify cached
artifact hashes and coordinate concurrent builders. The bundled build helper
currently requires a casthon-py source checkout; an explicit builder `command=` or
prebuilt Wasm can be used elsewhere. The build CLI also supports `--project-root`
and `--output-dir` for external projects using `contracts.*` helper modules.

Class configuration includes `network_seed`, `node_count`, `user_count`,
`network_timeout`, `port_offset`, `project_root`, `runtime`, `profile`, `binary`
and `custom_asset`. `binary` selects a launcher executable; `custom_asset`
selects an installed named asset instead of the packaged protocol bundle. Default port
blocks are leased across processes; unique network names prevent class/worker
collisions. Diagnostics, receipts and node logs are retained under
`.cache/casthon-testing/live/`. Teardown stops the owned network and retains its
runtime files; it avoids the launcher's concurrent file-deletion race.

`DevnetNetwork(name="existing", owned=False)` attaches without stopping the
network on exit. Owned startup refuses to replace a discovered existing network.

## Captured contract prints

With a print-FD capable node and launcher, debug contract `print()` output is
captured automatically from the MCP transport's dedicated `node-N casper_print:`
stderr lines. It stays separate from ordinary node logs and JSON-RPC responses.
Release Wasm has no `casper_print` import and produces no output.
The debug profile is the default for `LiveNetworkTest`; select release with
`profile = "release"`. These are contract Wasm prints, separate from pytest's
capture of native CPython stdout described above.
`casthon deploy` builds release Wasm by default, so its deployed contract does
not emit `print()` diagnostics.

Uncaught Python exceptions in debug Wasm also print their traceback, exception
type and message at the outer C dispatcher, after Python `finally` blocks run.
This includes API errors and explicit reverts. Caught exceptions and successful
`Ret` signals do not print a traceback. Diagnostic formatting is best effort;
an exception raised while rendering an error does not replace its revert code.
The existing print capture includes these diagnostics in live test failures.
Dispatcher diagnostics buffer complete lines before calling `casper_print`;
long lines split into bounded chunks at UTF-8 boundaries.
See the captured [live traceback](../results/exception-print-traceback.txt) and
[deliberate test failure](../results/exception-print-failure-example.txt), with
the [verification record](../results/exception-print-live.json).

```python
cursor = self.network.print_cursor
receipt = self.network.deploy(wasm, signer=alice, args=args).assert_success()
line = self.network.wait_for_print(r"counter = 7", since=cursor, node_id=1)
self.assertEqual(line.node_id, 1)
recent = self.network.prints_since(cursor)   # ContractPrint(sequence, node_id, text)
```

`network.print_output` returns a snapshot of the retained stream.
`receipt.print_output` contains lines observed during submission/execution wait.
Failed receipt assertions and `LiveNetworkTest` failures attach a bounded print
excerpt as an exception note. This includes test methods, per-test setup,
teardown, cleanups and subtests; unittest and pytest display the notes with the
failure. A test's cursor excludes output already received before it started.
Teardown retains `contract-prints.jsonl` beside the network's `report.json`,
including output printed before a revert and in `finally`.

These are node streams, with no transaction ID or cross-node ordering guarantee.
Validators can print the same execution independently. Late output can arrive
after a receipt or during a later test. Sharing one MCP client across networks
also shares its captured stream. The launcher console forwarding is best effort;
it can drop lines if its bounded queue fills.

The Python buffer retains at most 1,000 lines and 262,144 text characters;
individual lines are capped at 16,384 characters with an explicit truncation
marker. Failure excerpts show up to 50 lines / 8,192 characters. Evicted lines
are counted in the network report; empty lines remain in the JSONL capture.

The opt-in live regression exercises four validators, UTF-8, output before a
revert, uncaught exception tracebacks, failure-report display and silent release
deployment:

```sh
CSPR_LIVE_TESTS=1 CSPR_PRINT_FD_TESTS=1 \
    CSPR_DEVNET_BIN=/path/to/current/casper-devnet \
    .venv/bin/python -m unittest discover -s tests/live -p test_print_fd.py -v
```

Add `CSPR_DEVNET_CUSTOM_ASSET=<name>` to select a compatible named asset.
The published v0.4.0 assets support the FD environment variable but lack the
`--devnet-capabilities` query required by the current launcher. The recorded
v0.4.0 experiment uses a local test-only custom asset whose wrapper advertises
that known capability, verifies the bundled node's SHA-256, and executes the
unchanged bundled node. This does not make the unwrapped v0.4.0 assets pass
the launcher's capability check. See [the verification record](../results/print-fd-live.json).

## Backend checks

`make test-wasm` runs Python `unittest` tests in `tests/wasm/` through Wasmtime
(installed by `make setup` with the development dependencies). It executes the
actual frozen MicroPython, C adapter and optional native-unwinding backend
against independent Python host and wire fixtures. These checks cover
the MVP instruction profile, host signatures, the 500-slot stack limit,
return/revert unwinding and compiler lowering. They are not a full Casper engine.
Both plain and Casper-instrumented Wasm are exercised; the latter retains the
500-slot stack limiter and gas accounting. Native discovery excludes this
directory, so `make test` neither imports Wasmtime nor requires built artifacts.

Printing tests build debug and release Wasm for both unwinding backends. Debug
has all 58 host imports; release has the same signatures except `casper_print`.
The tests check built-in formatting and UTF-8, string-conversion side effects,
silent release output, uncaught exception tracebacks, broken error formatting,
and unchanged `Ret`, revert, error and `finally` behavior.
After `make setup`, run the focused profile check from the source checkout:

```sh
casthon test --wasm -- tests/wasm/test_wasm_print.py -q -k builtin_print_formatting
```

Example output (counts and timing may vary):

```text
..                                                               [100%]
2 passed, 12 deselected, 8 subtests passed in 38.30s
```

The test checks `Harness.prints` for debug output and an empty release buffer;
passing assertions do not print those captured lines in pytest's summary.
Build on demand with `build_contract(source, profile="release")`; a
`LiveNetworkTest` subclass can select the same profile with `profile = "release"`.

For the preserved native runtime:

```sh
make build BUILD_FLAGS='--runtime native-errors'
CSPR_BUILD_DIR=build/native-errors make test-wasm
```

Native tests remain the fast loop. Wasm tests exercise deployment artifacts;
the live suite validates selected behavior against stock nodes.

`EntryPoint.from_function()` and inherited `Contract.entry_points()` are covered
by native/frozen signature parity tests and compiled examples. Installation
derives metadata from the same signatures used to load arguments and encode
returns. Counter tests cover ownership transfer, owner-only pause controls,
read access while paused and rollback of increments rejected by the pause guard.
`tests/fixtures/constructor_contract.py` is built on demand by the Wasm suite.
It checks required constructor arguments, constructor reads/writes and dictionary
initialization, isolated new state in an existing context, fresh bound instances,
and `finally` writes followed by rollback on failure, in plain and metered Wasm.

The [CEP-18 port](cep18.md) adds native Rust-fixture comparisons, plain/metered
Wasm scenarios and live token tests. Coverage includes the inherited
16-entrypoint ABI, U256 bounds, delegated transfers, security precedence, all
event modes, upgrades and contract-package caller identity. A typed Python
session verifies returned CLValues without re-exporting the token methods.
`MockHost` models immediate caller information, registered message topics and
emitted messages; transactions restore these together with storage on failure.
