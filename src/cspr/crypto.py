"""Tagged public keys and signatures passed to Casper's cryptography API."""

from .errors import ABIError


class PublicKey:
    _tag = 0
    _size = 0

    def __init__(self, data: bytes = b"") -> None:
        if type(data) is not bytes or len(data) != self._size:
            raise ABIError("Invalid public key length")
        self.data = data

    def to_bytes(self) -> bytes:
        return bytes([self._tag]) + self.data

    @staticmethod
    def from_bytes(data: bytes) -> "PublicKey":
        if not data or data[0] > 2:
            raise ABIError("Invalid public key tag")
        return (SystemPublicKey, Ed25519PublicKey, Secp256k1PublicKey)[data[0]](data[1:])

    def __eq__(self, other: object) -> bool:
        return isinstance(other, PublicKey) and self.to_bytes() == other.to_bytes()

    def __hash__(self) -> int:
        return hash(self.to_bytes())

    @property
    def account_hash_preimage(self) -> bytes:
        return (b"system", b"ed25519", b"secp256k1")[self._tag] + b"\0" + self.data


class SystemPublicKey(PublicKey):
    pass


class Ed25519PublicKey(PublicKey):
    _tag, _size = 1, 32


class Secp256k1PublicKey(PublicKey):
    _tag, _size = 2, 33


class Signature:
    _tag = 0

    def __init__(self, data: bytes) -> None:
        if type(data) is not bytes or len(data) != 64 or self._tag not in (1, 2):
            raise ABIError("Invalid signature")
        self.data = data

    def to_bytes(self) -> bytes:
        return bytes([self._tag]) + self.data

    @staticmethod
    def from_bytes(data: bytes) -> "Signature":
        if not data or data[0] not in (1, 2):
            raise ABIError("Invalid signature tag")
        return (Ed25519Signature if data[0] == 1 else Secp256k1Signature)(data[1:])


class Ed25519Signature(Signature):
    _tag = 1


class Secp256k1Signature(Signature):
    _tag = 2
