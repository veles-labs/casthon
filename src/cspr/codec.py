"""Casper bytesrepr codecs shared by CPython and the frozen MicroPython SDK."""

from typing import Any
from .errors import ABIError as ABIError
from .key import Key, key_length
from .types import cl_type_of
from ._cl_types import CLType, BITS as TYPE_BITS
from ._wire_types import enum_type

TAGS = {"Bool": 0, "U8": 3, "U32": 4, "U64": 5, "U256": 7,
        "U512": 8, "Unit": 9, "String": 10, "Key": 11}
BITS = {"U8": 8, "U32": 32, "U64": 64, "U256": 256, "U512": 512}


def encode(annotation: Any, value: Any) -> bytes:
    return _encode(cl_type_of(annotation), value)


def validate(annotation: Any, value: Any) -> None:
    """Validate a typed Python value without serializing a binary payload."""
    _encode(cl_type_of(annotation), value, False)


def _encode(kind: CLType, value: Any, serialize: bool = True) -> bytes:
    tag = kind.tag
    if tag == 13:
        if value is None:
            return b"\0" if serialize else b""
        data = _encode(kind.children[0], value, serialize)
        return b"\1" + data if serialize else b""
    if tag == 11:
        expected = kind.annotation or Key
        if not isinstance(value, Key) or (expected._prefix and not bytes(value).startswith(expected._prefix)):
            raise ABIError("Expected " + expected.__name__)
        return value.to_bytes() if serialize else b""
    if tag == 14:
        if kind.annotation is bytes:
            if type(value) is not bytes:
                raise ABIError("Expected bytes")
            data = value if serialize else b""
        else:
            if type(value) is not list:
                raise ABIError("Expected list")
            data = b""
            for item in value:
                data += _encode(kind.children[0], item, serialize)
        return len(value).to_bytes(4, "little") + data if serialize else b""
    if tag == 17:
        if type(value) is not dict:
            raise ABIError("Expected dict")
        items = sorted(value.items()) if serialize else value.items()
        data = len(value).to_bytes(4, "little") if serialize else b""
        for key, item in items:
            data += _encode(kind.children[0], key, serialize) + _encode(kind.children[1], item, serialize)
        return data
    if tag in TYPE_BITS:
        enum = enum_type(kind.annotation)
        if enum is not None:
            if not isinstance(value, enum):
                raise ABIError("Expected a " + enum.__name__ + " member")
            value = int(value)
        bits = TYPE_BITS[tag]
        if type(value) is not int or value < 0 or value >= 1 << bits:
            raise ABIError("Out of range " + str(kind))
        if not serialize:
            return b""
        if tag in (7, 8):
            data = value.to_bytes(bits // 8, "little")
            size = len(data)
            while size and data[size - 1] == 0:
                size -= 1
            return bytes([size]) + data[:size]
        return value.to_bytes(bits // 8, "little")
    if tag == 0:
        if type(value) is not bool:
            raise ABIError("Expected bool")
        return bytes([int(value)]) if serialize else b""
    if tag == 10:
        if type(value) is not str:
            raise ABIError("Expected str")
        data = value.encode("utf-8")
        validate_utf8(data)
        return len(data).to_bytes(4, "little") + data if serialize else b""
    if tag == 9 and value is None:
        return b""
    raise ABIError("Unsupported value for " + str(kind))


def decode(annotation: Any, data: bytes) -> Any:
    value, offset = _read(cl_type_of(annotation), data, 0, True)
    if offset != len(data):
        raise ABIError("Trailing value bytes")
    return value


def _read(kind: CLType, data: bytes, offset: int, materialize: bool) -> Any:
    tag = kind.tag
    size = 0
    value: Any = None
    if tag == 13:
        if offset >= len(data) or data[offset] > 1:
            raise ABIError("Invalid Option tag")
        if data[offset] == 0:
            return None, offset + 1
        return _read(kind.children[0], data, offset + 1, materialize)
    if tag in (10, 14, 17):
        if offset + 4 > len(data):
            raise ABIError("Truncated collection length")
        count = int.from_bytes(data[offset:offset + 4], "little")
        offset += 4
        if tag == 10 or kind.annotation is bytes:
            end = offset + count
            if end > len(data):
                raise ABIError("Truncated bytes")
            value = data[offset:end]
            if tag == 10:
                validate_utf8(value)
                value = value.decode("utf-8")
            return value, end
        # Unit has zero-sized elements. Bound its count too, before allocating.
        if count > max(len(data), 65536):
            raise ABIError("Invalid collection length")
        result: Any = {} if tag == 17 else []
        for _ in range(count):
            item, offset = _read(kind.children[0], data, offset, materialize)
            if tag == 17:
                mapped, offset = _read(kind.children[1], data, offset, materialize)
                if materialize:
                    result[item] = mapped
            elif materialize:
                result.append(item)
        return result, offset
    if tag == 11:
        size = key_length(data[offset:])
        value = Key.from_bytes(data[offset:offset + size])
        expected = kind.annotation or Key
        if expected is not Key:
            value = expected(bytes(value))
    elif tag in TYPE_BITS:
        size = TYPE_BITS[tag] // 8
        if tag in (7, 8):
            if offset >= len(data) or data[offset] > size:
                raise ABIError("Invalid magnitude length")
            size = data[offset] + 1
            value = int.from_bytes(data[offset + 1:offset + size], "little")
        else:
            value = int.from_bytes(data[offset:offset + size], "little")
        if offset + size > len(data):
            raise ABIError("Truncated value")
        if materialize:
            enum = enum_type(kind.annotation)
            if enum is not None:
                try:
                    value = enum.from_value(value)
                except ValueError as error:
                    raise ABIError("Invalid " + enum.__name__ + " discriminant") from error
    elif tag == 0:
        size = 1
        if offset >= len(data) or data[offset] > 1:
            raise ABIError("Invalid Bool")
        value = bool(data[offset])
    elif tag != 9:
        raise ABIError("Unsupported CL type")
    if offset + size > len(data):
        raise ABIError("Truncated value")
    return value, offset + size


def validate_utf8(data: bytes) -> None:
    if not valid_utf8(data):
        raise ABIError("Invalid UTF-8")


def cl_value(annotation: Any, value: Any) -> bytes:
    data = encode(annotation, value)
    return len(data).to_bytes(4, "little") + data + cl_type(annotation)


def cl_type(annotation: Any) -> bytes:
    return cl_type_of(annotation).to_bytes()


def valid_utf8(data: bytes) -> bool:
    i = 0
    while i < len(data):
        lead = data[i]
        if lead < 128:
            i += 1
            continue
        if 194 <= lead <= 223:
            width, low, high = (2, 128, 191)
        elif 224 <= lead <= 239:
            width = 3
            low = 160 if lead == 224 else 128
            high = 159 if lead == 237 else 191
        elif 240 <= lead <= 244:
            width = 4
            low = 144 if lead == 240 else 128
            high = 143 if lead == 244 else 191
        else:
            return False
        if i + width > len(data) or not low <= data[i + 1] <= high:
            return False
        for j in range(i + 2, i + width):
            if not 128 <= data[j] <= 191:
                return False
        i += width
    return True


def valid_payload(annotation: Any, data: bytes) -> bool:
    """Validate bytesrepr without applying application enum-domain checks."""
    try:
        _, end = _read(cl_type_of(annotation), data, 0, False)
        return bool(end == len(data))
    except (ABIError, TypeError, ValueError):
        return False
