<p align="center">
  <img src="docs/assets/casthon-logo.png" width="176" alt="A friendly ghost with a curled tail, inspired by the snake emoji">
</p>

# Casthon

**Python smart contracts for Casper.**

Write a contract as a Python class, give its entrypoints type annotations, and
build it into Casper-compatible WebAssembly. Casthon freezes your code with
MicroPython; the `cspr` SDK handles arguments, storage, return values and host calls.

The same contract source runs in ordinary Python tests. You can compose classes,
catch exceptions, and use `finally` for cleanup. An uncaught contract error becomes
a Casper revert at the outer invocation boundary.

## Hello, Casper

Here is [hello.py](contracts/hello.py), including its installer:

```python
from cspr import ContractHash, ContractPackageHash, U32, URef, UserError, export
from cspr.contract_api import storage
from cspr.contract_api.runtime import named_keys
from cspr.contracts import Contract, entry_point, export_contract


@export_contract
class Hello(Contract):
    calls: URef[U32]

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
            self.calls.write(self.calls.read() + 1)
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
./target/release/casthon test -q
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

## A few more examples

- [Counter](contracts/counter.py) composes ownership and pause controls, with a
  typed URef and a persistent dictionary.
- [Counter session](contracts/counter_session.py) imports the counter's Python
  ABI to call a deployed contract. The session exports only `call`.
- [MyToken](contracts/my_token.py) inherits the [CEP-18 base](contracts/cep18.py),
  including its entrypoints, permissions and typed events.
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

`casthon test` is a pytest wrapper. Wasm and live tests are ordinary test suites,
with the live opt-in described in the [testing guide](docs/testing.md).

## Read more

| Guide | Contents |
| --- | --- |
| [CLI](docs/casthon.md) | Setup, configuration, commands and artifacts |
| [Python API](docs/python-api.md) | Classes, typed arguments, state, events and low-level calls |
| [Testing](docs/testing.md) | Mock state, invocation boundaries and live networks |
| [CEP-18](docs/cep18.md) | Token implementation, event formats and upgrades |
| [Repository and architecture](docs/architecture.md) | Code ownership, build stages and the remaining 0.1 work |
| [Short pitch](docs/pitch.md) | A brief introduction and a small demo |
| [Native port](native/README.md) | Interpreter lifecycle, unwinding and host completion |

## Status

Casthon is a developer preview. The CLI and SDK live in one repository; the CLI
still needs this checkout's compiler and runtime resources. Standalone packaging
and selecting an installed project SDK are the next release work.

The default runtime is pristine MicroPython 1.29.0 with Asyncify, software binary64
floats, and fixed 4 MiB linear memory with GC compiled out. The preserved `native-errors`
backend remains available. Supported Python constructs and runtime limits are
listed in the [architecture guide](docs/architecture.md#runtime-profile).

[Logo credits](docs/assets/README.md).
