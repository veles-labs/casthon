# CEP-78 class contract

[Cep78](../contracts/cep78.py) ports the collection behavior of the Rust CEP-78
**2.0.0** reference at
[`9a624aa`](https://github.com/casper-ecosystem/cep-78-enhanced-nft/tree/9a624aa9a4f5cba59260f93652b76948e528c7f2).
[MyNft](../contracts/my_nft.py) inherits all 17 stored entrypoints and supplies
collection defaults and an explicit installer. The upstream Apache 2.0 license
and independent Rust serialization fixtures are in [reference/cep78](../reference/cep78/README.md).

The structure follows [CEP-18](cep18.md): an unexported base class, one exported
concrete class, cooperative constructors, typed persistent fields, closed U8
enums, named exceptions, typed events, and no manual named-argument reads in
entrypoint bodies. Importing the base or example into a caller does not add its
Wasm exports to that caller.

## Build and install

```sh
make build-my-nft
```

This produces `build/my_nft.wasm` and `build/my_nft.metered.wasm`. Deploy the
installer with no arguments to create **My NFT**, symbol **MNFT**, with a maximum
of **1,000** tokens. Its defaults are installer-only minting, transferable tokens,
mutable NFT721 metadata, ordinal identifiers, burnable tokens, complete owner
reverse lookup, and CES events. These choices belong to the example; `Cep78`
defaults to immutable CEP78 metadata, no lookup, and no events.

The installer accepts typed optional overrides for every constructor modality.
For example, pass `identifier_mode` as U8 `1` and `metadata_mutability` as U8 `0`
for hash identifiers, or `minting_mode` as U8 `1` for public minting. Invalid
combinations fail before construction allocates state. The supply must be between
1 and 1,000,000. `OptionalArg[T]`/`MISSING` distinguishes omission from supplied
false, zero, empty strings, and empty lists. Supplied malformed values fail normal
SDK decoding; the port does not remap decoder exceptions to application errors.

Construction creates the state without publishing its fields into the account.
The installer creates a package, adds the initialized instance with its inherited
ABI and an `events` message topic, and calls `init` with the package's formatted
string. `init` is installer-only and can complete once. The account receives:

* `cep78_contract_package_My NFT`
* `cep78_contract_package_access_My NFT`
* `cep78_contract_hash_My NFT`
* `cep78_contract_version_My NFT`

The suffix uses `collection_name` exactly. Different names create independent
collections. Stored context keeps a `cep78_<collection_name>` URef containing the
package string and a `cep78_python_layout` marker.

## Mint and use an NFT

With complete reverse lookup, register each recipient before minting or
transferring to it. The same class ABI works in Python sessions and other stored
contracts:

```python
from cspr import ContractHash, Key
from contracts.cep78 import Cep78

def issue(nft: ContractHash, owner: Key) -> str:
    nft.call(Cep78.register_owner, owner)
    receipt_name, receipt_address, token_id = nft.call(
        Cep78.mint, owner,
        '{"name":"First NFT","symbol":"MNFT","token_uri":"ipfs://first"}',
    )
    return token_id
```

This function can be used by an authorized installer session or an allowed stored
minter. Default installer minting requires the immediate caller to be the
installing account. A stored contract needs public or ACL minting.

Pass ordinal identifiers as `token_id: U64`, and hash/custom identifiers as
`token_hash: str`. These dynamic parameters are typed `OptionalArg`s and are
omitted from the registered ABI, matching upstream's identifier-less metadata.
The selected mode determines which identifier is required. Example calls:

```python
owner = nft.call(Cep78.owner_of, token_id=0)
balance = nft.call(Cep78.balance_of, owner)
metadata = nft.call(Cep78.metadata, token_id=0)
nft.call(Cep78.approve, spender, token_id=0)
nft.call(Cep78.transfer, owner, recipient, token_id=0)
nft.call(Cep78.burn, token_id=0)
```

The token owner, its single approved spender, or an authorized operator can
transfer. Transfer clears the single approval. Owners and operators can approve
or revoke a spender; an approved spender cannot appoint another spender.
`set_approval_for_all(approve_all, operator)` sets a persistent owner/operator
pair. Self transfers preserve the balance and ownership bit while clearing
approval. `MINTER` and `ASSIGNED` ownership prevent transfers and approvals.

Burning retains ownership, metadata, reverse lookup records, and the historical
mint count. It reduces the owner's live balance and prevents further transfers,
approvals, or repeated burns. Burning does not reopen a supply slot. Operators
may burn only when `operator_burn_mode` is enabled; a single approved spender
does not have burn permission.

## State, identities and metadata

State uses `URef[T]` and `Dictionary[K, V]`. Ownership and metadata dictionaries
use decimal ordinal strings or the supplied hash/custom string. Address keys use
the underlying account/contract/entity/package address as 64 lowercase hex
characters, matching upstream. Operators use
`blake2b(bytes(owner) + bytes(operator)).hex()`. Hash identifiers default to
BLAKE2b-256 of the **original metadata string**, before normalization. A supplied
nonempty `token_hash` overrides that identifier. Duplicates are rejected; Casper's
64-byte dictionary item limit also applies to custom identifiers.

CEP-78 identities differ from CEP-18: a legacy stored caller owns and issues
tokens as its **contract version**, with its package available separately for
ACL and operator checks. Entity callers use their entity Key and package.
An initiating account does not lend its NFT ownership or installer permissions
to a stored caller. `acl_package_mode` selects package-based mint whitelisting;
`package_operator_mode` also checks approvals granted to the caller's package.
The reference's Contracts holder mode rejects account minters.

Four metadata kinds are supported:

| Kind | Required data |
| --- | --- |
| `CEP78` (0) | Nonempty string `name`, `token_uri`, `checksum` |
| `NFT721` (1) | Nonempty string `name`, `symbol`, `token_uri` |
| `RAW` (2) | Any string, stored unchanged |
| `CUSTOM_VALIDATED` (3) | A string-valued JSON object checked against `json_schema` |

Custom schema format follows upstream; it is not general JSON Schema:

```json
{
  "properties": {
    "artist": {"name": "Artist", "description": "Creator", "required": true}
  }
}
```

Additional required and optional metadata kinds use `list[NFTMetadataKind]`
(CL `List<U8>`). Required kinds take precedence over optional ones. All required
validations complete before writes; optional failures are skipped. `metadata`
returns the first required kind in numeric order. Structured metadata is stored
using Rust's pretty JSON formatting, including field ordering and escaping.
The frozen runtime's metadata reader validates JSON without `eval`, rejects
duplicate keys and invalid Unicode surrogates, and bounds nesting to 32 levels.

Only the current owner may update mutable metadata. Hash identifiers require
immutable metadata. Getter behavior after burn follows upstream: ownership and
metadata remain queryable. `get_approved` rejects burned tokens.

## Reverse lookup and returns

Reverse lookup keeps `page_table` and lazily allocated `page_<n>` dictionaries.
Each owner page contains 1,000 boolean token positions. Registration allocates
the owner's table; receiving a token allocates the relevant page. Complete
lookup tracks minting and transfers. Transfers-only lookup begins tracking on
transfer and requires both parties to register. Receipt names have the form
`cep78_My NFT_m_1000_p_0`; their addresses are Casper dictionary Keys.

`mint` returns `(receipt_name, dictionary_key, token_identifier)` with complete
lookup. `transfer` returns `(receipt_name, source_dictionary_key)` when lookup is
enabled. `register_owner` returns `(collection_name, package_string_uref)` when
lookup is enabled. `updated_receipts` returns a list of receipt pairs with
complete lookup. The SDK supports fixed `tuple[T]`, `tuple[T, U]`, and
`tuple[T, U, V]` wire types, including nested lists, and typed `URef[T]` wire
values for the registration receipt. A bare `URef` annotation continues to use
the SDK's existing Key representation.

Upstream declares receipt return types even in modes that return no receipt.
The port preserves Unit in those modes using explicit `runtime.ret(CLUnit())`.
For direct local Python calls in those modes, this raises the normal `Ret`
completion signal. Receipt-producing calls use ordinary Python returns. Remote
typed receipt calls require a mode that returns the declared receipt; a session
calling a no-lookup entrypoint can use the low-level `runtime.call_contract` with
Unit as its expected return type.

## Events, configuration and upgrades

The port declares all ten typed event records in
[cep78_events.py](../contracts/cep78_events.py). `EventsMode` values differ from
CEP-18:

| Mode | Value | Delivery |
| --- | --- | --- |
| `NO_EVENTS` | 0 | No emission |
| `CEP47` | 1 | String maps and U64 `len` in the `events` dictionary |
| `CES` | 2 | Casper event standard schemas and event history |
| `NATIVE` | 3 | JSON in a native String message |
| `NATIVE_BYTES` | 4 | UTF-8 JSON in a native Bytes message |

CES history and schemas survive mode changes. All setters update existing URefs.
`set_variables` changes minting status, ACL/package flags, operator-burn policy,
and an unlocked ACL whitelist. As upstream, a nonempty replacement list creates
a new dictionary; an empty list leaves the whitelist unchanged. Flags can be
disabled explicitly with false.

Running the installer again with the same collection name upgrades an existing
**Python** installation. It shares state and topics, applies supplied migration
options, disables the old version, and updates the account's hash/version keys.
Upgrade options are `total_token_supply`, `events_mode`, `acl_package_mode`,
`package_operator_mode`, and `operator_burn_mode`. Other installation options
do not reconfigure existing collections. The cap can decrease to the historical
mint count, but cannot become zero or increase. True migration flags enable
their modes; use `set_variables` to disable them. `migrate` requires the
installer and the Python layout marker.

Historical Rust storage migration, V1 named-key conventions, the deprecated
`contract_whitelist` argument and deprecated `approve(operator=...)` alias are
not implemented. This contract must not replace an existing Rust deployment.
The constructor replaces Rust's initialization argument list, and optional
configuration is represented by dynamic `OptionalArg`s: registered `init`,
`set_variables`, and `migrate` have no ABI parameters. The other fourteen
entrypoint schemas and all seventeen return types match the pinned reference.

The port also makes explicit corrections to the pinned development revision:
operator burning honors its flag; transfer filters receive the actual target
after authorization; NativeBytes carries valid UTF-8 JSON bytes; CES declares
`RevokedForAll`; and reverse lookup page dictionaries are allocated on demand.
These differences have regression tests.

## Validation

```sh
.venv/bin/python -m pytest -q tests/test_cep78.py
make typecheck
make build-my-nft
.venv/bin/python -m pytest -q tests/wasm/test_wasm_cep78.py
CSPR_LIVE_TESTS=1 .venv/bin/python -m pytest -q tests/live/test_cep78.py
```

Set `CSPR_DEVNET_BIN` to test a particular local launcher build. The live suite
uses an explicit 400 CSPR contract-call payment allowance; the generic testing
helper's 100 CSPR default is insufficient for complete-lookup mint and transfer.
Installer and session deployments retain their 800 CSPR allowance. These are
payment limits, not measurements of the gas consumed.

Native tests cover authority, approvals, metadata modes, caller/package identity,
filter callbacks, pagination, failed-event rollback, and Python upgrades. Both
plain and metered Wasm exercise the compiled class and codecs. The live test
checks installation, minting, transfer, typed session returns (including a URef
read), burning, upgrade, hash/custom identifiers, native Bytes events, and
stored-caller/package permissions on managed local Casper networks.

[The recorded live run](../results/cep78-devnet.json) passed three tests and
31 transactions on Casper 2.2.0 using the local `casper-devnet-launcher` checkout
at `7701eb7`. Five transactions intentionally reverted. The record includes
transaction hashes, consumed gas, deployed Wasm hashes, and the isolated HTTP
dependency override used to avoid macOS system-proxy discovery in this environment.
