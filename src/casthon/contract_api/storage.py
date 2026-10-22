"""URef, dictionary and package operations from contract_api/storage.rs."""

from typing import Any, Iterable, Mapping, Sequence, cast
from .._ffi import call as _call
from ..codec import ABIError, encode, validate_utf8
from ..errors import InvalidArgument, Read, ValueNotFound, DictionaryItemKeyExceedsLength
from ..entry_points import EntryPoint, serialize_entry_points
from ..key import Key, URef, ContractHash, ContractPackageHash, ContractEntity, PackageHash, DictionaryAddress
from ..bytesrepr import Reader
from ..enums import MessageTopicOperation
from ..values import CLValue
from . import runtime


def read_from_key(key: Key, annotation: Any) -> Any:
    try:
        data = _call('read_value', bytes(key))
    except ValueNotFound:
        return None
    return None if data is None else runtime._decode(annotation, data)


def read(uref: URef, annotation: Any) -> Any:
    _require_uref(uref)
    return read_from_key(uref, annotation)


def read_or_revert(uref: URef, annotation: Any) -> Any:
    _require_uref(uref)
    data = _call('read_value', bytes(uref))
    if data is None:
        raise ValueNotFound()
    try:
        return runtime._decode(annotation, data)
    except ABIError:
        raise Read()


def new_uref(value: CLValue) -> URef:
    return URef(_call('new_uref', value.to_bytes()))


def write(uref: URef, value: CLValue) -> None:
    _require_uref(uref)
    _call('write', bytes(uref), value.to_bytes())


def add(uref: URef, value: CLValue) -> None:
    _require_uref(uref)
    _call('add', bytes(uref), value.to_bytes())


def _require_uref(uref: URef) -> None:
    if not isinstance(uref, URef):
        raise TypeError("Expected URef")


def new_dictionary(name: str) -> URef:
    if not name or runtime.has_key(name):
        raise InvalidArgument()
    seed = new_dictionary_seed()
    runtime.put_key(name, seed)
    return seed


def new_dictionary_seed() -> URef:
    """Allocate an empty dictionary seed without adding a named-key binding."""
    return URef(_call('new_dictionary'))


def _dictionary_item_key(item: str) -> None:
    if not isinstance(item, str):
        raise TypeError("Dictionary item keys must be strings")
    encoded = item.encode("utf-8")
    validate_utf8(encoded)
    if len(encoded) > 64:
        raise DictionaryItemKeyExceedsLength()


def dictionary_get(seed: URef, item: str, annotation: Any, *, default: Any = None) -> Any:
    _require_uref(seed)
    _dictionary_item_key(item)
    try:
        data = _call('dictionary_get', bytes(seed), item)
    except ValueNotFound:
        return default
    return default if data is None else runtime._decode(annotation, data)


def dictionary_put(seed: URef, item: str, value: CLValue) -> None:
    _require_uref(seed)
    _dictionary_item_key(item)
    _call('dictionary_put', bytes(seed), item, value.to_bytes())


def create_contract_package_at_hash(is_locked: bool = False) -> tuple[ContractPackageHash, URef]:
    package, access = _call('create_contract_package_at_hash', is_locked)
    return ContractPackageHash(package), URef(access)


def add_contract_version(
    package: Key,
    entry_points: Sequence[EntryPoint],
    named_keys: Mapping[str, Key],
    message_topics: Mapping[str, MessageTopicOperation] | Sequence[str] = (),
) -> tuple[ContractHash, int]:
    key, version = _call('add_contract_version',
        bytes(package), serialize_entry_points(entry_points), _named_keys(named_keys), _message_topics(message_topics)
    )
    return ContractHash(key), version


def _named_keys(named_keys: Mapping[str, Key]) -> bytes:
    keys = encode("U32", len(named_keys))
    for name, key in sorted(named_keys.items()):
        keys += encode("String", name) + bytes(key)
    return keys


def _message_topics(topics: Mapping[str, MessageTopicOperation] | Sequence[str]) -> bytes:
    if hasattr(topics, "items"):
        items = list(cast(Mapping[str, MessageTopicOperation], topics).items())
    else:
        items = [(name, MessageTopicOperation.ADD) for name in set(topics)]
    data = encode("U32", len(items))
    for name, operation in sorted(items):
        operation = MessageTopicOperation.from_value(int(operation))
        data += encode("String", name) + bytes([int(operation)])
    return data


def disable_contract_version(package: Key, contract: Key) -> None:
    _call('disable_contract_version', bytes(package), bytes(contract))


def enable_contract_version(package: Key, contract: Key) -> None:
    _call('enable_contract_version', bytes(package), bytes(contract))


def add_contract_version_legacy(package: Key, entry_points: Sequence[EntryPoint],
                                named_keys: Mapping[str, Key]) -> tuple[ContractHash, int]:
    key, version = _call('add_contract_version_legacy', bytes(package),
        serialize_entry_points(entry_points, legacy=True), _named_keys(named_keys))
    return ContractHash(key), version


def add_package_version(package: PackageHash, entry_points: Sequence[EntryPoint],
                        named_keys: Mapping[str, Key],
                        message_topics: Mapping[str, MessageTopicOperation] | Sequence[str] = ()) -> tuple[ContractHash | ContractEntity, int]:
    key, version = _call('add_package_version', bytes(package), serialize_entry_points(entry_points),
        _named_keys(named_keys), _message_topics(message_topics))
    result = Key.from_bytes(key)
    if isinstance(result, ContractEntity):
        return result, version
    return ContractHash(key), version


def _uref_set(urefs: Iterable[URef]) -> bytes:
    items = sorted(set(urefs))
    if any(not isinstance(uref, URef) for uref in items):
        raise TypeError("User group members must be URef objects")
    return encode("U32", len(items)) + b"".join(bytes(uref)[1:] for uref in items)


def _uref_list(data: bytes) -> list[URef]:
    reader = Reader(data)
    result = [URef(b"\2" + reader.take(33)) for _ in range(reader.count(33))]
    reader.finish()
    return result


def create_contract_user_group(package: Key, label: str, num_new_urefs: int,
                               existing_urefs: Iterable[URef] = ()) -> list[URef]:
    encode("U8", num_new_urefs)
    return _uref_list(_call('create_contract_user_group', bytes(package), label, num_new_urefs, _uref_set(existing_urefs)))


def provision_contract_user_group_uref(package: Key, label: str) -> URef:
    return URef(b"\2" + _call('provision_contract_user_group_uref', bytes(package), label))


def remove_contract_user_group_urefs(package: Key, label: str, urefs: Iterable[URef]) -> None:
    _call('remove_contract_user_group_urefs', bytes(package), label, _uref_set(urefs))


def remove_contract_user_group(package: Key, label: str) -> None:
    _call('remove_contract_user_group', bytes(package), label)


def dictionary_read(dictionary_key: DictionaryAddress, annotation: Any) -> Any:
    try:
        data = _call('dictionary_read', bytes(dictionary_key))
    except ValueNotFound:
        return None
    return None if data is None else runtime._decode(annotation, data)
