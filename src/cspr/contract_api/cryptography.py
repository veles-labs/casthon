"""Host-backed digest and signature functions, matching contract_api/cryptography.rs."""

from typing import cast
from .._ffi import call as _call
from ..errors import ABIError
from ..crypto import PublicKey, Signature, Secp256k1Signature
from ..enums import HashAlgorithm


def generic_hash(data: bytes, algorithm: HashAlgorithm = HashAlgorithm.BLAKE2B) -> bytes:
    algorithm = HashAlgorithm.from_value(int(algorithm))
    return cast(bytes, _call('generic_hash', data, int(algorithm)))


def recover_secp256k1(data: bytes, signature: Secp256k1Signature, recovery_id: int) -> PublicKey:
    if type(recovery_id) is not int or not 0 <= recovery_id < 4:
        raise ABIError("Recovery id must be in 0..3")
    return PublicKey.from_bytes(_call('recover_secp256k1', data, signature.to_bytes(), recovery_id))


def verify_signature(data: bytes, signature: Signature, public_key: PublicKey) -> None:
    _call('verify_signature', data, signature.to_bytes(), public_key.to_bytes())
