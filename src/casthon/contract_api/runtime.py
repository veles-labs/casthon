"""Arguments, named keys, calls and returns; mirrors contract_api/runtime.rs."""

from __future__ import annotations

from typing import Any, Iterator, Mapping, NoReturn, TypeVar, TYPE_CHECKING, cast, overload
from .._ffi import call as _call
from ..errors import Ret, Revert, MissingArgument, MissingKey
from ..return_value import serialize_return
from ..codec import decode, encode, valid_payload
from ..key import AccountHash, Key, URef, key_length
from ..enums import Phase, MessageTopicOperation
from ..caller import CallerInfo, AccountCaller, CallStackElement, decode_caller_information, decode_legacy_call_stack
from ..bytesrepr import Reader
from ..messages import MessagePayload
from ..errors import ABIError
from ..values import CLValue
from ..arguments import MISSING, optional_arg_inner

_T = TypeVar("_T")
_K = TypeVar("_K")
_V = TypeVar("_V")
_Key = TypeVar("_Key", bound=Key)

if TYPE_CHECKING:
    from ..references import (
        NamedKeyReference, URefReference, URefType,
        DictionaryReference, DictionaryType, Dictionary,
    )


def _decode(annotation: Any, data: bytes) -> Any:
    return decode(annotation, data)


def get_named_arg(name: str, annotation: Any) -> Any:
    inner = optional_arg_inner(annotation)
    if inner is not None:
        try:
            data = _call('get_named_arg', name)
        except MissingArgument:
            return MISSING
        return _decode(inner, data)
    return _decode(annotation, _call('get_named_arg', name))


def try_get_named_arg(name: str, annotation: Any) -> Any:
    if optional_arg_inner(annotation) is not None:
        raise TypeError("Use get_named_arg with OptionalArg to preserve missing and malformed inputs")
    # Rust returns None for both a missing argument and a deserialization error.
    try:
        data = _call('get_named_arg', name)
    except MissingArgument:
        return None
    if data is None or not valid_payload(annotation, data):
        return None
    try:
        return _decode(annotation, data)
    except ABIError:
        return None


def ret(value: CLValue) -> NoReturn:
    """Snapshot the return value and unwind to the outer export dispatcher."""
    payload = serialize_return(value)
    raise Ret(payload)


def revert(error: int) -> NoReturn:
    """Raise a revert signal; an uncaught signal reverts at the export boundary."""
    raise Revert(error)


def get_key(name: str) -> Key | None:
    try:
        data = _call('get_key', name)
    except MissingKey:
        return None
    return None if data is None else Key.from_bytes(data)


def has_key(name: str) -> bool:
    return cast(bool, _call('has_key', name))


def put_key(name: str, key: Key) -> None:
    if not isinstance(key, Key):
        raise TypeError("Expected Key")
    _call('put_key', name, bytes(key))


def remove_key(name: str) -> None:
    _call('remove_key', name)


def list_named_keys() -> dict[str, Key]:
    """Materialize a dictionary snapshot; named_keys iterators decode lazily."""
    return dict(named_keys.items())


class _NamedKeyIterator:
    def __init__(self, mode: int) -> None:
        self._reader = Reader(_call('list_named_keys'))
        # A string length plus the shortest Key variant occupy six bytes.
        self._remaining = self._reader.count(6)
        self._mode = mode

    def __iter__(self) -> "_NamedKeyIterator":
        return self

    def __next__(self) -> Any:
        reader = self._reader
        if not self._remaining:
            reader.finish()
            raise StopIteration
        start = reader.offset
        reader.take(reader.u32())
        name = decode("String", reader.data[start:reader.offset])
        size = key_length(reader.data, reader.offset)
        self._remaining -= 1
        if self._mode == 0:
            # Names-only iteration validates the Key without constructing it.
            reader.offset += size
            return name
        key = Key.from_bytes(reader.take(size))
        return (name, key) if self._mode == 1 else key


class NamedKeys:
    """Named-key bindings in the current context, with snapshot iterators."""

    def __getitem__(self, name: str) -> Key:
        key = get_key(name)
        if key is None:
            raise KeyError(name)
        return key

    def __setitem__(self, name: str, key: Key) -> None:
        put_key(name, key)

    def __delitem__(self, name: str) -> None:
        if not has_key(name):
            raise KeyError(name)
        remove_key(name)

    def __contains__(self, name: str) -> bool:
        return has_key(name)

    def __len__(self) -> int:
        return Reader(_call('list_named_keys')).count(6)

    def __iter__(self) -> Iterator[str]:
        return self.keys()

    @overload
    def get(self, name: str) -> Key | None: ...

    @overload
    def get(self, name: str, default: _T) -> Key | _T: ...

    def get(self, name: str, default: _T | None = None) -> Key | _T | None:
        key = get_key(name)
        return default if key is None else key

    def keys(self) -> Iterator[str]:
        """Load one serialized snapshot and decode names on demand."""
        return _NamedKeyIterator(0)

    def items(self) -> Iterator[tuple[str, Key]]:
        """Load one serialized snapshot and decode pairs on demand."""
        return _NamedKeyIterator(1)

    def values(self) -> Iterator[Key]:
        """Load one serialized snapshot and decode keys on demand."""
        return _NamedKeyIterator(2)

    @overload
    def reference(self, name: str, annotation: type[URef[_V]] | "URefType[_V]") -> "URefReference[_V]": ...

    @overload
    def reference(self, name: str, annotation: "Dictionary[_K, _V] | type[Dictionary[_K, _V]] | DictionaryType[_K, _V]") -> "DictionaryReference[_K, _V]": ...

    @overload
    def reference(self, name: str, annotation: type[_Key]) -> "NamedKeyReference[_Key]": ...

    @overload
    def reference(self, name: str | None = None, *, key: Any = None) -> Any: ...

    def reference(self, name: str | None = None, annotation: Any = ..., *, key: Any = None) -> Any:
        """Declare a typed lazy binding without reading or allocating storage."""
        if annotation is ...:
            from ..contracts import StateConfiguration
            return StateConfiguration(name, key)
        if name is None or key is not None:
            raise TypeError("Explicit references require a name and a complete schema")
        from ..references import reference
        return reference(self, name, annotation)


named_keys = NamedKeys()


def get_caller() -> AccountHash:
    """The account initiating the transaction, matching Rust get_caller()."""
    return AccountHash(_call('get_caller'))


def get_protocol_version() -> tuple[int, int, int]:
    return cast(tuple[int, int, int], _call('get_protocol_version'))


def blake2b(data: bytes) -> bytes:
    return cast(bytes, _call('blake2b', data))


def call_contract(
    contract: Key, entry: str, args: Mapping[str, CLValue], return_type: Any = None
) -> Any:
    return _decode(return_type, _call('call_contract', bytes(contract), entry, _runtime_args(args)))


def _runtime_args(args: Mapping[str, CLValue]) -> bytes:
    data = encode("U32", len(args))
    for name, value in args.items():
        if not isinstance(value, CLValue):
            raise TypeError("Runtime arguments must be CLValue objects")
        data += encode("String", name) + value.to_bytes()
    return data


def emit_message(topic: str, payload: MessagePayload | bytes) -> None:
    """Emit a payload; raw bytes include the serialized MessagePayload tag."""
    if not topic:
        raise ValueError("Message topic must not be empty")
    if not isinstance(payload, (MessagePayload, bytes)):
        raise TypeError("Expected MessagePayload or serialized bytes")
    _call('emit_message', topic, payload.to_bytes() if isinstance(payload, MessagePayload) else payload)


def manage_message_topic(topic: str, operation: MessageTopicOperation = MessageTopicOperation.ADD) -> None:
    if not topic:
        raise ValueError("Message topic must not be empty")
    operation = MessageTopicOperation.from_value(int(operation))
    _call('manage_message_topic', topic, bytes([int(operation)]))


def list_authorization_keys() -> set[AccountHash]:
    reader = Reader(_call('list_authorization_keys'))
    result = {AccountHash(reader.take(32)) for _ in range(reader.count(32))}
    reader.finish()
    return result


def is_valid_uref(uref: URef) -> bool:
    return cast(bool, _call('is_valid_uref', bytes(uref)))


def get_blocktime() -> int:
    return cast(int, decode("U64", _call('get_blocktime')))


def get_phase() -> Phase:
    return Phase.from_value(_call('get_phase'))


def get_block_height() -> int:
    return cast(int, decode("U64", _call('get_block_info', 1)))


def get_parent_block_hash() -> bytes:
    return cast(bytes, _call('get_block_info', 2))


def get_state_hash() -> bytes:
    return cast(bytes, _call('get_block_info', 3))


def get_addressable_entity() -> bool:
    return cast(bool, decode("Bool", _call('get_block_info', 5)))


def random_bytes() -> bytes:
    return cast(bytes, _call('random_bytes'))


def get_call_stack() -> list[CallerInfo]:
    return decode_caller_information(_call('load_caller_information', 2))


def get_immediate_caller() -> CallerInfo:
    values = decode_caller_information(_call('load_caller_information', 1))
    if len(values) != 1:
        raise ValueError("Expected one immediate caller")
    return values[0]


def get_call_initiator() -> AccountHash:
    values = decode_caller_information(_call('load_caller_information', 0))
    if len(values) != 1 or not isinstance(values[0], AccountCaller):
        raise ValueError("Expected account initiator")
    account = values[0].account_hash
    if account is None:
        raise ValueError("Missing account initiator")
    return account


def get_legacy_call_stack() -> list[CallStackElement]:
    """Decode the deprecated casper_load_call_stack representation."""
    return decode_legacy_call_stack(_call('load_call_stack'))


def _optional_u32(value: int | None) -> bytes:
    return b"\0" if value is None else b"\1" + encode("U32", value)


def call_versioned_contract(package: Key, version: int | None, entry: str,
                            args: Mapping[str, CLValue], return_type: Any = None) -> Any:
    return _decode(return_type, _call('call_versioned_contract', bytes(package), _optional_u32(version),
                                                              entry, _runtime_args(args)))


def call_package_version(package: Key, major_version: int | None, version: int | None,
                         entry: str, args: Mapping[str, CLValue], return_type: Any = None) -> Any:
    return _decode(return_type, _call('call_package_version', bytes(package), _optional_u32(major_version),
                                                            _optional_u32(version), entry, _runtime_args(args)))
