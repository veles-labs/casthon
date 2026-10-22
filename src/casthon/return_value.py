"""Shared Python serialization for explicit and ordinary contract returns."""

from typing import Any

from .bytesrepr import Reader
from .codec import cl_type, decode
from .errors import ABIError, InvalidArgument
from .key import Key
from .types import optional_inner
from .values import CLValue, SerializedCLValue
from ._wire_types import enum_type


def validate_return_payload(data: bytes) -> None:
    """Require one complete bytesrepr CLValue, including its recursive CLType."""
    if type(data) is not bytes:
        raise InvalidArgument()
    reader = Reader(data)
    try:
        reader.take(reader.u32())
        reader.cl_type()
        reader.finish()
    except ABIError:
        raise InvalidArgument()


def serialize_return(value: CLValue) -> bytes:
    if not isinstance(value, CLValue):
        raise InvalidArgument()
    data = value.to_bytes()
    validate_return_payload(data)
    return data


def _validate_value(annotation: Any, value: Any) -> None:
    inner = optional_inner(annotation)
    if inner is not None:
        if value is not None:
            _validate_value(inner, value)
    elif isinstance(annotation, type) and issubclass(annotation, Key):
        if not isinstance(value, Key):
            raise TypeError("Expected a Key value")
        prefix = annotation._prefix
        if prefix and bytes(value)[:len(prefix)] != prefix:
            raise TypeError("Key does not match the declared variant")
    else:
        enum = enum_type(annotation)
        if enum is not None:
            if type(value) is not int and not isinstance(value, enum):
                raise TypeError("Value does not match the declared enum")
            try:
                enum.from_value(value)
            except ValueError as error:
                raise ABIError("Invalid " + enum.__name__ + " discriminant") from error


def typed_value(annotation: Any, value: Any) -> CLValue:
    """Validate and snapshot a value for typed storage or an export return."""
    kind = annotation
    if isinstance(value, CLValue):
        data = serialize_return(value)
        size = int.from_bytes(data[:4], "little")
        if data[4 + size:] != cl_type(kind):
            raise TypeError("CLValue does not match the declared value type")
        # Concrete Key validation keeps its public TypeError for a wrong variant.
        if isinstance(annotation, type) and issubclass(annotation, Key):
            _validate_value(annotation, decode(Key, data[4:4 + size]))
        else:
            _validate_value(annotation, decode(kind, data[4:4 + size]))
        return SerializedCLValue(data)
    _validate_value(annotation, value)
    return CLValue(annotation, value)


def serialize_typed_return(annotation: Any, value: Any) -> bytes:
    try:
        return serialize_return(typed_value(annotation, value))
    except (TypeError, ABIError):
        raise InvalidArgument()
