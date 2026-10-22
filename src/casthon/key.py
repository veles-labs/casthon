"""Casper 6.1 Key bytesrepr, canonical formatting and Rust ordering."""

from .errors import ABIError
from typing import Any, Callable, Generic, Iterator, Mapping, ParamSpec, Sequence, TYPE_CHECKING, cast, overload

if TYPE_CHECKING:
    from typing_extensions import TypeVar
    from .values import CLValue
    from .references import URefType
    from .contracts import Contract
    from .enums import MessageTopicOperation

    _Value = TypeVar("_Value", default=Any)
else:
    from typing import TypeVar

    _Value = TypeVar("_Value")

_UNTYPED = object()
_CallArgs = ParamSpec("_CallArgs")
_CallResult = TypeVar("_CallResult")


def hex_bytes(data: bytes) -> str:
    return data.hex()


def base64(data: bytes) -> str:
    alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/"
    result = ""
    for i in range(0, len(data), 3):
        part = data[i : i + 3]
        n = part[0] << 16
        if len(part) > 1:
            n |= part[1] << 8
        if len(part) > 2:
            n |= part[2]
        result += alphabet[n >> 18] + alphabet[(n >> 12) & 63]
        result += alphabet[(n >> 6) & 63] if len(part) > 1 else "="
        result += alphabet[n & 63] if len(part) > 2 else "="
    return result


def key_length(data: bytes, offset: int = 0) -> int:
    length = valid_key_length(data, offset)
    if not length:
        raise ABIError("Invalid Key bytes")
    return length


class Key:
    _prefix = b""
    _payload_size = 0

    def __init__(self, data: bytes) -> None:
        if self._prefix:
            if (
                type(data) is bytes
                and self._payload_size
                and len(data) == self._payload_size
            ):
                data = self._prefix + data
            elif type(data) is not bytes or data[: len(self._prefix)] != self._prefix:
                raise ABIError("Wrong Key variant")
        if type(data) is not bytes or not data or valid_key_length(data) != len(data):
            raise ABIError("Expected exact Key bytes")
        if data[0] in (10, 11, 13, 14):
            data = data[:1] + bytes(32)
        elif data[0] == 21:
            data = data[:2] + bytes(31)
        self._data = data

    @staticmethod
    def account(address: bytes) -> "AccountHash":
        if len(address) != 32:
            raise ABIError("Expected account hash")
        return AccountHash(address)

    @staticmethod
    def hash(address: bytes) -> "Hash":
        if len(address) != 32:
            raise ABIError("Expected hash")
        return Hash(address)

    @staticmethod
    def from_bytes(data: bytes) -> "Key":
        """Decode a Key into the subclass identified by its wire variant."""
        if type(data) is not bytes or not data or data[0] >= len(_KEY_TYPES):
            raise ABIError("Invalid Key")
        if valid_key_length(data) != len(data):
            raise ABIError("Expected exact Key bytes")
        cls = _KEY_TYPES[data[0]]
        if data[0] == 17:
            if len(data) < 2 or data[1] > 2:
                raise ABIError("Invalid entity Key")
            cls = _ENTITY_TYPES[data[1]]
        return cls(data)

    def to_bytes(self) -> bytes:
        return self._data

    def __bytes__(self) -> bytes:
        return self._data

    def __iter__(self) -> Iterator[int]:
        # MicroPython's bytes constructor uses the iterable protocol.
        return iter(self._data)

    def __hash__(self) -> int:
        return hash(self._data)

    def __eq__(self, other: object) -> bool:
        return isinstance(other, Key) and self._data == other._data

    def order_bytes(self) -> bytes:
        data = self._data
        offset, width = 0, 0
        if data[0] == 5:
            offset, width = 1, 8
        elif (data[0] == 15 and data[1] == 4) or data[0] == 22:
            offset, width = 34, 8
        elif data[0] == 19 and data[66] == 1:
            offset, width = 67, 4
        if width:
            return (
                data[:offset]
                + bytes(reversed(data[offset : offset + width]))
                + data[offset + width :]
            )
        return data

    def __lt__(self, other: "Key") -> bool:
        return self.order_bytes() < other.order_bytes()

    def __le__(self, other: "Key") -> bool:
        return self.order_bytes() <= other.order_bytes()

    def __gt__(self, other: "Key") -> bool:
        # MicroPython sequence comparisons use > even when sorting tuples
        # with <. It does not synthesize this from the reflected __lt__.
        return self.order_bytes() > other.order_bytes()

    def __ge__(self, other: "Key") -> bool:
        return self.order_bytes() >= other.order_bytes()

    def __str__(self) -> str:
        data, tag = self._data, self._data[0]
        prefixes = (
            "account-hash-",
            "hash-",
            "uref-",
            "transfer-",
            "deploy-",
            "era-",
            "balance-",
            "bid-",
            "withdraw-",
            "dictionary-",
            "system-entity-registry-",
            "era-summary-",
            "unbond-",
            "chainspec-registry-",
            "checksum-registry-",
            "bid-addr-",
            "package-",
        )
        kinds = ("system", "account", "contract")
        if tag == 2:
            return "uref-" + hex_bytes(data[1:33]) + "-00" + str(data[33])
        if tag == 5:
            return "era-" + str(int.from_bytes(data[1:], "little"))
        if tag <= 16:
            return prefixes[tag] + hex_bytes(data[1:])
        entity = (
            "entity-" + kinds[data[1]] + "-" + hex_bytes(data[2:34])
            if tag in (17, 19, 20, 24)
            else ""
        )
        if tag == 17:
            return entity
        if tag == 18:
            return "byte-code-" + (
                "empty-" + "0" * 64
                if data[1] == 0
                else ("v1-wasm-" if data[1] == 1 else "v2-wasm-") + hex_bytes(data[2:])
            )
        if tag == 19:
            return (
                ("message-topic-" if data[66] == 0 else "message-")
                + entity
                + "-"
                + hex_bytes(data[34:66])
                + (
                    ""
                    if data[66] == 0
                    else "-" + hex(int.from_bytes(data[67:], "little"))[2:]
                )
            )
        if tag == 20:
            return "named-key-" + entity + "-" + hex_bytes(data[34:])
        if tag == 21:
            return (
                "block-time-",
                "block-message-count-",
                "block-protocol-version-",
                "block-addressable-entity-",
            )[data[1]] + "0" * 62
        if tag == 22:
            return "balance-hold-" + hex_bytes(data[1:])
        if tag == 23:
            return (
                "entry-point-v1-entity-"
                + kinds[data[2]]
                + "-"
                + hex_bytes(data[3:35])
                + "-"
                + hex_bytes(data[35:])
            )
        return "state-" + entity

    formatted = __str__


class AccountHash(Key):
    _prefix = b"\x00"
    _payload_size = 32


class Hash(Key):
    """Legacy Key::Hash; the wire format does not distinguish contract/package roles."""

    _prefix = b"\x01"
    _payload_size = 32


class ContractHash(Hash):
    """A legacy Hash whose contract role is known explicitly."""

    if TYPE_CHECKING:
        def call(self, function: Callable[_CallArgs, _CallResult], /,
                 *args: _CallArgs.args, **kwargs: _CallArgs.kwargs) -> _CallResult:
            from .contract_call import call_function
            return cast(_CallResult, call_function(self, function, args, kwargs))
    else:
        # MicroPython has no positional-only syntax. Consume self and function
        # from *args so entrypoint arguments named "self" or "function" work.
        def call(*args: Any, **kwargs: Any) -> Any:
            """Call a deployed entrypoint using an exported function's wire signature."""
            from .contract_call import call_function
            if len(args) < 2:
                raise TypeError("Expected an exported function")
            return call_function(args[0], args[1], args[2:], kwargs)


class ContractPackageHash(Hash):
    """A legacy Hash whose contract-package role is known explicitly."""

    def add_contract_version(
        self, contract: "Contract", *,
        message_topics: "Mapping[str, MessageTopicOperation] | Sequence[str]" = (),
    ) -> tuple[ContractHash, int]:
        """Add an initialized contract's entrypoints and state to this package."""
        from .contract_api import storage
        from .contracts import Contract

        if not isinstance(contract, Contract):
            raise TypeError("Expected an initialized Contract instance")
        return storage.add_contract_version(
            self, contract.entry_points(), contract.named_keys, message_topics)

    def disable_contract_version(self, contract: ContractHash) -> None:
        """Disable a version belonging to this package."""
        from .contract_api import storage
        storage.disable_contract_version(self, contract)

    def enable_contract_version(self, contract: ContractHash) -> None:
        """Re-enable a version belonging to this package."""
        from .contract_api import storage
        storage.enable_contract_version(self, contract)


class URef(Key, Generic[_Value]):
    _prefix = b"\x02"

    @classmethod
    def __class_getitem__(cls, annotation: Any) -> Any:
        return cls.of(annotation)

    @classmethod
    def of(cls, annotation: type[_Value]) -> "URefType[_Value]":
        """Build the value schema used by URef[T] and the frozen SDK."""
        from .references import URefType
        return URefType(annotation)

    def __init__(self, address: bytes, access_rights: int = 7) -> None:
        if type(address) is bytes and len(address) == 32:
            if not 0 <= access_rights <= 7:
                raise ABIError("Invalid URef access rights")
            address = b"\x02" + address + bytes([access_rights])
        Key.__init__(self, address)
        self._value_type: Any = _UNTYPED

    @property
    def address(self) -> bytes:
        return self._data[1:33]

    @property
    def access_rights(self) -> int:
        return self._data[33]

    @overload
    def read(self) -> _Value: ...

    @overload
    def read(self, annotation: Any) -> Any: ...

    def read(self, annotation: Any = _UNTYPED) -> Any:
        """Typed reads are strict; an explicit annotation preserves low-level read semantics."""
        from .contract_api import storage
        if annotation is _UNTYPED:
            if self._value_type is _UNTYPED:
                raise TypeError("An untyped URef requires an explicit read type")
            return storage.read_or_revert(self, self._value_type)
        return storage.read(self, annotation)

    def _cl_value(self, value: Any) -> "CLValue":
        from .values import CLValue
        if self._value_type is _UNTYPED:
            if not isinstance(value, CLValue):
                raise TypeError("An untyped URef requires an explicit CLValue")
            return value
        from .return_value import typed_value
        return typed_value(self._value_type, value)

    def write(self, value: "_Value | CLValue") -> None:
        """Replace the referenced value without changing any named-key binding."""
        from .contract_api import storage
        storage.write(self, self._cl_value(value))

    def add(self, value: "_Value | CLValue") -> None:
        """Apply Casper's add operation to the referenced value."""
        from .contract_api import storage
        if self._value_type is not _UNTYPED:
            from .types import wire_type
            if wire_type(self._value_type) not in ("U64", "U256", "U512"):
                raise TypeError("The declared value type does not support Casper add")
        storage.add(self, self._cl_value(value))


class TransferHash(Key):
    _prefix = b"\x03"
    _payload_size = 32


class DeployInfo(Key):
    _prefix = b"\x04"
    _payload_size = 32


class EraInfo(Key):
    _prefix = b"\x05"
    _payload_size = 8


class Balance(Key):
    _prefix = b"\x06"
    _payload_size = 32


class Bid(Key):
    _prefix = b"\x07"
    _payload_size = 32


class Withdraw(Key):
    _prefix = b"\x08"
    _payload_size = 32


class DictionaryAddress(Key):
    _prefix = b"\x09"
    _payload_size = 32


class SystemEntityRegistry(Key):
    _prefix = b"\x0a"
    _payload_size = 32


class EraSummary(Key):
    _prefix = b"\x0b"
    _payload_size = 32


class Unbond(Key):
    _prefix = b"\x0c"
    _payload_size = 32


class ChainspecRegistry(Key):
    _prefix = b"\x0d"
    _payload_size = 32


class ChecksumRegistry(Key):
    _prefix = b"\x0e"
    _payload_size = 32


class BidAddress(Key):
    _prefix = b"\x0f"


class PackageHash(Key):
    _prefix = b"\x10"
    _payload_size = 32


class AddressableEntity(Key):
    _prefix = b"\x11"


class SystemEntity(AddressableEntity):
    _prefix = b"\x11\x00"
    _payload_size = 32


class AccountEntity(AddressableEntity):
    _prefix = b"\x11\x01"
    _payload_size = 32


class ContractEntity(AddressableEntity):
    _prefix = b"\x11\x02"
    _payload_size = 32


class ByteCode(Key):
    _prefix = b"\x12"


class Message(Key):
    _prefix = b"\x13"


class NamedKeyAddress(Key):
    _prefix = b"\x14"


class BlockGlobal(Key):
    _prefix = b"\x15"


class BalanceHold(Key):
    _prefix = b"\x16"


class EntryPointAddress(Key):
    _prefix = b"\x17"


class State(Key):
    _prefix = b"\x18"


_ENTITY_TYPES = (SystemEntity, AccountEntity, ContractEntity)
_KEY_TYPES = (
    AccountHash,
    Hash,
    URef,
    TransferHash,
    DeployInfo,
    EraInfo,
    Balance,
    Bid,
    Withdraw,
    DictionaryAddress,
    SystemEntityRegistry,
    EraSummary,
    Unbond,
    ChainspecRegistry,
    ChecksumRegistry,
    BidAddress,
    PackageHash,
    AddressableEntity,
    ByteCode,
    Message,
    NamedKeyAddress,
    BlockGlobal,
    BalanceHold,
    EntryPointAddress,
    State,
)


def valid_key_length(data: bytes, offset: int = 0) -> int:
    remaining = len(data) - offset
    if offset < 0 or remaining <= 0:
        return 0
    tag = data[offset]
    length = 33
    if tag > 24:
        return 0
    if tag == 2:
        length = 34
    elif tag == 5:
        length = 9
    elif tag in (15, 17, 18, 19, 20, 21, 22, 23, 24):
        if remaining < 2:
            return 0
        sub = data[offset + 1]
        if tag == 15:
            if sub > 9:
                return 0
            length = 34 if sub in (0, 1, 9) else 42 if sub == 4 else 66
        elif tag in (17, 24):
            if sub > 2:
                return 0
            length = 34
        elif tag == 18:
            if sub > 2:
                return 0
            length = 2 if sub == 0 else 34
        elif tag == 19:
            if sub > 2 or remaining < 67 or data[offset + 66] > 1:
                return 0
            length = 67 if data[offset + 66] == 0 else 71
        elif tag == 20:
            if sub > 2:
                return 0
            length = 66
        elif tag == 21:
            if sub > 3:
                return 0
        elif tag == 22:
            if sub > 1:
                return 0
            length = 42
        elif tag == 23:
            if sub != 0 or remaining < 3 or data[offset + 2] > 2:
                return 0
            length = 67
    if remaining < length or (tag == 2 and data[offset + 33] > 7):
        return 0
    return length
