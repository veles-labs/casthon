"""Numeric host-API enums, matching casper-node's wire discriminants."""

from enum import IntEnum
from typing import Self


class WireEnum(IntEnum):
    """A closed U8 enum; annotations preserve its member type on the wire."""

    def __init_subclass__(cls) -> None:
        super().__init_subclass__()
        if len(cls.__members__) != len(list(cls)):
            raise ValueError("WireEnum members require distinct values")
        if any(not 0 <= member.value <= 255 for member in cls):
            raise ValueError("WireEnum discriminants must fit U8")

    @classmethod
    def from_value(cls, value: int) -> Self:
        return cls(value)


class Phase(WireEnum):
    SYSTEM = 0
    PAYMENT = 1
    SESSION = 2
    FINALIZE_PAYMENT = 3


class ActionType(WireEnum):
    DEPLOYMENT = 0
    KEY_MANAGEMENT = 1


class AddKeyFailure(WireEnum):
    MAX_KEYS_LIMIT = 1
    DUPLICATE_KEY = 2
    PERMISSION_DENIED = 3


class RemoveKeyFailure(WireEnum):
    MISSING_KEY = 1
    PERMISSION_DENIED = 2
    THRESHOLD_VIOLATION = 3


class UpdateKeyFailure(WireEnum):
    MISSING_KEY = 1
    PERMISSION_DENIED = 2
    THRESHOLD_VIOLATION = 3


class SetThresholdFailure(WireEnum):
    KEY_MANAGEMENT_THRESHOLD = 1
    DEPLOYMENT_THRESHOLD = 2
    PERMISSION_DENIED_ERROR = 3
    INSUFFICIENT_TOTAL_WEIGHT = 4


class SystemEntityType(WireEnum):
    MINT = 0
    HANDLE_PAYMENT = 1
    STANDARD_PAYMENT = 2
    AUCTION = 3


class TransferredTo(WireEnum):
    EXISTING_ACCOUNT = 0
    NEW_ACCOUNT = 1


class HashAlgorithm(WireEnum):
    BLAKE2B = 0
    BLAKE3 = 1
    SHA256 = 2


class MessageTopicOperation(WireEnum):
    ADD = 0


class EntryPointAccess(WireEnum):
    PUBLIC = 1
    GROUPS = 2
    TEMPLATE = 3


class EntryPointType(WireEnum):
    CALLER = 0
    CALLED = 1
    FACTORY = 128


class EntryPointPayment(WireEnum):
    CALLER = 0
    DIRECT_INVOCATION_ONLY = 1
    SELF_ONWARD = 2
