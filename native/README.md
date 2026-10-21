# Casper interpreter port

The native port separates four responsibilities:

| Component | Responsibility |
| --- | --- |
| `interpreter.h` | Initialize/deinitialize MicroPython, own its heap and pystack, and supply frozen-import/GC/fatal-NLR port hooks. |
| `unwind.h`, `asyncify/` | Enter the selected unwinding backend and expose pending native exceptions. No host completion policy. |
| `outcome.h` | Cache the SDK outcome types, validate error codes/return payloads, and perform final `casper_ret`/`casper_revert`. |
| `dispatcher.h` | Coordinate one invocation and track the bootstrap/contract stage. |

`adapter.c`, `contract_api.h` and `extended_api.h` implement the `_casper` host
bindings and their `(status, value)` transport. The Python dispatcher loads
annotated arguments, applies declared argument-decoding policies, performs
ordinary calls and serializes returns. Defaults are also resolved there; terminal
return/revert signals and uncaught error policy remain at the outer C boundary.

The builder sets the port-local `CSPR_DEBUG` flag for the debug/release profile.
Debug stdout encodes each UTF-8 chunk as a Casper string, calls `casper_print`,
and frees its temporary buffer. Release stdout discards chunks without allocating
or calling the host. The same flag removes outer-dispatch diagnostics, including
bootstrap and invalid error-code/return-payload messages. Release artifacts have
no `casper_print` import; completion and exception mapping remain shared.

Bootstrap ends only after the SDK types, Python dispatcher function and return
validator are resolved. Failures before that point use User error 2, with the
existing mappings for a known exact `ABIError` and `Revert` subclasses. A `Ret`
raised during bootstrap is a bootstrap failure. Contract import, contract code
and ordinary return serialization execute in the contract stage: uncaught
`ApiError`/`Revert` preserve their codes, `Ret` completes successfully, codec
errors map to `InvalidArgument`, and other Python exceptions use User error 610.
Failures inside the error-code or Ret-payload guards use `InvalidArgument`.

The C boundary imports the root contract directly, then passes that module to
the Python dispatcher. This preserves ordinary import order while avoiding an
extra retained VM frame beneath nested contract/mixin imports. Class state
descriptors are constructed after their class body, and frozen entrypoint
methods retain ordinary method calls. These choices keep the class counter and
its importing session within the stock 500-slot stack limit.

Fatal interpreter port faults (an absent NLR boundary or an unsupported GC
attempt) use User error 1. Engine traps, gas exhaustion and stack exhaustion
remain engine failures. Interpreter initialization is outside the Python
outcome boundary.

The default heap uses `MICROPY_ENABLE_GC=0` and routes upstream MicroPython's
allocations through libc malloc/realloc/free, supplied by emmalloc. There is
no static Python heap buffer. The builder's `--heap emmalloc-gc1` profile
instead allocates one GC region from the available emmalloc tail. Both modes fix
initial and maximum linear memory at 4 MiB, disable growth and return NULL on
allocation failure. The GC-enabled mode keeps tracing collection disabled.
`--heap static` preserves the historical static 2 MiB GC region, while
`--heap split` preserves the growing-region experiment.
The optional `native-errors` backend uses its exact audited configuration in
`micropython/port/`, including the historical static GC region. Its call-site
recipe and all three patch files remain unchanged; other heap modes require
a separate audit and are rejected for that preserved backend.
Heap regions and other Python allocations live within one invocation's Wasm
instance; the engine discards that instance afterwards.

The production dispatcher has no terminal-jump compatibility hook or mapping
flags. The preserved native-error runtime uses explicit pending-exception
returns; Asyncify uses upstream NLR continuations. The older isolated
experiments retain their own terminal shims and outcome policies.
