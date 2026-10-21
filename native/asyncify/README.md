# Asyncify Casper port

The default build uses the pinned MicroPython 1.29.0 archive without interpreter
patches. `scripts/build.py` verifies all 6,741 archived files and uses a separate
pristine tree for the bytecode compiler. The preserved native error-return
patches remain available with `--runtime native-errors`; see
[`../micropython/README.md`](../micropython/README.md).

This directory supplies the port-local `setjmp`/`longjmp` implementation used by
MicroPython's existing exception machinery. Binaryen Asyncify saves and restores
Wasm frames. `setjmp_core.S` restores the linear-memory C stack pointer after
rewinding; `unwind.c` drives the unwind/rewind loop outside `dispatch_body`.
Those function boundaries must remain intact before Asyncify runs, including
with LTO enabled.

The builder copies the Casper port into a separate cache, selects these files,
removes the native error-return feature flags, and links with optimization that
preserves the continuation boundaries. The canonical native Makefile and
configuration remain unchanged for the preserved patch recipe. It then lowers
bulk memory/sign extension, optimizes without inlining across driver boundaries,
applies Asyncify, lowers floating point through
SoftFloat, optimizes, checks the Casper MVP ABI, and instruments gas and the
500-slot stack limit. Asyncify control imports are resolved during the build;
deployed artifacts import only Casper functions.

Each continuation buffer is bounded at 4 KiB. Optimizing live locals before
Asyncify is necessary to keep the saved frames within that buffer. The regular probes exercise
native exceptions, nested callbacks, repeated failed imports and completion
signals. Buffer exhaustion traps; it does not become a catchable Python error.
GC is compiled out by default. Every invocation initializes a fresh interpreter
using emmalloc within fixed 4 MiB Wasm memory. Engine traps, gas exhaustion
and engine stack exhaustion remain terminal.

Python errors and completion signals unwind through ordinary `except` and
`finally` handlers. Only uncaught outcomes reach the outer C dispatcher, which
maps `ApiError`/`Revert` to `casper_revert` and `Ret` to `casper_ret`. The Python
contract API and the separate roles of `@export` and `ENTRY_POINTS` are shared
by both runtime profiles.

[`../README.md`](../README.md) describes the separate interpreter lifecycle,
unwinding backend, invocation coordinator and outcome policy, including the
explicit bootstrap failure stage.
