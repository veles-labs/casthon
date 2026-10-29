<p align="center">
  <img src="docs/assets/casthon-logo.png" width="176" alt="A friendly ghost with a curled tail, inspired by the snake emoji">
</p>

# Casthon

**Python smart contracts for Casper.**

Start with the [step-by-step tutorial](https://veles-labs.github.io/casthon/),
then use the references below when you need more detail.

Write a contract as a Python class, give its entrypoints type annotations, and
build it into Casper-compatible WebAssembly. Casthon freezes your code with
MicroPython; the `casthon` SDK handles arguments, storage, return values and host calls.

The same contract source runs in ordinary Python tests. You can compose classes,
catch exceptions, and use `finally` for cleanup. An uncaught contract error becomes
a Casper revert at the outer invocation boundary.

## Hello, Casper

Here is [hello.py](contracts/hello.py), including its installer:

```python
from casthon import ContractHash, ContractPackageHash, U32, URef, UserError, export
from casthon.contract_api import storage
from casthon.contract_api.runtime import named_keys
from casthon.contracts import Contract, entry_point, export_contract


@export_contract
class Hello(Contract):
    calls: U32 = named_keys.property()

    @entry_point
    def greet(self, name: str) -> str:
        try:
            name = name.strip()
            if not name:
                raise ValueError("Empty name")
            if len(name) > 64:
                raise UserError(1)
            return f"Hello, {name}!"
        except ValueError:
            return "Hello, stranger!"
        finally:
            self.calls += 1
            print("Greeting finished")


installed = named_keys.reference("hello", ContractHash)
installed_package = named_keys.reference("hello_package", ContractPackageHash)
installed_access = named_keys.reference("hello_access", URef[None])


@export
def call() -> None:
    package, access = storage.create_contract_package_at_hash()
    contract, _ = package.add_contract_version(Hello(calls=0))
    installed.set(contract)
    installed_package.set(package)
    installed_access.set(access)
```

`greet` receives and returns a Python string. `calls` is persistent U32 state.
An empty name takes the `except` branch. A name longer than 64 characters raises
a user error and reverts. The `finally` block runs in either case; a revert rolls
back its storage write too.

`@entry_point` describes the class ABI. `@export_contract` selects its Wasm
exports. The top-level `call` creates the package and stores the deployed hashes
explicitly. [The Python API guide](docs/python-api.md) explains the boundaries.

## Try it

This developer preview builds from a source checkout. You need Python 3.11+,
`uv`, Rust/Cargo, Node, Make, a host C compiler, Emscripten and Binaryen.
The [CLI guide](docs/casthon.md#requirements) covers the build requirements.

```sh
make setup
make cli
./target/release/casthon doctor
./target/release/casthon test -- -q
./target/release/casthon build hello
./target/release/casthon inspect build/hello.wasm
```

The build produces `build/hello.wasm`, its metered test counterpart, and a build
report. It compiles the contract; deployment is a separate transaction.

Debug builds keep `print()` and exception tracebacks. For a release build:

```sh
./target/release/casthon build hello --release
```

That writes `build/release/hello.wasm` and removes the `casper_print` import.
See [CLI usage](docs/casthon.md) for project configuration, templates, caching
and minification.

For a public network, Casthon builds release Wasm and delegates node-side
speculative execution, wallet access and signing to the Veles Labs `casper-cli`.
Speculative execution is the default; submission requires `--broadcast`:

```sh
casthon deploy hello --network testnet --from mywallet:account-0
casthon deploy hello --network testnet --from mywallet:account-0 --simulate
casthon deploy hello --network testnet --from mywallet:account-0 --broadcast
casthon call hello greet --arg name=Casper
```

Executed deployments are recorded under `deployments/<network>/` with their
artifact-bound callable ABI, transaction metadata and canonical package/entity
target. `casthon call` resolves that manifest, validates the entry point and
arguments, infers omitted CLTypes, and reuses the recorded signer and network.
As with deployment, calls are speculative by default and require `--broadcast`
for submission. Both commands wait for execution after broadcasting and exit
with an error if the transaction fails. Use `--no-wait` to return after
submission, or `--wait-timeout <seconds>` to change the default 600-second wait.
Pass `--network` when the same target is deployed to more than one network, or
`--from` to use a different caller.
Calls and deployments print a compact result by default. Add `-q` for only the
result, `-v` for workflow progress and five-second heartbeats, or `-vv` for
commands and backend diagnostics. `--format json` (or `--json`) writes one
versioned result object to stdout, including typed return values, transaction
metadata and operational errors. Progress and wallet prompts stay on stderr:

```sh
casthon call flipper get --simulate -q
casthon call flipper get --simulate --format json | jq '.returnValue.parsed'
casthon call flipper get --simulate --json -vv
```

## A few more examples

- [Counter](contracts/counter.py) composes ownership and pause controls, with
  typed state properties and a persistent dictionary.
- [Counter session](contracts/counter_session.py) imports the counter's Python
  ABI to call a deployed contract. The session exports only `call`.
- [MyToken](contracts/my_token.py) inherits the [CEP-18 base](contracts/cep18.py),
  including its entrypoints, permissions and typed events.
- [MyNft](contracts/my_nft.py) inherits the [CEP-78 base](contracts/cep78.py),
  with NFT metadata, approvals, ownership receipts and typed events.
- [Basic](contracts/basic.py) shows the procedural `contract_api` beneath the
  class API.

## Testing

Use pytest or unittest with `MockHost` for fast feedback. `ContractHarness` adds
argument decoding, contract context, return encoding and transaction rollback.
Compiled tests exercise the actual MicroPython/C adapter in Wasmtime. Live tests
start and stop their own Casper devnets.

```sh
make test          # Native Python tests
make typecheck
make build         # Example Wasm artifacts needed by the compiled suite
make test-wasm
make test-live     # Starts local Casper networks; requires casper-devnet
```

`casthon test` runs pytest. Use `casthon test --live` for local-network tests or
`casthon test --wasm` for compiled tests. Put pytest arguments after `--`, for
example `casthon test --live -- -q -k counter`. See the [testing guide](docs/testing.md).

## Tooling benchmarks

Matching [counter contracts and six tests](benchmarks/tooling/), measured on
2026-10-22 with an Apple M1 Max (10 cores, 64 GB RAM, macOS 27.0).
Times are **median wall-clock seconds across three runs**, including command
startup. The comparison uses Casthon 0.1.0, Odra 2.9.1 and cargo-odra 0.1.8.

| Workflow | Casthon (seconds) | Odra (seconds) |
| --- | ---: | ---: |
| Clean release build | 44.59 | 26.20 |
| First unchanged build after clean | 15.98 | 0.40 |
| Cached unchanged build | 1.19 | 0.30 |
| Incremental build after a source edit | 5.14 | 2.57 |
| Cold check / Clippy | 0.92 | 33.74 |
| Cached unchanged check | 0.17 | 0.28 |
| Incremental check after a source edit | 0.28 | 0.29 |
| Cold tests | 0.36 | 153.20 |
| Warm unchanged tests | 0.18 | 0.43 |
| Tests after a source edit | 0.19 | 1.05 |

Clean/cold runs clear compilation or checker caches; tool installation and
downloads are excluded. Incremental runs change an entrypoint's return value
from `1` to `2`. Builds use each tool's standard release pipeline; Casthon also
produces validated, metered Wasm. Checks compare `casthon check contracts` with
default-target `cargo clippy --locked -- -D warnings`. Tests run the six matching
cases through Casthon's native `MockHost`/`ContractHarness` and OdraVM, including
any required test compilation.

The first unchanged Casthon build in this snapshot recompiles the runtime:
Emscripten's one-time sanity-check message changes the compiler cache key.
Later unchanged builds hit the cache. Other sessions were active and OS file
caches were retained, so these figures are indicative; Odra's cold test runs
ranged from 150 to 251 seconds.

To repeat the comparison, install cargo-odra 0.1.8 and the required toolchains,
then run the [benchmark script](scripts/benchmark_tooling.py):

```sh
.venv/bin/python scripts/benchmark_tooling.py --repeats 3
```

The runner isolates its builds and defaults to saving reports and raw logs under
the ignored `.experiments/tooling-benchmarks/` directory. Use
`--clippy-all-targets` to include test targets in the Clippy comparison.

## Read more

| Guide | Contents |
| --- | --- |
| [CLI](docs/casthon.md) | Setup, configuration, commands and artifacts |
| [Python API](docs/python-api.md) | Classes, typed arguments, state, events and low-level calls |
| [Testing](docs/testing.md) | Mock state, invocation boundaries and live networks |
| [CEP-18](docs/cep18.md) | Token implementation, event formats and upgrades |
| [CEP-78](docs/cep78.md) | NFT collections, metadata, approvals, receipts and Python upgrades |
| [Repository and architecture](docs/architecture.md) | Code ownership, build stages and the remaining 0.1 work |
| [Short pitch](docs/pitch.md) | A brief introduction and a small demo |
| [Native port](native/README.md) | Interpreter lifecycle, unwinding and host completion |
| [Website](website/README.md) | Tutorial and GitHub Pages deployment |

## Status

Casthon is a developer preview. The CLI and SDK live in one repository; the CLI
still needs this checkout's compiler and runtime resources. Standalone packaging
and selecting an installed project SDK are the next release work.

The default runtime is pristine MicroPython 1.29.0 with Asyncify, software binary64
floats, and fixed 4 MiB linear memory with GC compiled out. The preserved `native-errors`
backend remains available. Supported Python constructs and runtime limits are
listed in the [architecture guide](docs/architecture.md#runtime-profile).

[Logo credits](docs/assets/README.md).
