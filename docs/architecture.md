# Repository and architecture

Casthon has two public pieces: the Rust `casthon` command and the Python `casthon`
SDK. They share a compiler and a Casper-specific MicroPython port. Keeping them
in one repository lets a change to a type, decorator or class schema update its
freezer and execution tests in the same change.

## Where things live

| Path | Responsibility |
| --- | --- |
| `src/casthon/` | Python SDK: wire types, codecs, contract API, class/state helpers and events |
| `src/casthon/testing/` | Mock host, native invocation harness and live-network helpers; excluded from contract Wasm |
| `cli/` | Rust command-line interface, configuration, templates and build orchestration |
| `scripts/` | Static source analysis, lowering, freezing, runtime builds and optimization |
| `runtime/` | Frozen Python dispatcher and MicroPython-specific replacements for SDK inspection/typing helpers |
| `native/` | C host adapter, interpreter lifecycle, unwind backends and outcome handling |
| `tools/wasm-softfloat/` | Rust Wasm rewriting, Casper validation and gas/stack instrumentation; also linked into the CLI |
| `contracts/` | Working examples, reusable contract bases and host API probes |
| `tests/` | Native Python and Rust CLI tests, plus compiled-Wasm and live suites |
| `reference/` | Independent upstream wire fixtures and comparison inputs |
| `results/` | Recorded validation reports, each tied to its own revision and artifacts |
| `docs/` | User guides and implementation notes |

Generated Wasm and lowered source go in `build/`. Compilers, runtime objects and
downloads currently go in `.cache/`. Both are ignored. Local feasibility work
is archived in an ignored directory and is outside the build and release inputs.

## Review of the current structure

The SDK, CLI and native port already have useful boundaries. Keep those
directories together while preparing 0.1. Moving them into separate repositories
would make schema changes harder without resolving the packaging problem.

The remaining coupling is in how these components find and select each other:

- `cli/main.rs` defaults `--sdk-root` to its compile-time checkout path. Its
  Python commands prepend that checkout's `src/` to `PYTHONPATH`, including tests.
- `scripts/build.py` freezes the checkout SDK, reads compiler/runtime files
  relative to that checkout, and writes caches there.
- The freezer imports SDK schema helpers. `runtime/` supplies corresponding
  frozen implementations, so compiler and SDK versions must be compatible.
- `casthon.testing.build_contract` also locates the SDK checkout. It is useful
  today, but that lookup will need an installed-resource boundary.
- `contracts/` contains both teaching examples and exhaustive FFI probes.
  The README links the teaching examples; the probes serve the regression suite.

For distribution, the SDK should be its own Python package. The CLI release
should carry versioned compiler/runtime resources and build against the SDK in
the project's selected Python environment. A known compatible version pair is
enough for 0.1. Separate repositories are unnecessary for that arrangement.

The Python SDK is distributed as `casthon-sdk`; its public import package is
`casthon`. The Rust package still has `publish = false`, and the project needs a
top-level license and a release pipeline before a stable release.

## From Python to Wasm

1. **Select the target.** The CLI reads `pyproject.toml`, chooses Python and a
   supported runtime recipe, and invokes the Python build worker.
2. **Analyze the source.** The frontend follows supported local imports,
   resolves annotations, discovers explicit exports and validates class schemas.
   It does this without importing or executing contract source.
3. **Lower and freeze.** Development-only typing and inspection become compact
   descriptors and signature tables. MicroPython's bytecode compiler produces
   frozen modules. Imported reusable code is included without automatically
   exporting its entrypoints from the target module.
4. **Compile and link.** Emscripten links the interpreter, frozen modules, host
   adapter and small Wasm export wrappers. The default backend uses unchanged
   upstream MicroPython with the port-local Asyncify driver.
5. **Process the Wasm.** The pipeline applies the selected optimization passes,
   supplies software floating point, removes unsupported instructions and strips
   the public `_initialize` export while preserving internal startup.
6. **Validate and report.** The Rust engine checks the Casper V1 Wasm profile.
   The build also writes a gas/500-slot-stack-instrumented test artifact and a
   report containing hashes, exports, signatures and runtime settings.

The CLI packages this workflow. The next step is giving the existing Python
frontend a distributable, versioned resource bundle.

## One invocation

The outer C dispatcher initializes MicroPython and imports the root module.
The Python dispatcher decodes annotated named arguments and calls the selected
function or a bound contract method. A class invocation binds existing named
keys without rerunning its constructor.

Calls inside contract code use ordinary Python arguments, return values and
exception handlers. A normal return is serialized after its `finally` blocks
have run. `runtime.ret()` and `runtime.revert()` raise explicit `BaseException`
signals, so they also unwind Python cleanup.

At the outer boundary, a successful result becomes `casper_ret`. Uncaught
`ApiError` subclasses preserve their Casper error code; `UserError(n)` uses a
user code. Other Python exceptions use the documented fallback, User error 610;
codec failures map to `InvalidArgument`. A revert rolls back the invocation's
state changes, including writes made during cleanup. Direct engine traps, gas
exhaustion and stack exhaustion remain engine failures.

The [native port guide](../native/README.md) assigns the C lifecycle, unwind and
completion responsibilities to their implementation files.

## Runtime profile

The default recipe pins MicroPython 1.29.0 and its source checksum. It uses
Asyncify, emmalloc with GC compiled out, and fixed 4 MiB Wasm memory. Each
invocation starts a fresh interpreter. The preserved `native-errors` backend
uses the separate audited MicroPython patches in `native/micropython/`.

Python integers are arbitrary precision. Binary64 calculations use Berkeley
SoftFloat and are lowered to integer-only Wasm; Casper arguments, storage and
returns still use supported CLTypes. Float formatting is MicroPython's
approximate formatter. The `math` module and complex numbers are disabled.

The authoring profile supports functions, closures, classes, supported mixin
graphs, typed state, exceptions and cleanup. It does not include arbitrary
PyPI packages or native CPython extensions. Generators, async code, context
managers and dynamic code are outside the contract authoring profile. The
builder rejects inheritance whose lookup or `super()` behavior would differ
between CPython and MicroPython. The Asyncify driver uses bounded continuation
buffers; their exhaustion traps.

Gas and size figures in `results/` belong to the artifacts named in each report.
They are not estimates for a newly built contract. Static Wasm compatibility
also does not establish runtime behavior; compiled tests and live deployments
cover that separately.

## What remains for 0.1

- Install the CLI, SDK and compiler resources without a source checkout.
- Resolve the project SDK consistently for native tests and Wasm builds.
- Check supported external compiler versions and use a writable user cache.
- Run release-package smoke tests outside the repository, including a live
  deployment and exception/rollback checks.
- Finish package names, licensing, installation instructions and release CI.

The existing pytest interface can stay. Automatic compiler installation,
parallel build workspaces and more interpreter recipes can follow this release.

## Working on this checkout

```sh
make setup
make cli
make test
make test-cli
make typecheck
make build
make test-wasm
```

Run `make test-live` when changing behavior that needs node validation. It starts
local networks; the [testing guide](testing.md) describes ownership and cleanup.
Changes to the native port should preserve the separate audited `native-errors`
recipe and exercise the relevant compiled runtime profiles.
