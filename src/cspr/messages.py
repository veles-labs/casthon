"""MessagePayload bytesrepr (String and Bytes variants)."""

from .codec import encode


class MessagePayload:
    def to_bytes(self) -> bytes:
        raise NotImplementedError


class MessageString(MessagePayload):
    def __init__(self, value: str) -> None:
        self.value = value

    def to_bytes(self) -> bytes:
        return b"\0" + encode("String", self.value)


class MessageBytes(MessagePayload):
    def __init__(self, value: bytes) -> None:
        self.value = value

    def to_bytes(self) -> bytes:
        return b"\1" + encode("Bytes", self.value)
