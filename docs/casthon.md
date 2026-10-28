# Using the Casthon CLI

`casthon` is the Rust command for building Python contracts. It also creates
projects, inspects Wasm and runs your Python test/type-checking tools.

The current version works from a source checkout. Its compiler, native port and
SDK are still loaded from that checkout; standalone distribution is work for the
0.1 release. The [architecture guide](architecture.md) describes that boundary.

## Requirements

For a Wasm build, have these tools available:

| Tool | Used for |
| --- | --- |
| Python 3.11+ | SDK, source analysis and build worker |
| `uv` | The checkout's environment setup |
| Rust/Cargo | Building the CLI; Wasm processing is then built into the executable |
| Node | Emscripten and the checkout's JavaScript tools |
| Make and a host C compiler | Building MicroPython's bytecode compiler and runtime |
| Emscripten (`emcc`) | Compiling and linking the Wasm interpreter/adapter |
| Binaryen (`wasm-opt`) | Asyncify and Wasm optimization |
| `casper-devnet` | Live-network tests only |
| Veles Labs `casper-cli` | Wallets, speculative execution, signing and network deployment |

The current builders use POSIX paths and `fcntl` file locks. Python-only tests
can run without the Wasm compiler tools. `make setup` installs Python development
packages and locked npm dependencies; install the external tools separately.

From this checkout:

```sh
make setup
make cli
./target/release/casthon doctor
./target/release/casthon build hello
./target/release/casthon inspect build/hello.wasm
```

The compiled command lives at `target/release/casthon`. To install it on your
Cargo executable path, run `cargo install --path . --locked` from the checkout.
The remaining examples use that installed `casthon` command. Keep the checkout
available: its location is the default `--sdk-root` embedded in this preview.

## Commands at a glance

| Command | Use |
| --- | --- |
| `casthon new my-flipper` | Create the bundled Flipper project with native and live tests |
| `casthon new my-counter --template counter` | Create the legacy Counter project |
| `casthon new my-token --template cep18` | Create a CEP-18 project |
| `casthon build hello` | Build `contracts/hello.py` |
| `casthon test -q` | Run pytest with the project's configuration |
| `casthon check contracts` | Run mypy on the contract sources |
| `casthon inspect build/hello.wasm` | Inspect the built Wasm |
| `casthon deploy hello --network testnet --from wallet:account-0` | Build and speculatively execute deployment |
| `casthon call hello greet --arg name=Casper` | Validate and speculatively call a deployed contract |
| `casthon doctor` | Report the selected environment and missing tools |

Use `casthon --help` or `casthon build --help` for the parser's full option list.
Arguments to `test` and `check` pass straight through to pytest and mypy, including
`--help` and their exit codes.

## Project configuration

Keep target selection and the interpreter pin in `pyproject.toml`:

```toml
[tool.casthon]
micropython = "1.29.0"
targets = ["contracts/hello.py"]
# python = ".venv/bin/python"
```

`casthon new` writes the MicroPython pin and default target. The supported recipe
currently pins MicroPython 1.29.0. An unsupported version fails before compilation
or downloads. `casthon build --micropython 1.29.0` overrides the project pin for
that invocation. The shared recipe is [native/toolchain.json](../native/toolchain.json).

The CLI uses the nearest ancestor containing `pyproject.toml`, or the current
directory if there is none. Select another root with `--project-root`.
Python is selected in this order:

1. `--python`.
2. `[tool.casthon].python`.
3. The active `VIRTUAL_ENV`, when it contains `bin/python`.
4. The project's `.venv/bin/python`.
5. `python3` on PATH.

The SDK still comes from the checkout selected by `--sdk-root`, even when Python
comes from a project virtualenv. This is an intentional description of the
current preview; installed-SDK resolution remains release work.

## Building contracts

```sh
casthon build                         # Configured targets
casthon build hello counter           # contracts/<name>.py aliases
casthon build contracts/my_token.py   # Explicit source file
casthon build hello --release
casthon build hello --release --minify
casthon build hello --output-dir artifacts
casthon build hello --json
casthon build hello --no-progress
```

A file supplied on the command line is relative to the current directory.
Configured targets and the output directory are relative to the project root.
A short target name selects `contracts/<name>.py`. Explicit targets replace the
configured list. Multiple targets need distinct filenames so their outputs
cannot overwrite each other.

A single-file build works without `pyproject.toml` when you pass its source path.
The build still uses the checkout's compiler resources and supported recipe.

### Build progress and logs

In a terminal, each build stage has a numbered row and a progress bar. Four lines
of compiler output scroll underneath the stages. Both stdout and stderr feed this
area; long lines are clipped to the terminal width. Module freezing shows completed
work out of the total. Compiler steps with no reliable total show an activity bar.
Cache hits appear as reused artifacts.

The complete output is saved to `<target>-build.log` alongside the Wasm, including
diagnostics that have scrolled out of view. A failed build prints that log's path
and returns the worker's failure code.

Redirected output and `TERM=dumb` use plain step names and stream all compiler
output. `--no-progress` streams the compiler output without step headings or bars.
`--json` also disables the display and keeps its artifact manifest on stdout.

### Profiles and files

Debug is the default. Python `print()` reaches `casper_print`, and an uncaught
exception prints its Python traceback and message after cleanup. Caught errors
and successful `Ret` completion signals have no failure traceback.

`--release` is an alias for `--profile release`. It removes host printing and
outer-dispatch diagnostics. Expressions and string conversions passed to
`print()` still run; only their output is discarded. Returns, reverts and
`finally` keep the same behavior.

For a target named `hello`, the main files are:

| File | Purpose |
| --- | --- |
| `build/hello.wasm` | Debug deployment artifact |
| `build/hello.metered.wasm` | Local gas/stack-instrumented test artifact |
| `build/hello-build-report.json` | Hash, exports, signatures and runtime settings |
| `build/hello-build.log` | Full compiler output from the latest CLI build |
| `build/hello.json` | Discovered export/signature declaration |
| `build/hello/` | Lowered Python, bytecode and generated build inputs |
| `build/release/hello.wasm` | Release deployment artifact |

Deploy the deployment artifact; the `.metered.wasm` copy is for the local test
harness. `--minify` adds a `minified/` directory beneath the selected profile.
A custom `--output-dir` replaces the `build/` prefix.

The command compiles Wasm. Installers run only when that Wasm is submitted as a
transaction. See the [testing guide](testing.md#live-network-tests) for the
Python network API used by the live suites.

## Deploying to a network

Casthon delegates wallet storage, network configuration, node-side speculative
execution and signing to the [Veles Labs `casper-cli`](https://github.com/veles-labs/casper-cli).
Install it and select or configure its networks and wallets before deploying:

```sh
cargo install --git https://github.com/veles-labs/casper-cli casper-cli --locked
casper-cli network list
casthon doctor
```

Deployment builds canonical release Wasm and asks the selected network RPC to
speculatively execute an install/upgrade transaction by default. Nothing is
submitted. A network is always selected explicitly:

```sh
casthon deploy hello \
  --network testnet \
  --from mywallet:account-0
```

Review the speculative execution result, then repeat with `--broadcast` to
submit and wait for execution:

```sh
casthon deploy hello \
  --network testnet \
  --from mywallet:account-0 \
  --broadcast
```

Use `--simulate` instead of the default speculative preflight to run Veles
`casper-cli`'s local execution engine. Its experimental public-node mode fetches
and verifies state proofs through ordinary RPC queries, so it does not require
a binary-port endpoint. `--simulate` and `--broadcast` are mutually exclusive.

`--payment-amount` is a CSPR allowance and defaults to `800` for the current
MicroPython runtime. `--gas-price-tolerance` defaults to `1`. Use `--no-build`
only when an already validated `build/release/<target>.wasm` and matching build
report should be submitted. Use `--no-wait` to return immediately after node
admission; the manifest then remains in `submitted` state.
Broadcast deployments and calls use the same wait options.
`--wait-timeout <seconds>` defaults to `600`. A timeout exits with
an error and includes the submitted transaction hash; the transaction may still
execute on the network.

Network commands print a compact result by default. `-v` shows the deployment
summary, numbered phases and five-second heartbeats. `-vv` also shows copyable
external commands and backend output. Diagnostics use stderr. Wallet passwords
are entered directly into `casper-cli`; Casthon does not read or log them.

Successful submissions are written atomically to
`deployments/<network>/<target>.json`. The current record contains the source
and artifact hash, build profile, artifact-bound callable entry-point ABI
(arguments, return type, access/groups, kind and payment policy), signer
reference, public runtime arguments, payment settings, transaction and
block hashes, execution status, gas, any package/entity/bytecode addresses
found in the execution effects, and an unambiguous canonical call target when
one can be derived. Redeploying preserves the previous current record in
`history`.

Call an executed deployment by its manifest name and entry point:

```sh
casthon call hello greet --arg name=Casper
```

`casthon call` selects the manifest automatically when the name exists on one
network. Pass `--network testnet` when it exists on several. It uses the most
recent successfully executed record, so a pending or failed upgrade does not
hide the prior working deployment. The recorded signer is the default caller;
override it with `--from another-wallet:account-0`.

Argument names and entry points are validated against the snapshotted ABI.
`--arg name=Casper` becomes `name:String=Casper` before the handoff to
`casper-cli`; an explicitly supplied CLType must match. Registered stored-call
arguments must be present even when the Python method has a default, because
Casper validates the registered ABI before invoking Python. Dynamic
`OptionalArg` parameters may be omitted.
Package targets call the latest package version, which is the stable target
across Casthon upgrades. The ABI snapshot is tied to the deployment artifact's
SHA-256 hash.

Calls use node-side speculative execution by default. `--simulate` selects the
local public-RPC execution engine and `--broadcast` explicitly submits the
call and waits for its execution result. A successful call reports the block
height; a failed call prints the transaction hash and execution error and exits
nonzero. `--no-wait` returns immediately after submission, and `--wait-timeout`
sets the wait in seconds. Payment defaults to `2.5` CSPR and gas-price tolerance
to `1`:

```sh
casthon call hello greet --arg name=Casper --simulate
casthon call hello greet --arg name=Casper --broadcast
casthon call hello greet --arg name=Casper --broadcast --wait-timeout 120
```

Commit manifests for shared public networks. They contain no private keys or
wallet material. Temporary local-network manifests normally stay untracked.
The chain remains authoritative; transaction hashes and artifact hashes make the
records independently verifiable.

Use `--casper-cli /path/to/casper-cli` to select a non-default executable.
`deploy`, `call` and `doctor` verify the Veles command surface (`transaction
put`, `transaction call`, install/upgrade, package targeting, public-RPC local
simulation, speculative execution and raw transaction output) so an older or
unrelated executable with the same name is rejected.

### Network output and verbosity

`call` and `deploy` have independent format and verbosity controls:

| Option | Output |
| --- | --- |
| default | Compact text result with a short heading on stderr |
| `-q`, `--quiet` | Result only; a simulation returning Bool prints `true` or `false` |
| `-v`, `--verbose` | Workflow details, phases and polling progress on stderr |
| `-vv` | Also show commands and backend diagnostics on stderr |
| `--format text` | Human-readable results (default) |
| `--format json`, `--json` | One JSON result on stdout |

```sh
casthon call flipper get --simulate
casthon call flipper get --simulate -q
casthon call flipper get --simulate --format json | jq '.returnValue.parsed'
casthon call flipper get --simulate --json -v
casthon deploy --network testnet --from mywallet:account-0 --json
```

JSON mode suppresses progress by default; add `-v` or `-vv` to enable stderr
diagnostics without changing the stdout document. Wallet prompts also use
stderr and read terminal input directly. Nested build output is retained in
the build log and cannot enter the result stream.

The result schema uses `schemaVersion: 1`. It includes `command`, `deployment`,
`entryPoint`, `network`, `mode`, `status`, `success`, `exitCode`,
`transactionHash`, `blockHeight`, `gasConsumed`, `returnValue`, `manifest`,
`result` and `error`. Unavailable fields are `null`. Gas quantities preserve the
backend's exact value, normally a decimal string. `returnValue` is the complete
CLValue, with `cl_type`, encoded `bytes`, and native JSON `parsed` data. Node
speculative execution and broadcast receipts do not provide return values;
use `--simulate` to inspect a return value. `result` retains the complete
backend execution data or deployment record.

Successful statuses are `simulated`, `speculated`, `submitted` and `executed`.
With `--broadcast --no-wait`, `submitted` confirms admission only. Operational
failures, including invalid project/ABI configuration, execution errors and
timeouts, emit the same schema with `success: false`, `status: "failed"` and
an error message, and exit nonzero. A timeout retains the submitted hash so it
can be queried later. CLI syntax errors use the normal usage message on stderr.

### Build JSON output

`--json` writes one artifact manifest to stdout. Compiler logs go to stderr,
so a caller can parse stdout without removing progress messages. The manifest
contains `schemaVersion`, the project, MicroPython version, build profile and an
`artifacts` list. Each item records source, deployment Wasm, metered Wasm, report
paths, the build log path, and build metadata.

`casthon.testing.build_contract` consumes this interface for builds on demand.
An invocation such as `casthon build hello --json > artifacts.json` records it.

### Size optimization

Normal builds already use size optimization, LTO, dead-code elimination and
metadata stripping. `--minify` tries additional compatible Binaryen pipelines
and keeps the smallest valid result, including the original as a fallback.
The report records candidate sizes, the selected pipeline and tool version.

Minification removes frozen Python line tables, so debug traceback line numbers
are lost. It preserves assertions, `__debug__`, public signatures and memory
limits. Run compiled tests for the selected profile: static ABI validation alone
does not establish its gas or stack behavior. The [minifier](../scripts/minify.py)
records the excluded transformations and interface checks.

### Other runtime profiles

The default is pristine MicroPython with Asyncify and `emmalloc-gc0`, fixed at
4 MiB. These switches retain the comparison and preserved backend profiles:

```sh
casthon build counter --heap emmalloc-gc1
casthon build counter --heap static
casthon build counter --heap split
casthon build counter --runtime native-errors
```

`native-errors` uses the separate audited MicroPython patches and supports only
its static heap profile. Its artifacts use `build/native-errors/`, followed by
`release/` and `minified/` when selected. Keep these profiles separate when
running tests. The [native port guide](../native/README.md) explains the choices.

## Tests and type checking

```sh
casthon test
casthon test tests/test_contract.py -k greeting
casthon check contracts
```

These run `python -m pytest` and `python -m mypy` in the selected project.
`casthon check` without paths needs mypy targets in the project's configuration;
this checkout supplies them. The richer `make typecheck` also checks positive
SDK usage and deliberate type mistakes.

In this checkout, pytest defaults to the fast native suite. For compiled and live
suites, select their directories explicitly:

```sh
make build
casthon test tests/wasm
CSPR_LIVE_TESTS=1 casthon test tests/live
```

The live opt-in starts local networks. `test` has no separate Wasm or live mode;
these remain ordinary Python suites. See [testing contracts](testing.md) for
mock state, invocation rollback and network setup/cleanup.

## Creating a project

```sh
casthon new my-flipper
casthon new my-counter --template counter
casthon new my-token --template cep18
```

The default Flipper scaffold is maintained as a complete project under
`templates/flipper/` and embedded in the CLI at compile time. It includes native
unit tests and an opt-in live-network test that deploys, flips and queries the
contract on an isolated Casper network. The legacy Counter template includes
ownership and pause mixins. CEP-18 includes its reusable base, events, errors
and upstream license. Existing destinations are refused.

The generated project pins the compatible `casthon-sdk` alpha and its development
tools. Install them into the project environment with `uv`:

```sh
cd my-flipper
uv sync
casthon test
casthon check contracts
casthon build
CSPR_LIVE_TESTS=1 casthon test tests/live
```

The template's SDK version is taken from the Casthon checkout's Python package
metadata, keeping generated projects on the SDK alpha paired with that CLI.

## Inspection and environment checks

```sh
casthon inspect build/hello.wasm
casthon inspect build/hello.wasm --json
casthon doctor
```

Inspection reads the actual exports, imports, memory limits, byte size and hash.
It applies the existing Casper V1 static validator. It does not run installation
code, discover a dynamically registered stored ABI, or predict transaction gas.
Built contracts omit the toolchain's `_initialize` export while retaining
internal constructor startup.

`doctor` groups its results into build dependencies and optional test tools.
It uses ✅ for working dependencies, ❌ for required dependencies that need fixing,
and ⚠️ for optional tools that need attention. It shows Python and tool versions,
checks the runtime pin, and imports pytest, mypy and Wasmtime in the selected
Python environment. Emscripten is checked using the build's Python interpreter
and compiler configuration. Live test support is checked through `casper-devnet --help`.

Failed checks include installation commands and setup links. Python package
commands target the selected virtual environment, or explain how to create a
project virtualenv first. Compiler hints use Homebrew or the detected Linux
package manager, with links to the upstream instructions such as
[Emsdk setup](https://emscripten.org/docs/getting_started/downloads.html).
The command exits with status 1 when a required build check fails; missing
optional test tools leave its status at 0. Version checks establish tool
availability; contract builds still validate the resulting Casper Wasm.

All normal commands currently load checkout metadata, including `inspect`.
Use `--sdk-root /path/to/casthon` if the CLI's compiled-in default has moved.

## Build caching

An unchanged build prints `Using cached contract` and verifies output hashes
before reusing Wasm. Contract or SDK edits invalidate the affected frozen
modules and relink against cached runtime objects. Removed modules and altered
artifacts also invalidate their relevant cache entries.

Reusable Asyncify runtime objects, the bytecode compiler and downloads live in
this checkout's `.cache/`. The runtime key includes interpreter sources, native
code, build profile, heap, compiler identity and relevant flags. Generated
contract inputs and their complete-build cache live beneath `build/<target>/`.
The preserved native-errors backend keeps its runtime objects local to each
contract build.

To force a contract rebuild, remove its `build-cache.json` from the generated
input directory, for example `build/hello/build-cache.json`. Removing
`.cache/micropython-build/` discards the shared runtime object cache. Source files
and the project pin remain in place.

Build workers hold a shared lock because compiler sources and port caches are
currently shared. Writable user caches and isolated parallel workspaces are
part of the remaining packaging work. `casthon.testing.build_contract` has its own
source-keyed artifact cache and uses `CASTHON_BIN`, a CLI on PATH, or a local
built executable; it falls back to the Python builder when no CLI is found.
