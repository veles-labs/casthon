"""Explicit Casper CLValues used for storage and runtime arguments."""

from typing import Any
from .codec import ABIError, cl_type, _encode
from .key import Key
from .types import cl_type_of


class CLValue:
    def __init__(self, annotation: Any, value: Any) -> None:
        self.value = value
        self._descriptor = cl_type_of(annotation)
        self._payload = _encode(self._descriptor, value)

    @property
    def kind(self) -> str:
        return str(self._descriptor)

    def to_bytes(self) -> bytes:
        return (
            len(self._payload).to_bytes(4, "little")
            + self._payload
            + cl_type(self._descriptor)
        )


class CLU8(CLValue):
    def __init__(self, value: int) -> None:
        CLValue.__init__(self, "U8", value)


class CLU32(CLValue):
    def __init__(self, value: int) -> None:
        CLValue.__init__(self, "U32", value)


class CLU64(CLValue):
    def __init__(self, value: int) -> None:
        CLValue.__init__(self, "U64", value)


class CLU256(CLValue):
    def __init__(self, value: int) -> None:
        CLValue.__init__(self, "U256", value)


class CLU512(CLValue):
    def __init__(self, value: int) -> None:
        CLValue.__init__(self, "U512", value)


class CLString(CLValue):
    def __init__(self, value: str) -> None:
        CLValue.__init__(self, str, value)


class CLBool(CLValue):
    def __init__(self, value: bool) -> None:
        CLValue.__init__(self, bool, value)


class CLKey(CLValue):
    def __init__(self, value: Key) -> None:
        CLValue.__init__(self, Key, value)


class CLKeyList(CLValue):
    def __init__(self, value: list[Key]) -> None:
        CLValue.__init__(self, "List<Key>", value)


class CLSecurityMap(CLValue):
    def __init__(self, value: dict[Key, int]) -> None:
        CLValue.__init__(self, "Map<Key,U8>", value)


class CLBytes(CLValue):
    def __init__(self, value: bytes) -> None:
        CLValue.__init__(self, bytes, value)


class CLUnit(CLValue):
    def __init__(self) -> None:
        CLValue.__init__(self, None, None)


class SerializedCLValue(CLValue):
    """A complete bytesrepr CLValue, for CLTypes outside the authoring subset."""

    def __init__(self, data: bytes) -> None:
        if (
            type(data) is not bytes
            or len(data) < 5
            or int.from_bytes(data[:4], "little") >= len(data) - 4
        ):
            raise ABIError("Expected serialized CLValue")
        self._serialized = data

    def to_bytes(self) -> bytes:
        return self._serialized

    @property
    def payload(self) -> bytes:
        size = int.from_bytes(self._serialized[:4], "little")
        return self._serialized[4:4 + size]

    @property
    def cl_type_bytes(self) -> bytes:
        size = int.from_bytes(self._serialized[:4], "little")
        return self._serialized[4 + size:]
