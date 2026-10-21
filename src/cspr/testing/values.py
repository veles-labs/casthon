"""Test/client-side CLValue inspection, using the production bytesrepr codecs."""

from typing import Any
from ..bytesrepr import Reader
from ..codec import TAGS, cl_type, decode, encode
from ..key import AccountHash, Hash, Key, URef, DictionaryAddress, PackageHash, ContractEntity, AccountEntity
from ..return_value import validate_return_payload
from ..values import CLValue, SerializedCLValue
from ..types import cl_type_of
from .._cl_types import CLType


def read_type(reader: Reader) -> CLType:
    tag = reader.u8()
    if tag in (13, 14):
        child = read_type(reader)
        return CLType(tag, (child,), bytes if tag == 14 and child.tag == 3 else None)
    if tag == 17:
        return CLType(tag, (read_type(reader), read_type(reader)))
    return CLType(tag)


def read_kind(reader: Reader) -> str:
    return str(read_type(reader))


def inspect_value(data: bytes) -> tuple[str, Any]:
    validate_return_payload(data)
    reader = Reader(data)
    payload = reader.take(reader.u32())
    kind = read_type(reader)
    reader.finish()
    return str(kind), decode(kind, payload)


def kind_json(annotation: Any) -> Any:
    kind = cl_type_of(annotation)
    if kind.tag in (13, 14):
        return {"Option" if kind.tag == 13 else "List": kind_json(kind.children[0])}
    if kind.tag == 17:
        return {"Map": {"key": kind_json(kind.children[0]), "value": kind_json(kind.children[1])}}
    return str(kind)


def json_kind(value: Any) -> CLType:
    if isinstance(value, str):
        return cl_type_of(value)
    if isinstance(value, dict):
        if "Option" in value or "List" in value:
            tag = 13 if "Option" in value else 14
            child = json_kind(value["Option" if tag == 13 else "List"])
            return CLType(tag, (child,), bytes if tag == 14 and child.tag == 3 else None)
        if "Map" in value:
            return CLType(17, (json_kind(value["Map"]["key"]), json_kind(value["Map"]["value"])))
    raise NotImplementedError(f"CLType {value!r} is outside the Python codec subset")


def runtime_args(args: dict[str, CLValue]) -> list[Any]:
    items = []
    for name, value in args.items():
        if not isinstance(value, CLValue):
            raise TypeError("Runtime arguments must be CLValue objects")
        data = value.to_bytes()
        validate_return_payload(data)
        reader = Reader(data)
        payload = reader.take(reader.u32())
        kind = _read_type_json(reader)
        reader.finish()
        items.append([name, {"cl_type": kind, "bytes": payload.hex(), "parsed": None}])
    return items


def _read_type_json(reader: Reader) -> Any:
    tag = reader.u8()
    scalars = {0: "Bool", 1: "I32", 2: "I64", 3: "U8", 4: "U32", 5: "U64", 6: "U128",
               7: "U256", 8: "U512", 9: "Unit", 10: "String", 11: "Key", 12: "URef", 21: "Any", 22: "PublicKey"}
    if tag in scalars:
        return scalars[tag]
    if tag in (13, 14):
        return {"Option" if tag == 13 else "List": _read_type_json(reader)}
    if tag == 15:
        return {"ByteArray": reader.u32()}
    if tag in (16, 17):
        names = ("ok", "err") if tag == 16 else ("key", "value")
        return {"Result" if tag == 16 else "Map": {name: _read_type_json(reader) for name in names}}
    if tag in (18, 19, 20):
        return {"Tuple" + str(tag - 17): [_read_type_json(reader) for _ in range(tag - 17)]}
    raise ValueError("Unknown CLType")


def from_json(value: dict[str, Any]) -> SerializedCLValue:
    kind = json_kind(value["cl_type"])
    payload = bytes.fromhex(value["bytes"])
    data = encode("U32", len(payload)) + payload + cl_type(kind)
    inspect_value(data)
    return SerializedCLValue(data)


def parse_key(value: str) -> Key:
    if value.startswith("uref-"):
        address, rights = value[5:].split("-")
        return URef(bytes.fromhex(address), int(rights))
    for prefix, cls in (("account-hash-", AccountHash), ("hash-", Hash),
                        ("dictionary-", DictionaryAddress), ("package-", PackageHash),
                        ("entity-contract-", ContractEntity), ("entity-account-", AccountEntity)):
        if value.startswith(prefix):
            return cls(bytes.fromhex(value[len(prefix):]))
    raise NotImplementedError(f"Unsupported formatted Key: {value}")
