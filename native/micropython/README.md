# Native exception returns

The preserved `native-errors` profile applies `stackless-calls.patch`,
`integer-errors.patch` and `native-errors.patch` to the pinned MicroPython
1.29.0 archive. The default runtime uses pristine upstream with Asyncify;
these patches remain available as an alternative without Asyncify. The bytecode
compiler stays pristine in both profiles. These changes use ordinary Wasm MVP
calls and returns.

```sh
python3.14 scripts/build.py counter --runtime native-errors
```

Artifacts go to `build/native-errors/`, independently of the default artifacts.
The previous full devnet measurements are preserved in
[`results/native-errors`](../../results/native-errors). The three patch files,
their checksums, and their regeneration recipe are retained unchanged.

`native-errors.patch` propagates C-side failures as exception objects:

1. `nlr_jump` stores the exception pointer in the interpreter thread's
   `native_exception` slot and returns.
2. Checked C call sites stop immediately on failure, returning zero or void
   through their callers. Void calls and originally non-returning raisers have
   separate macros.
3. Local C exception handlers receive the exception through an explicit jump
   to their existing handler. C-stack-owned import callbacks run before their
   registering function returns. Python globals/locals and the pystack are
   restored as those scopes unwind.
4. The bytecode interpreter consumes the exception and runs Python handlers,
   including `finally`. Nested C-to-Python callbacks use the same propagation.
5. Only an uncaught Python outcome reaches the outer Casper dispatcher.

The slot carries a Python exception object, not an ABI error code. It is cleared
before a Python handler or native cleanup callback runs, so a caught exception
does not affect the next operation. The outer dispatcher also checks for errors
when inspecting exception codes and return payloads.

The reviewed recipe in `native-error-edits.json` identifies the active C call
sites using Clang's AST. Indirect calls are treated conservatively as capable of
raising, then direct callers are marked transitively. Byte offsets are paired
with exact source checksums. Builds of this profile apply that recipe and compare its
generated diff with `native-errors.patch`; they do not invoke Clang AST analysis.
The port configuration and native Makefile are pinned by the recipe. Changing
interpreter features or compiler flags requires regeneration and validation.

To regenerate after building the counter with `--runtime native-errors`:

```sh
python3.14 scripts/native_errors.py --output .cache/native-error-review
```

This prepares a separate, verified interpreter tree with the first two patches
and writes analysis plus a proposed recipe under the output directory. Review
the recipe before replacing the checked-in JSON and regenerating the diff.
`nativeerror.c` and `nativeerror.h` implement the small shared transport helpers.
The audited Casper bindings have corresponding checks in `native/adapter.c`,
`contract_api.h` and `extended_api.h`. The common `outcome.h` policy uses the
pending-exception hooks from `unwind.h`; it contains no backend feature flags.

`contracts/native_unwind.py` exercises 52 failure cases, successful iterator
exhaustion, repeated failed imports, and Ret/Revert propagation through C
callbacks. The local tests run plain and Casper-metered Wasm. Direct Casper
engine traps, gas exhaustion and the engine's stack limit remain terminal.
Context managers, generators, async and dynamic code remain outside the frozen
authoring profile. This preserved backend retains GC=1 with collection disabled
and a static 2 MiB region. Its exact reviewed configuration and compiler flags
live in `port/mpconfigport.h` and `port/Makefile`, checked against the original
recipe hashes. The default Asyncify backend uses GC=0 independently.
