# CEP-18 class contract

[Cep18](../contracts/cep18.py) ports the Rust CEP-18 **2.0.0** contract at
[`7fa83c5`](https://github.com/casper-ecosystem/cep18/tree/7fa83c559d04b3516e06b4d7202aba912c14c235).
[MyToken](../contracts/my_token.py) inherits its state and all 16 entrypoints:

```python
@export_contract
class MyToken(Cep18):
    def __init__(self, name="My Token", symbol="MYT", decimals=18,
                 total_supply=1_000_000 * 10**18, *, events_mode=EventsMode.CES,
                 enable_mint_burn=1, **state):
        super().__init__(name, symbol, decimals, total_supply,
                         events_mode=events_mode,
                         enable_mint_burn=enable_mint_burn, **state)
```

The source has full wire annotations; the example above omits them for space.
Constructors run ordinary Python, create typed state, and support cooperative
`super().__init__(..., **state)` composition. Invocation uses `MyToken.bind()`
without repeating initialization. Only the concrete root class has
`@export_contract`. Importing `Cep18` or `MyToken` into another contract does not
export their methods.

## Installation and upgrades

```sh
make build-my-token
```

The top-level `@export def call(...)` declares its installer inputs as typed
parameters. The dispatcher loads them before invoking the function; the
installer and CEP-18 methods contain no manual named-argument reads. The
installer explicitly creates a package, registers a
version using the instance's inherited ABI and named keys, adds the `events`
message topic, and calls `init`. It writes the upstream account key names:

* `cep18_contract_package_My Token`
* `cep18_contract_package_access_My Token`
* `cep18_contract_hash_My Token`
* `cep18_contract_version_My Token`

The suffix follows the token's name. Optional installer arguments override the
constructor defaults: `name`, `symbol`, `decimals`, `total_supply`, `events_mode`,
`enable_mint_burn`, `admin_list`, and `minter_list`. Lists use `CLKeyList`;
numeric arguments use their declared CLTypes. `OptionalArg[T]` distinguishes
missing arguments (`MISSING`) from supplied values. Installer arguments use
defaults when omitted. `change_security` checks each list for `MISSING` in its
method body and raises `InvalidAdminList`, `InvalidMinterList` or `InvalidNoneList`.
Supply an empty list when making no changes to a badge category. Malformed
supplied lists and flags raise the normal SDK `ABIError`; no annotation remaps
decoder exceptions to application errors.

The constructor creates balances, allowances, security badges and scalar URefs
without putting these names in the installing account. The deployer receives
the initial supply and an Admin badge, subject to upstream's initial badge-list
precedence. The stored `init` records `package_hash` and `contract_hash`, initializes CES
storage when selected, and emits the first Mint event. Its guard checks the
existing `package_hash`, since dictionaries already exist after construction.
Replaying it with valid decoded arguments raises `AlreadyInitialized` (User 60015).
Its ABI remains parameterless; deployment hashes are explicit dynamic arguments.
Their annotations are `OptionalArg[Key]`: they are omitted from the registered
ABI, and the method explicitly raises `MissingArgument` if either is `MISSING`.
The installer calls
`contract.call(MyToken.init, package_hash=package, contract_hash=contract)` using
that same signature.

Calling the installer again with the same name adds a version sharing existing
state, retains message topics, disables the previous version and updates the
account's contract hash/version. An optional `events_mode` applies to the new
version. The tests exercise upgrades between versions of this Python contract;
migration of historical Rust 1.x installations has not been validated.

## State and behavior

State uses value annotations with `named_keys.property()`, including
`Dictionary[K, V]` views. Getter methods such
as `name()` use a different Python attribute (`token_name`) bound to the original
storage name (`name`). Dictionary operations use normal collection syntax:

```python
self.balances[recipient] = received
self.supply = supply
```

Balance and security keys are base64 of the complete Key bytes, preserving
upstream dictionaries. Account/hash Key bytes occupy 33 bytes, so hex would
exceed Casper's 64-byte dictionary item-key limit. Allowances use
`blake2b(bytes(owner) + bytes(spender)).hex()`. Typed key transforms hide these
encodings from entrypoint bodies.

Transfers check balances and U256 overflow before writing. The dispatcher
validates annotated U256 arguments before calling a method. Ordinary local calls
follow Python's usual typing conventions and receive no extra argument checks.
Allowance increases and decreases saturate at U256's bounds. A zero `transfer` emits an event; a
zero `transfer_from` returns without consuming allowance or emitting. Both
still reject upstream's forbidden self targets. Mint requires Admin or Minter;
burn requires the caller to own the burned balance. Mint/burn and security
changes require a nonzero `enable_mint_burn` U8, matching Rust's behavior.

`change_security()` retains upstream's zero-parameter ABI and receives optional
dynamic lists through its typed parameters. Its feature and authorization checks
use an ordinary `@require_security_admin` decorator, after argument decoding.
Revocation overrides Admin, which overrides Minter; the caller
cannot revoke or downgrade itself through this entrypoint. Caller identity
comes from `get_immediate_caller()`: an account, a legacy contract's **package**,
or an addressable entity. A stored caller never spends the initiating account's
tokens or allowance by accident.

`EventsMode` is a closed `WireEnum` with `NO_EVENTS`, `CES`, `NATIVE` and
`NATIVE_BYTES` members. The state declaration is `events_mode: EventsMode = named_keys.property()`;
constructors and `change_events_mode()` accept the enum directly:

```python
token = MyToken(events_mode=EventsMode.CES)
mode = token.events_mode                    # EventsMode.CES
token.events_mode = EventsMode.NATIVE
contract.call(Cep18.change_events_mode, EventsMode.NATIVE_BYTES)
```

The enum serializes as U8, preserving the Rust ABI and existing stored values.
`change_events_mode()` assigns the property to update its existing cell, preserving
the URef and its named-key binding. This intentionally differs from upstream's
`put_key(..., new_uref(...))`: changing a mode does not leave an old cell behind.
Decoding returns canonical enum members. Typed writes require members of the
declared enum; an explicit `CLU8` is also accepted after validating its
discriminant. Unknown modes raise `InvalidEventsMode` (User 60006) through the
standard enum `_missing_` hook, including during dispatch and storage reads.
`Optional[EventsMode]` and `OptionalArg[EventsMode]` compose with the same rules.

`SecurityBadge` remains a `WireEnum` subclass with the upstream dictionary's
explicit U8 schema. CPython uses IntEnum; the frozen build preserves member
identity, names, values and integer conversion through a small compatibility
implementation. WireEnum discriminants must be distinct integers in 0–255.
Application declarations may define a classmethod `_missing_` hook; other methods
and decorators are outside the current frozen enum profile.

Event records are top-level classes with annotated fields and explicit encoder
mixins. The base `Event` owns record metadata and construction; encoders produce
`MessageString` or `MessageBytes`. Delivery uses `emit` with the event instance:

```python
from casthon import Event, Bytesrepr, Json, Key, U256, emit

class Mint(Event, Bytesrepr):
    recipient: Key
    amount: U256

emit(Mint(recipient, amount))
```

With one encoder, `to_message()` uses it automatically. `Bytesrepr` encodes just
the ordered fields as `MessageBytes`; `Json` returns JSON in `MessageString`;
`JsonBytes` returns UTF-8 JSON in `MessageBytes`. Binary messages can contain any
format. Encoding does not imply a decoder or require `to_bytes` / `from_bytes`
methods on the record.

For multiple encoders, select one explicitly:

```python
class Mint(Event, Bytesrepr, Json):
    recipient: Key
    amount: U256

record = Mint(recipient, amount)
emit(record, encoder=Json.to_message)
emit(record, encoder=Bytesrepr.to_message)
```

Without `encoder=`, delivery calls `record.to_message()`, which raises `TypeError`
when encoders are ambiguous.
A record can define its own `to_message()` to select an explicit default. Each
mixin uses the same `MessageString | MessageBytes` return annotation so multiple
inheritance remains compatible with Python type checkers. Custom stateless
encoders inherit `MessageEncoder` and implement that method; a custom record can
also override `to_message()` directly. No runtime ABC machinery is needed.
`encoder=` accepts a callable taking the event and returning `MessageString` or
`MessageBytes`. The default topic is `"events"`; use `emit(record, topic="audit")`
to select another registered topic. Encoding errors remain catchable Python
exceptions and occur before the host emission call. `emit` accepts event instances;
the low-level `runtime.emit_message(topic, payload)` accepts `MessagePayload` or
its serialized bytes.

Constructors accept positional and keyword arguments and perform no host I/O.
Fields are required, ordered annotations; defaults and custom record constructors
are unsupported. Records support one record parent followed by encoder mixins.
The freezer binds schemas and constructors without executing application source;
it rejects inheritance that would resolve differently in upstream MicroPython.
`Map[K, V]` is an ordinary dict encoded as a CL Map, distinct from persistent
`Dictionary[K, V]` state. Nested collections and nullable fields use structural
CLType descriptors throughout encoding and validation.

Contract/mixin `events = (...)` tuples contribute schema declarations across the
MRO. Identical classes are deduplicated; conflicting wire names are rejected.
`Contract.event_types()` returns the effective tuple. Native message delivery
uses the topic registered with Casper and does not need a contract instance or
an ambient Python contract object.

CES is an explicit storage backend in `casthon.ces`:

```python
from casthon import ces

# Within a stored contract:
ces.initialize(MyToken.event_types())
ces.emit(record, events=MyToken.event_types())
```

`ces.emit` requires `Bytesrepr`, adds the `event_<name>` envelope, and writes CES
history. Its optional `events=` argument checks an explicit registry before any
write. `ces.initial_named_keys(events)` creates a dict of CES keys for an explicit
installer without binding them into the account. Initialization is idempotent.
`package.add_contract_version(contract)` registers the instance's state and ABI without
choosing an event backend; `Contract` has no `emit` method.

CEP-18 declares a shared `Cep18Event(Event, Bytesrepr, JsonBytes)` base. Its module
function `emit(event)` reads EventsMode and selects CES, JSON text, UTF-8 JSON
bytes, or no emission. The ChangeSecurity record customizes JSON badge names;
its binary schema remains `Map[Key, U8]`. The stored `init` initializes CES when
selected, and mode switches preserve existing history. Built-in serializers
validate typed fields before delivery; failed serialization remains catchable,
and uncaught failures revert and roll back at the outer dispatcher.

Events support modes 0 (off), 1 (CES), 2 (native String), and 3 (native Bytes).
All nine event layouts, CES schemas and native JSON payloads match independent
Rust fixtures. CES history survives event-mode switches. Mode changes replace
the named URef, as upstream does. Field and ABI parameter order is represented
explicitly so it survives MicroPython's unordered dictionaries.

## Exceptions and tests

Contract failures use named, catchable subclasses of `Cep18Error(UserError)`,
preserving upstream User numbers 60000–60038. Ordinary local calls can catch
them and run `finally`. Only an uncaught exception reaches the outer C
dispatcher and reverts the invocation. Returned values are ordinary Python
integers/strings; annotations select the returned CLValue.

Annotated arguments are decoded before entering the method. This intentionally
uses our existing dispatcher convention: when multiple inputs are invalid,
error precedence can differ from Rust's interleaved argument reads and guards.
The installer decodes all supplied inputs before choosing installation or
upgrade, including creation-only options on an upgrade. The `init` replay check
and `change_security` authorization checks use ordinary `@require_uninitialized`
and `@require_security_admin` Python decorators beneath `@entry_point`.
They run after argument decoding, once per invocation. Malformed supplied data
therefore raises `ABIError` before these guards run. Local calls use
their supplied Python arguments without loading named arguments.
Storage/capability failures use SDK exceptions; this port does not reproduce
every Rust `unwrap_or_revert_with` remapping for corrupted internal state.

```sh
make test-native
make typecheck
make test-wasm
PYTHONPATH=src CSPR_LIVE_TESTS=1 .venv/bin/python -m unittest discover \
    -s tests/live -p test_cep18.py -v
```

Native tests use `MockHost` and `ContractHarness`. Wasm tests execute both plain
and Casper-metered artifacts with the stock 500-slot stack limiter. Live tests
own a four-node Casper 2.2.0 network and stop it through class cleanup. They
deploy the inherited token, exercise permissions and upgrades, and check typed
return values through an imported-ABI session. A stored client checks package
identity across contract calls. These clients live under `tests/fixtures/`;
the session exports only `call`.

The [Rust fixtures](../reference/cep18/fixtures.json) are independent compatibility
inputs. Recorded checks include the [original port](../results/cep18.json),
[event delivery](../results/event-emit.json), and
[typed argument loading](../results/cep18-argument-injection.json).
Each report names its own artifacts and validation scope. For the hash and size
of a current build, read `build/my_token-build-report.json` or the corresponding
profile directory.
