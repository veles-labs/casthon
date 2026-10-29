# Python API

Start with [hello.py](../contracts/hello.py) for a complete class contract. This
reference covers the class API and the procedural functions underneath it. Build
commands live in the [CLI guide](casthon.md); contract tests have their own
[guide](testing.md).

For a shorter path with copyable examples, see the
[website Python API guide](../website/python-api.html).

- [Classes and state](#class-contracts)
- [Reusable contract mixins](#reusable-contract-mixins)
- [Typed arguments](#typed-arguments)
- [Exceptions and cleanup](#exceptions-and-cleanup)
- [Calling a deployed contract](#calling-a-deployed-contract)
- [Installation and stored ABI](#stored-contract-abi-and-installation)
- [Low-level API](#low-level-api)
- [Typed state references](#typed-state-references)
- [Events](#events)

## Python functions and Wasm exports

[contracts/basic.py](../contracts/basic.py) contains procedural functions:

```python
from casthon import EntryPoint, U32, URef, CLU32, MissingKey, export
from casthon.contract_api import runtime, storage

ENTRY_POINTS = [
    EntryPoint("increment_by", {"amount": U32}),
    EntryPoint("get", {}, U32),
]


@export
def increment_by() -> None:
    amount = runtime.get_named_arg("amount", U32)
    key = runtime.get_key("count")
    if not isinstance(key, URef):
        raise MissingKey()
    count = storage.read_or_revert(key, U32)
    storage.write(key, CLU32(count + amount))


@export
def get() -> CLU32:
    key = runtime.get_key("count")
    if not isinstance(key, URef):
        raise MissingKey()
    return CLU32(storage.read_or_revert(key, U32))
```

The builder reads export markers and checks that they resolve to top-level Python
functions. Parameters require supported Casper wire annotations. The same marker applies
to stored-contract functions and session functions:

```python
from casthon import export

@export
def call() -> None:
    # Explicit package creation, state initialization and version registration.
    ...
```

Build [the basic example](../contracts/basic.py) with `casthon build basic` or `make
build-basic`. Its selected functions keep Casper's `() -> ()` Wasm export signature. The
Python dispatcher supplies annotated arguments and serializes the result before the
outer C dispatcher calls `casper_ret`. Existing explicit `CLValue` return annotations
remain supported. `call` is neither required nor implicitly exported. There is no
contract TOML file.

### Class contracts

[The counter](../contracts/counter.py) uses the class API, with reusable
[Ownable](../contracts/ownable.py) and [Pausable](../contracts/pausable.py) mixins:

```python
from typing import Any
from casthon import U32, AccountHash, Dictionary
from casthon.contract_api.runtime import named_keys
from casthon.contracts import entry_point, export_contract
from contracts.pausable import Pausable

@export_contract
class Counter(Pausable):
    count: U32 = named_keys.property()
    increments: Dictionary[AccountHash, U32] = named_keys.property(
        key=lambda account: bytes(account)[1:].hex())

    def __init__(self, initial: U32 = 0, **state: Any) -> None:
        super().__init__(count=initial, **state)

    @entry_point
    def get(self) -> U32:
        return self.count
```

`named_keys.property()` uses the attribute's value annotation and infers its named-key
name. For example, `Ownable.owner: AccountHash` and `Pausable.paused: bool` are
inherited by Counter. Ownership uses `named_keys.property(uref=True)` to preserve its
URef-backed storage; a Key subclass otherwise represents a direct named-key binding.
Declarations perform no storage I/O. `Counter(initial)` runs the normal Python
constructor chain: Pausable supplies its `paused` default, Ownable supplies its `owner`
default, and Contract validates the collected values and allocates fresh URefs and
dictionary seeds. Unspecified dictionaries start empty; other required state must be
supplied. The new instance owns its state-key map, without binding those names into the
installer's account. After `super().__init__` returns, constructor code can read/write
`self.count` and `self.increments`. Use `named_keys.property("old_count")` to specify a
different persistent name.

`Counter.bind()` creates a view of existing state in the current context. It skips the
constructor and resolves named keys lazily, following rebinding. `self.count` returns
the stored U32, and `self.increments[account]` accesses dictionary items directly. Reads
validate key variants and stored value types. `self.count = 7` updates its existing
cell without allocating another URef or changing its named-key binding. Previously
resolved URefs see the new value. A new instance writes its own initial state, while a
bound instance writes the current contract's state.

`self.count += 1` reads, increments and writes through the same URef. Dictionary
properties return typed views: `self.increments[account] = amount` and
`self.increments[account] += 1` operate on individual items. Missing items raise
`KeyError`; use `.get(account, 0)` when a default is needed. Whole-dictionary assignment
is rejected. A property holding a list or map returns a decoded value: mutate a local
copy and assign it back to persist the change.

Key properties such as `target: ContractHash = named_keys.property()` read and replace
the named-key binding directly. Use `uref=True` to store a Key value inside a URef
instead. Raw keys remain available through `self.named_keys`; ordinary typed references
from `named_keys.reference(name, schema)` retain `.get()`, `.read()` and `.write()`.
Existing `URef[T]` class fields remain explicit references; properties use the exposed
value type `T` as their annotation.

`@entry_point` marks a method for the class ABI. `Counter.entry_points()` includes
inherited ownership, pause and counter methods without a manual `ENTRY_POINTS` list.
`@export_contract` selects these methods as root Wasm exports when its module is the
build target. It is an identity decorator on CPython and is erased when freezing Wasm.
Importing the decorated Counter into another module does not select its exports there.
To select an imported class explicitly, use `from contracts.counter import Counter`
followed by `export_contract(Counter)`. Use the decorator without parentheses. Local
calls such as `Counter.bind().increment_by(5)` use normal Python arguments, returns and
catchable exceptions. Ordinary Python decorators compose underneath `@entry_point`, for
example `@entry_point` followed by `@require_security_admin`. Use `functools.wraps` in
the decorator to preserve native signature inspection. The decorator runs after boundary
argument decoding, and also runs for ordinary local calls. `@export` supports the same
pattern for free functions; keep the export marker outermost. The freezer records the
annotated ABI separately and removes `wraps` inspection metadata, while retaining the
decorator's executable Python code. Frozen functions do not expose writable
`__wrapped__` or `__annotations__` attributes.

The top-level `@export def call(initial: U32 = 0)` remains the explicit installer:

```python
counter = Counter(initial)
package, access = storage.create_contract_package_at_hash()
contract, version = package.add_contract_version(counter)
```

The package method takes an initialized `Contract` instance and supplies its inherited
entrypoint metadata and `counter.named_keys`. Package creation and account-key bindings
stay explicit.
Constructor arguments are ordinary Python arguments; the top-level export loads its own
annotated named arguments from the host. `__init__` is not an entrypoint.

The returned `ContractPackageHash` also owns version controls:

```python
package.disable_contract_version(contract)
package.enable_contract_version(contract)
```

These methods preserve catchable host errors. For an upgrade that reuses existing
state without constructing fresh state, use the explicit
`storage.add_contract_version(package, Counter.entry_points(), {}, message_topics)` API.
Resolve a stored package with
`named_keys.reference("counter_package", ContractPackageHash).get()` to recover its
package methods from the legacy hash wire representation.

The dispatcher and native test harness use `Counter.bind()` for every invocation, so
constructor logic and allocations are not repeated by dispatch. Binding uses
`object.__new__` without running user `__new__` or `__init__`. Plain Python instance
attributes created by the constructor do not persist across invocations; persistent data
belongs in declared storage fields. Uncaught constructor errors use the ordinary
invocation rollback policy, including writes made by `finally`.

The builder checks inherited state names, entrypoint names and override wire signatures.
MicroPython uses depth-first inheritance lookup rather than CPython's C3 order. The
builder rejects inheritance graphs whose lookup or `super().method(...)` resolution
would differ; the Counter → Pausable → Ownable chain works on both interpreters. General
cooperative C3 diamonds are not implemented. Metadata is inspected on CPython and frozen
at build time for Wasm; no runtime `typing` or `inspect` package is deployed.

### Reusable contract mixins

The example modules [Ownable](../contracts/ownable.py) and
[Pausable](../contracts/pausable.py) show how to compose contract behavior.
They live in the repository's `contracts/` directory, rather than in the core
`casthon` package or the Flipper scaffold. Copy or adapt them in your own
project. [Counter](../contracts/counter.py) inherits `Pausable`, which inherits
`Ownable`, so its chain is `Counter → Pausable → Ownable → Contract`.

| Layer | Stored state and default | Inherited entry points | Guard and error |
| --- | --- | --- | --- |
| `Ownable` | `owner: AccountHash`, URef-backed; defaults to `get_caller()` during installation, or an explicit constructor owner | `get_owner()`, `transfer_ownership(new_owner)` | `@require_owner` checks the current caller before transfer; `NotOwner` is `UserError(100)` |
| `Pausable` | `paused: bool`; defaults to `False` | `pause()`, `unpause()`, `is_paused()` | `pause` and `unpause` use `@require_owner`; `@require_unpaused` raises `Paused`, a `UserError(101)`, on a guarded method |
| `Counter` | `count: U32` and a per-account `increments` dictionary | `increment()`, `increment_by(amount)`, `get()`, `get_increments(owner)` | Only the increment methods use `@require_unpaused`; reads remain available while paused |

`super().__init__` passes constructor values through the chain. `Ownable` takes
the current caller as the initial owner only when no `owner=` was supplied.
Creating `Counter(initial)` initializes all four stored fields once; later
entry-point invocations bind existing state without rerunning constructors.
The concrete `@export_contract` class selects root Wasm exports, and its
`entry_points()` includes the inherited methods automatically.

The guards are ordinary Python decorators. Place them below `@entry_point` on
the method they protect. `@require_owner` calls `_require_owner()` before the
method body, comparing `get_caller()` with `self.owner`.
`@require_unpaused` calls `_require_unpaused()` before the body and rejects a
call only when `self.paused` is true. Both use `functools.wraps` to preserve the
method signature used by native inspection. They run for local Python calls
as well as dispatched entry points, and their `UserError` subclasses are
catchable in native tests. If uncaught on chain, user error 100 or 101 reverts
the invocation.

Ownership does not implicitly guard every method. Any caller may increment
Counter while it is unpaused; only an owner may pause, unpause, or transfer
ownership. A failed pause guard runs before the increment body and leaves the
count and per-account tally unchanged. A paused contract still allows
`get()`, `get_increments()`, `get_owner()`, and `is_paused()` because none has
the pause guard. Transferring ownership changes who can control pause and
transfer next; it does not change `paused`. The
[website Counter walkthrough](../website/examples.html#counter-mixins) has a
copyable native session and its example output; the
[native contract tests](../tests/test_class_contracts.py) and
[compiled Wasm test](../tests/wasm/test_wasm_counter.py) exercise the same
behavior. The installer binds `py_counter`, so it can coexist with `basic.py`
at `py_basic`. Build it with `make build-counter` or
`python3.14 scripts/build.py counter`.

### Typed arguments

`U32` is `Annotated[int, "U32"]`: the function receives an ordinary integer. The builder
resolves each exported function's signature without executing contract code, then
freezes it in `build/<target>/_cspr_exports.py`. The Python dispatcher loads each
argument with `runtime.get_named_arg`, invokes the function, and encodes its return
using the declared wire type. Arithmetic stays ordinary Python; a returned integer
outside U32's range raises `InvalidArgument` at this boundary. Direct Python calls
receive no argument injection or return conversion. The generated JSON also records
these invocation signatures.

### Nullable and missing arguments

Nullable values use `typing.Optional[T]` or `T | None`, mapped to Casper `Option<T>`,
for both arguments and returns:

```python
from typing import Optional

@export
def echo(amount: Optional[U32] = None) -> Optional[U32]:
    return amount
```

An explicit Option None is distinct from a missing named argument. A missing argument
uses the function's default, if present; otherwise it raises `MissingArgument`.
Malformed supplied bytes and other host errors never select a default. Defaults retain
normal Python evaluation at function definition time. Named positional and keyword-only
parameters are supported; positional-only parameters, `*args`, `**kwargs` and
unsupported wire annotations fail the build. For stored calls, node argument validation
still follows the explicit `ENTRY_POINTS`: with strict checking enabled, a non-Option
metadata parameter must be supplied before Python runs, even if the Python parameter has
a default.

Use `OptionalArg[T]` when the named argument itself may be absent:

```python
from typing import Optional
from casthon import MISSING, OptionalArg, U32, export

@export
def describe(amount: OptionalArg[Optional[U32]] = MISSING) -> str:
    if amount is MISSING:
        return "absent"
    if amount is None:
        return "explicit None"
    return str(amount)
```

`Optional[T]` describes the wire value (`Option<T>`); `OptionalArg[T]` describes
argument presence. An absent argument supplies the Python default, or `MISSING` when
there is no default. An explicit encoded `None` remains `None`, including when the
default is something else. Malformed supplied arguments still raise. Low-level code can
use `runtime.get_named_arg("amount", OptionalArg[U32])` and check `is MISSING`, without
an optional-argument helper.

`EntryPoint.from_function()` and class entrypoint metadata omit `OptionalArg` parameters
from their required arguments, so strict node validation permits their absence. Python
validates supplied payloads using the inner type; these dynamic arguments have no stored
CLType declaration. Explicit metadata remains authoritative. For typed remote calls,
`contract.call(function, MISSING)` omits that argument; passing `None` encodes
`Option::None` when the inner type is nullable. The marker is only valid on arguments,
not returns or stored values.

Contract-specific validation belongs in ordinary Python code. For example, `admin_list:
OptionalArg[list[Key]] = MISSING` can be checked with `if admin_list is MISSING: raise
InvalidAdminList()`. Malformed supplied payloads raise the normal `ABIError`;
annotations do not select application error classes.

### Return values

Fixed tuples of one to three elements use Casper Tuple1/Tuple2/Tuple3. For
example, `tuple[str, Key, str]` describes a CEP-78 mint receipt, and
`list[tuple[str, Key]]` describes its ownership receipts. Tuple elements are
validated and encoded in declaration order; variable-length tuples are unsupported.
As a wire annotation, `URef[T]` encodes the raw Casper URef (CLType URef) and
retains its value schema when decoded. A bare `URef` continues to encode a Key.

An annotated `-> None` encodes Unit. With no return annotation, the existing low-level
behavior applies: return a `CLValue`, or return `None` to complete normally. CLValue
subclass annotations also retain that explicit behavior. A wire-annotated export may
return an explicit CLValue; its CLType, payload and declared Key variant are checked.
`runtime.ret` remains the explicit completion signal and can return its supplied CLValue
directly. Ordinary returns are serialized after the function's `finally` blocks have
run.

### Enums

`WireEnum` subclasses are typed U8 annotations. For example, CEP-18 declares
`events_mode: EventsMode = named_keys.property()` and `change_events_mode(events_mode: EventsMode)`. Reads
and dispatch return enum members, and typed writes require that enum's members. Enum
return annotations and typed remote calls preserve the same type. Use
`Optional[EventsMode]` for nullable enum values and `OptionalArg[EventsMode]` for
presence. The backing CLType stays U8; unknown discriminants fail decoding. A standard
classmethod `_missing_` hook can raise a contract-specific exception.

### Exceptions and cleanup

`raise MissingKey()`, `raise InvalidArgument()` and `raise UserError(100)` are ordinary
Python exceptions derived from `ApiError`, catchable by `except Exception`. `UserError`
and `User` refer to the same class. Internal calls to exported functions still return
normally; the identity `@export` marker adds no dispatcher at the call site.

| Signal | `except Exception` | `finally` | If it escapes the entry point |
| --- | --- | --- | --- |
| `ApiError` (including `UserError`) | Catches it | Runs | Reverts and rolls back state |
| Ordinary Python exception | Catches it | Runs | Reverts and rolls back state |
| `runtime.revert(code)` (`Revert`) | Does not catch it | Runs | Reverts and rolls back state |
| `runtime.ret(value)` (`Ret`) | Does not catch it | Runs | Returns the serialized value successfully |

[Hello.greet](../contracts/hello.py) shows the difference in one method: an empty
name raises a caught `ValueError` and returns a fallback; a long name raises an
uncaught `UserError(1)`. The `finally` increment runs in both cases, but the
long-name invocation rolls that increment back. The
[native contract test](../tests/test_contract_packages.py) checks all three
paths, including the successful greeting.
Its `print("Greeting finished")` also runs on every path. Native pytest can
display and capture the three lines with `--capture=tee-sys`; debug Wasm sends
them to `casper_print`, while release Wasm discards their output. See the
[print debugging run](testing.md#print-debugging-in-native-tests) and
[compiled print capture](testing.md#captured-contract-prints).

The private C bridge returns `(status, value)` for every binding. Python interprets
nonzero ApiError statuses and raises known subclasses, including `MissingArgument`;
unrecognized codes remain `ApiError(code)`. Account key-management failure enums are
successful transport values. Optional reads handle only their documented missing-value
status. C performs pointer, buffer and wire-length checks, returning `InvalidArgument`
on validation failure. The outer C dispatcher loads all exception classes directly from
the SDK; the builder injects no error-registration code. Engine traps and failures that
do not return an FFI status still terminate execution.

`runtime.revert(code) -> NoReturn` raises `Revert(code)`, a `BaseException` subclass,
like Python's `SystemExit`. It bypasses `except Exception` while running applicable
`finally` blocks. Contract code can explicitly catch `Revert` or `BaseException`;
catching an exception preserves earlier writes. Only an uncaught signal reaches the
outer C dispatcher, which calls `casper_revert` and rolls back execution.

`runtime.ret(value) -> NoReturn` serializes the CLValue at the call site and raises
`Ret(payload)`, another `BaseException` subclass. It unwinds the current contract
invocation, including supported `finally` blocks, then the outer C dispatcher calls
`casper_ret` with the immutable payload. Cleanup writes persist on successful
completion. `except Exception` leaves the signal alone; `except Ret` or `BaseException`
can intercept it. An ordinary Python `return` exits only its function and uses the same
serialization helper after that function's cleanup. A called contract's successful host
return resumes its caller's `runtime.call_contract`.

Normal Python outcome replacement applies: an exception or another completion signal
raised by `finally` replaces the pending outcome, and a Python `return` in `finally`
suppresses it. This includes replacing a pending `Ret` with a revert or replacing a
pending `Revert` with a successful return. Return serialization errors remain catchable
at the explicit `ret()` call. The shared validator requires a complete CLValue envelope
and recursive CLType; it does not introduce additional authoring CLTypes or reinterpret
opaque serialized payloads.

Unannotated exports retain the low-level return interface: use `return CLU32(count)` for
an integer. A bare integer requires a wire return annotation such as `-> U32`; otherwise
it is rejected with `InvalidArgument`. `ENTRY_POINTS` supplies registration metadata
independently of invocation signatures.

### Floating-point calculations

`add_fractional` in [basic.py](../contracts/basic.py) demonstrates ordinary Python float
arithmetic while preserving U32 arguments and storage:

```python
updated = int(float(current) + float(amount) / 2.0)
storage.write(count, CLU32(updated))
```

With current value 6 and argument 3, the intermediate value is 7.5 and the stored result
is 7. `int()` truncates toward zero. A result outside U32 reverts with `InvalidArgument`
and preserves the previous count. Pause checks still apply.

### Reusable modules

The builder parses source without importing or executing the contract. It removes
`@export` markers and development annotations, bundles local `contracts.*` helper
imports, and freezes normal Python packages. In CPython, `export` is an identity
function. Helpers stay ordinary Python functions and receive no Wasm wrapper unless
explicitly selected.

Reusable procedural modules can supply both functions and metadata:

```python
from casthon import EntryPoint, export
from contracts import shared

ENTRY_POINTS = [*shared.ENTRY_POINTS, EntryPoint("local", {})]
get = export(shared.get)

@export
def local() -> None:
    ...
```

`get = export(shared.get)` explicitly selects the root name `get` and lowers to an
ordinary function binding. Its invocation signature comes from `shared.get`, including
annotation aliases and defaults. Export markers in a helper module do not automatically
expose imported functions from the root contract; the root selects its Wasm interface
explicitly. The builder does not synthesize or collect `ENTRY_POINTS`.

`ENTRY_POINTS` is ordinary Python data. It can use function calls, lists, tuples,
starred sequences, concatenation or mutation within the supported runtime profile. The
builder neither evaluates nor validates its contents, and the name `ENTRY_POINTS` has no
special meaning to the tooling. Different metadata collections can be passed to separate
version-registration calls. Serialization rejects duplicate entrypoint names; the node
rejects registration if a named function has no Wasm export.

`EntryPoint.from_function()` derives a selected export's name, parameter CLTypes and
return CLType from its invocation signature. Declare the collection after the referenced
procedural functions:

```python
ENTRY_POINTS = [
    EntryPoint.from_function(increment),
    EntryPoint.from_function(increment_by),
    EntryPoint.from_function(get),
    EntryPoint.from_function(get_increments),
]
```

Access rules, groups, execution type and payment remain explicit keyword arguments, with
the same defaults as `EntryPoint(...)`. An imported function uses its selected root
export name. When the same function has multiple export aliases, pass `name=`
explicitly. A raw `CLValue` return or absent return annotation requires `returns=`, such
as `returns=U32`; `-> None` infers Unit. Direct calls remain ordinary Python. Frozen
contracts read the same generated signature table as the dispatcher; CPython uses native
signature inspection.

`Optional[U32]` describes `Option<U32>` encoding. Its named argument is still required
by the Python dispatcher unless a Python default is declared. Casper's strict entrypoint
validator permits an absent Option parameter, but requires Option encoding when present.
A default such as `amount: U32 = 7` leaves the metadata type U32, so a strict node can
reject omission before Python runs. The factory preserves these rules; it does not infer
a separate presence flag.

## Calling a deployed contract

[counter_session.py](../contracts/counter_session.py) imports the counter class and uses
its annotations to call a deployed contract:

```python
from contracts.counter import Counter
from casthon import ContractHash, U32, UserError, export

@export
def call(contract: ContractHash, amount: U32, expected: U32) -> U32:
    contract.call(Counter.increment_by, amount)
    value = contract.call(Counter.get)
    if value != expected:
        raise UserError(1)
    return value
```

Build with `make build-counter-session`. Deploy the counter once, then submit the
session Wasm with `install=False` and named arguments `contract` as a
`CLKey(contract_hash)`, `amount` as `CLU32(5)` and `expected` as `CLU32(5)`. The
expected-value check demonstrates that the session decoded the counter's return. A
mismatch reverts the transaction, including the preceding increment.

`ContractHash.call(function, *args, **kwargs)` checks the Python argument binding,
encodes supplied values with the function's wire annotations, calls the host, and
decodes the result. Arguments may be positional or named; keyword-only parameters remain
keyword-only. IDEs infer ordinary argument and return types:
`contract.call(Counter.get)` returns `int`. Ordinary `Counter.bind().increment_by(5)`
continues to execute locally.

The session exports only `call`. The builder freezes imported modules and their ABI
signatures separately from root export selection. Imported modules keep their Python
bodies and import-time code; importing the module does not install its contract. Class
references omit `self` from the remote call signature.

Omitted defaulted arguments are omitted from the outgoing RuntimeArgs, so the deployed
function supplies its own defaults. The node can still reject an absent non-Option
argument according to registered metadata. Nullable values retain their `Option<T>`
encoding. Typed calls require a wire return annotation, including `-> None` for Unit,
and an unambiguous export name. The explicit `runtime.call_contract(hash, name, args,
return_type)` API handles other ABIs. The imported source describes the ABI expected by
the session; it does not verify the code or ABI installed at the supplied hash.

## Stored contract ABI and installation

`ENTRY_POINTS` describes the stored ABI. The session code passes this data explicitly
when registering a version:

```python
from casthon import EntryPoint, CLU32, U32, URef, MissingKey, export
from casthon.contract_api import runtime, storage

ENTRY_POINTS = [
    EntryPoint("increment_by", {"amount": U32}),
    EntryPoint("get", {}, U32),
]


@export
def increment_by() -> None:
    amount = runtime.get_named_arg("amount", U32)
    key = runtime.get_key("count")
    if not isinstance(key, URef):
        raise MissingKey()
    storage.write(key, CLU32(storage.read_or_revert(key, U32) + amount))


@export
def get() -> CLU32:
    key = runtime.get_key("count")
    if not isinstance(key, URef):
        raise MissingKey()
    return CLU32(storage.read_or_revert(key, U32))


@export
def call() -> None:
    count = storage.new_uref(CLU32(0))
    package, access = storage.create_contract_package_at_hash()
    contract, version = storage.add_contract_version(
        package, ENTRY_POINTS, {"count": count}
    )
    runtime.put_key("counter", contract)
    runtime.put_key("counter_package", package)
    runtime.put_key("counter_access", access)
```

Here all three functions are Wasm exports, and the installation registers only
`increment_by` and `get` as stored-contract entrypoints. Merely listing a name in the
metadata does not export its Python function; merely exporting a function does not
register its stored ABI.

`EntryPoint` is ABI data, independent of Python function annotations. Access rules,
entrypoint types and payment modes are explicit enum fields, with public access,
called-contract execution and caller payment as defaults. The C adapter receives the
serialized entrypoints from Python; it has no generated ABI table or contract-specific
error profile. Class contracts collect inherited metadata in the Python layer.
`EntryPoint` accepts a mapping or an ordered sequence of `(name, annotation)` pairs;
factories preserve signature order explicitly in frozen MicroPython.

## Low-level API

| Python module | Supported functions |
| --- | --- |
| `casthon.contract_api.runtime` | `get_named_arg`, `try_get_named_arg`, `ret`, `revert`, `get_key`, `has_key`, `put_key`, `remove_key`, `list_named_keys`, `get_caller`, `get_protocol_version`, `blake2b`, `call_contract`, `emit_message` |
| `casthon.contract_api.storage` | `read`, `read_from_key`, `read_or_revert`, `new_uref`, `write`, `add`, `new_dictionary`, `dictionary_get`, `dictionary_put`, `create_contract_package_at_hash`, `add_contract_version`, `disable_contract_version` |

The remaining upstream `ext_ffi` functions are exposed through these procedural modules:

| Module | Additional functions |
| --- | --- |
| `runtime` | `list_authorization_keys`, `is_valid_uref`, `get_blocktime`, `get_phase`, `get_block_height`, `get_parent_block_hash`, `get_state_hash`, `get_addressable_entity`, `get_call_initiator`, `get_immediate_caller`, `get_call_stack`, `get_legacy_call_stack`, `random_bytes`, `call_versioned_contract`, `call_package_version`, `manage_message_topic` |
| `storage` | `dictionary_read`, `create_contract_user_group`, `provision_contract_user_group_uref`, `remove_contract_user_group_urefs`, `remove_contract_user_group`, `add_contract_version_legacy`, `add_package_version`, `enable_contract_version` |
| `account` | `get_main_purse`, `add_associated_key`, `remove_associated_key`, `update_associated_key`, `set_action_threshold` |
| `system` | `get_system_contract`, `get_mint`, `get_handle_payment`, `get_standard_payment`, `get_auction`, `create_purse`, `get_purse_balance`, `get_balance`, `transfer_to_account`, `transfer_to_public_key`, `transfer_from_purse_to_account`, `transfer_from_purse_to_public_key`, `transfer_from_purse_to_purse` |
| `cryptography` | `generic_hash`, `recover_secp256k1`, `verify_signature` |

Account key-management functions return `None` on success or a typed failure enum. Other
host API errors raise `ApiError` subclasses; an uncaught error reverts at the export
boundary. Transfer-to-account functions return `TransferredTo.EXISTING_ACCOUNT` or
`NEW_ACCOUNT`; transfer amounts and balances use U512, and transfer IDs use `U64 |
None`. `get_phase()` returns a `Phase` enum. CPython uses `IntEnum`; the frozen SDK
preserves member types, names, values, integer conversion and equality through a small
Python compatibility implementation.

Caller inspection returns `AccountCaller`, `ContractCaller` or `EntityCaller` instances
with typed identity properties. The legacy stack function returns `Session`,
`StoredSession` or `StoredContract` variants. A direct session can have no immediate
caller; the node then returns `ApiError::Unhandled`. Public keys and signatures use
explicit `Ed25519PublicKey`, `Secp256k1PublicKey`, `Ed25519Signature` and
`Secp256k1Signature` types. Signature verification raises an API error for invalid
signatures. Hash algorithms are selected with `HashAlgorithm.BLAKE2B`, `BLAKE3` or
`SHA256`.

`EntryPoint` additionally accepts `access`, `groups`, `entry_point_type` and `payment`.
Group-restricted access uses `EntryPointAccess.GROUPS` and an explicit sequence of
labels. The legacy version-registration function emits the older entrypoint layout
without a payment field and rejects metadata it cannot represent. Package creation
accepts `is_locked=True`. Message topics accept `MessageTopicOperation.ADD` (the only
operation upstream currently defines), and message payloads use `MessageString` or
`MessageBytes`.

The native module binds all 58 declarations in the local upstream `ext_ffi.rs`,
including deprecated functions and the test-support print function. Debug Wasm imports
all 58 functions; release Wasm omits `casper_print`. The [upstream signature
snapshot](../reference/ext-ffi.json) checks their signatures. Host-buffer transport
stays internal. Availability of individual system contracts and host operations depends
on the node configuration; the stock devnet asset does not register a Standard Payment
contract hash. Sessions that add contract versions must be submitted with the
transaction's install/upgrade flag. Transfers from the main purse need an
approved-spending `amount` transaction argument. Message topics and emission require
stored-contract context.

Built-in `print()` uses `casper_print` in the default debug profile. Uncaught exceptions
also print their Python traceback and message after `finally` blocks run. Caught
exceptions and successful `Ret` signals stay quiet.

Build with `casthon build counter --release` or `python scripts/build.py counter
--release` to discard stdout and compile out dispatcher diagnostics. Release artifacts
use `build/release/` and have no `casper_print` import. Expressions and string
conversions passed to `print()` still run. See [build profiles](casthon.md).

`add_package_version()` returns a `ContractEntity` when addressable entities are
enabled, or a legacy `ContractHash` otherwise. Group membership accepts an iterable of
`URef` capabilities and serializes a deduplicated, ordered set.

`get_named_arg(name, type)` decodes an explicit named argument. `try_get_named_arg`
returns `None` for missing or malformed payloads, following Rust. `get_caller()` returns
the account initiating the transaction, matching Rust's `get_caller`; it does not
substitute the immediate contract package identity.

`storage.read` returns `None` for missing values; `read_or_revert` raises `Read` for
caught decoding errors and `ValueNotFound` for absence. Dictionary item keys exceeding
64 UTF-8 bytes raise `DictionaryItemKeyExceedsLength`. These are ordinary `ApiError`
subclasses, catchable by `except Exception`; an uncaught error reverts at the outer C
boundary with the original Casper code. Decoding never changes a shared error code. Host
`add` supports Casper's addable CLTypes, including U64 and U256; U32 is rejected by the
engine. Dictionaries take a seed `URef` and an explicit string item key. Runtime
arguments use a mapping of names to explicitly typed CLValues:

```python
runtime.call_contract(contract, "increment_by", {"amount": CLU32(5)})
count = runtime.call_contract(contract, "get", {}, U32)
```

`Key`, `URef`, `ContractHash`, `ContractPackageHash`, `CLValue` and its subclasses
remain Casper data types. Legacy hash Key bytes do not distinguish contract and package
roles; the package APIs return the known role explicitly. U8/U32/U64/U256/U512 authoring
annotations map to unsigned wire types; mypy treats them as `int`, while CLValue
constructors enforce their ranges.

`runtime.named_keys` provides collection access to the current context's bindings:

```python
keys = runtime.named_keys
keys["balance"] = storage.new_uref(CLU256(7))
balance = keys["balance"]
if isinstance(balance, URef):
    balance.write(CLU256(10))
    balance.add(CLU256(2))
    amount = balance.read(U256)
for name, key in keys.items():
    print(name, key)
del keys["balance"]
```

Assignment changes a named-key binding; `URef.write()` and `URef.add()` change the
referenced value. Removing a binding leaves its stored value intact. `keys[name]` and
deletion raise `KeyError` for missing names; `.get(name, default)`, membership and
direct lookups query the current context. These operations also remain available through
the procedural runtime functions.

Iteration, `.keys()`, `.items()` and `.values()` return snapshot iterators. Each
iterator loads one serialized host listing when created, then decodes entries as
consumed, without materializing a dictionary or list. Names-only iteration does not
construct `Key` objects. The host API returns the entire listing; it does not support
paging. `len(keys)` also loads the listing to read its count.
`runtime.list_named_keys()` explicitly materializes a dictionary snapshot.

The `read`, `write` and `add` methods live on `URef` itself. `URef.read(type)` delegates
to `storage.read`, including returning `None` for missing values. An untyped URef
requires the explicit type because the host returns value bytes without their CLType.
`storage.read`, `read_or_revert`, `write` and `add` reject non-URef arguments with
`TypeError` before calling the host; `read_from_key` deliberately accepts other Key
variants. The host enforces access rights.

## Typed state references

`named_keys.reference(name, schema)` declares a lazy binding with a read-only `.name`
property. Declaration performs no host calls. `URef[T]` specifies the referenced value
type; a Key subclass such as `ContractHash` specifies a direct named-key value:

```python
counter = named_keys.reference("count", URef[U32])
installed = named_keys.reference("py_counter", ContractHash)
installed_package = named_keys.reference("py_counter_package", ContractPackageHash)
installed_access = named_keys.reference("py_counter_access", URef[None])
```

Key and URef references support `.get()`, `.set(key)` and `.remove()` for the binding.
Missing references raise `MissingKey`, and resolving a wrong key variant raises
`InvalidArgument`. Hash wire bytes do not distinguish contract/package roles; the
declared role determines the returned Python subclass. `.remove()` is idempotent and
removes the named key without deleting storage or revoking other capabilities. Each
`.get()` resolves the current context and binding; the reference never caches an
address.

URef references also support `.read()`, `.write(value)`, `.add(value)` and
`.create(value)`. Reads are strict, using `read_or_revert` semantics. Writes and
allocation encode the declared CLType and validate bounds before mutation; explicit
CLValues must match that type. `.get()` returns an ordinary URef carrying the same value
schema, so its methods also accept plain values and omit the read type. `.add()` accepts
the available addable unsigned CLTypes U64, U256 and U512; U32 uses explicit
read/modify/write.

`Dictionary[K, V](key=transform)` declares typed item access through a seed URef. `K`
may be a Python key class or a supported wire annotation; the callable maps it to a
deterministic UTF-8 string. String keys default to identity. Transform output is
validated against the SDK's 64-byte compatibility limit. Changing the transform changes
item addresses, so it is part of the contract's persistent schema.

```python
def account_key(account: AccountHash) -> str:
    return bytes(account)[1:].hex()

increments = named_keys.reference(
    "increments", Dictionary[AccountHash, U32](key=account_key)
)

def increment_for(owner: AccountHash) -> U32:
    updated = increments.get(owner, 0) + 1
    increments[owner] = updated
    return updated
```

An entrypoint can call `increment_for` after the dictionary seed is installed.
The first call for an account starts from zero; later calls read and update its
stored tally. Dictionary references expose collection operations directly. Each
item access resolves
the current named-key seed internally; `.get(key, default)` reads an item, while `.seed`
explicitly retrieves the current URef. `.set(seed)` and `.remove()` manage the named-key
binding. Item indexing raises `KeyError` on absence, and membership distinguishes
missing items from stored Unit/None values. Reads and writes use the existing dictionary
FFI and value decoder. The wrapper provides no item enumeration, length, deletion or
dictionary-add operation.

Creation only allocates and returns a URef; it never binds a name. Installation uses an
ordinary dictionary, without repeating names or value CLTypes:

```python
initial_keys = {
    counter.name: counter.create(0),
    increments.name: increments.create(),
}
contract, version = storage.add_contract_version(package, ENTRY_POINTS, initial_keys)
installed.set(contract)
installed_package.set(package)
installed_access.set(access)
```

`storage.new_dictionary_seed()` exposes allocation without binding;
`storage.new_dictionary(name)` retains its existing allocate-and-bind behavior. For
current-context initialization, use explicit assignment or `.set(key)`.
Removing/replacing a binding leaves any previously resolved URef or dictionary view
attached to its original capability. The value schema governs decoding but cannot verify
the original stored CLType tag, which the read FFI omits.

The freezer translates `URef[T]` and `Dictionary[K, V]` declarations into ordinary
`.of(...)` factories, preserving aliases and key callables. CPython uses the same
factories through class subscription. Generic typing machinery and class-subscription
hooks are removed from frozen SDK classes; no interpreter modifications are required.

Authoring and frozen code share wire-descriptor resolution, including `type(None)` for
Unit and explicitly supported descriptor strings. The builder lowers evaluated generic
annotations such as `list[Key]`, `dict[Key, U8]` and supported `typing.Annotated`
aliases to descriptors without executing contract source. Unsupported generic wire
annotations fail at build time. `storage.new_dictionary(name)` checks empty names and
collisions, creates the seed, and installs its named key in Python; the C binding only
allocates the dictionary seed.

[contracts/api_smoke.py](../contracts/api_smoke.py) exercises dictionaries, URefs, host
`add` with U256, named-key listing/removal, initiating caller identity, hashing,
protocol version and cross-contract calls with explicit return decoding. It composes the
`read_count` function and its entrypoint metadata from [a procedural helper
module](../contracts/api_smoke_helpers.py), alongside its two explicit session exports.

[contracts/ffi_smoke.py](../contracts/ffi_smoke.py) exercises the additional FFI
families with procedural sessions and small stored entrypoints: account-key changes,
purse transfers, restricted access and user groups, both versioned call interfaces,
legacy/new version registration, dictionary-address reads, all three digest algorithms,
Ed25519 verification, Secp256k1 verification/recovery, and message topics/payloads.

[contracts/typed_exports.py](../contracts/typed_exports.py) exercises annotated
arguments and returns, a reusable imported export, ordinary internal calls, nullable
values, Python defaults, explicit CLValues, Key variant validation and cleanup before
boundary serialization. Build it with `make build-typed-exports`.

## Events

An event is an annotated record. A plain `Event` subclass emits its fields as
Bytesrepr in a `MessageBytes` payload by default:

```python
from casthon import Event, Json, emit
from casthon.contracts import Contract, entry_point, export_contract

class Greeted(Event):
    name: str

@export_contract
class Greeter(Contract):
    @entry_point
    def greet(self, name: str) -> None:
        emit(Greeted(name))

    @entry_point
    def greet_json(self, name: str) -> None:
        emit(Greeted(name), encoder=Json.to_message)
```

`emit(event)` calls the record's `to_message()` and sends it to the `"events"` topic.
Register that topic when adding the contract version, using
`package.add_contract_version(Greeter(), message_topics=("events",))`. Select
another registered topic with `emit(event, topic="audit")`.
Record construction and encoding failures raise ordinary Python exceptions;
host message-delivery errors raise `ApiError` subclasses. Both can be caught
before they escape the entry point.

For `Greeted("Ada")`, the default payload is `03 00 00 00 41 64 61` in hex:
the four-byte little-endian string length followed by UTF-8 `Ada`. The JSON
entry point instead sends the text `{"name":"Ada"}`. `Json.to_message` can
encode a plain event when selected with `encoder=`. To make JSON the record's
default, inherit `Json` as a mixin: `class Greeted(Event, Json)`.
`JsonBytes` produces UTF-8 JSON in `MessageBytes`; an explicit `Bytesrepr`
mixin also produces binary field data. Multiple encoder mixins require an
explicit choice such as `emit(event, encoder=Json.to_message)`, or a record-defined
`to_message()` default. Encoder failures are ordinary catchable Python exceptions.

Contract mixins can declare `events = (Greeted,)`; `Contract.event_types()` collects
their schemas. Native message delivery does not need an ambient contract object. CES
storage has its own explicit backend, `casthon.ces`. `ces.emit` always encodes
event fields as Bytesrepr and accepts plain `Event` subclasses. The
[CEP-18 guide](cep18.md) covers event composition, CES and message formats.
