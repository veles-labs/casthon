"""Bounded readers for structured host results with embedded CLType data."""

from .errors import ABIError
from .values import SerializedCLValue


class Reader:
    def __init__(self, data: bytes) -> None:
        self.data, self.offset = data, 0

    def take(self, size: int) -> bytes:
        if size < 0 or size > len(self.data) - self.offset:
            raise ABIError("Truncated host result")
        start = self.offset
        self.offset += size
        return self.data[start:self.offset]

    def u8(self) -> int:
        return self.take(1)[0]

    def u32(self) -> int:
        return int.from_bytes(self.take(4), "little")

    def count(self, minimum_size: int) -> int:
        value = self.u32()
        if value > (len(self.data) - self.offset) // minimum_size:
            raise ABIError("Invalid host collection length")
        return value

    def cl_type(self, depth: int = 0) -> None:
        if depth > 32:
            raise ABIError("CLType nesting limit")
        tag = self.u8()
        if tag in (13, 14, 18):
            self.cl_type(depth + 1)
        elif tag in (16, 17, 19):
            self.cl_type(depth + 1)
            self.cl_type(depth + 1)
        elif tag == 20:
            self.cl_type(depth + 1)
            self.cl_type(depth + 1)
            self.cl_type(depth + 1)
        elif tag == 15:
            self.u32()
        elif tag > 22:
            raise ABIError("Invalid CLType tag")

    def cl_value(self) -> SerializedCLValue:
        start = self.offset
        self.take(self.u32())
        self.cl_type()
        return SerializedCLValue(self.data[start:self.offset])

    def finish(self) -> None:
        if self.offset != len(self.data):
            raise ABIError("Trailing host result bytes")
