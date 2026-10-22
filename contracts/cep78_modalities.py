# SPDX-License-Identifier: Apache-2.0
"""Closed U8 modalities from the pinned CEP-78 2.0.0 reference."""

from cspr.enums import WireEnum
from contracts import cep78_errors as errors


class WhitelistMode(WireEnum):
    UNLOCKED = 0
    LOCKED = 1

    @classmethod
    def _missing_(cls, value: object) -> None:
        raise errors.InvalidWhitelistMode()


class NFTHolderMode(WireEnum):
    ACCOUNTS = 0
    CONTRACTS = 1
    MIXED = 2

    @classmethod
    def _missing_(cls, value: object) -> None:
        raise errors.InvalidHolderMode()


class MintingMode(WireEnum):
    INSTALLER = 0
    PUBLIC = 1
    ACL = 2

    @classmethod
    def _missing_(cls, value: object) -> None:
        raise errors.InvalidMintingMode()


class NFTKind(WireEnum):
    PHYSICAL = 0
    DIGITAL = 1
    VIRTUAL = 2

    @classmethod
    def _missing_(cls, value: object) -> None:
        raise errors.InvalidNftKind()


class Requirement(WireEnum):
    REQUIRED = 0
    OPTIONAL = 1
    UNNEEDED = 2

    @classmethod
    def _missing_(cls, value: object) -> None:
        raise errors.InvalidRequirement()


class NFTMetadataKind(WireEnum):
    CEP78 = 0
    NFT721 = 1
    RAW = 2
    CUSTOM_VALIDATED = 3

    @classmethod
    def _missing_(cls, value: object) -> None:
        raise errors.InvalidNFTMetadataKind()


class OwnershipMode(WireEnum):
    MINTER = 0
    ASSIGNED = 1
    TRANSFERABLE = 2

    @classmethod
    def _missing_(cls, value: object) -> None:
        raise errors.InvalidOwnershipMode()


class NFTIdentifierMode(WireEnum):
    ORDINAL = 0
    HASH = 1

    @classmethod
    def _missing_(cls, value: object) -> None:
        raise errors.InvalidIdentifierMode()


class MetadataMutability(WireEnum):
    IMMUTABLE = 0
    MUTABLE = 1

    @classmethod
    def _missing_(cls, value: object) -> None:
        raise errors.InvalidMetadataMutability()


class BurnMode(WireEnum):
    BURNABLE = 0
    NON_BURNABLE = 1

    @classmethod
    def _missing_(cls, value: object) -> None:
        raise errors.InvalidBurnMode()


class OwnerReverseLookupMode(WireEnum):
    NO_LOOKUP = 0
    COMPLETE = 1
    TRANSFERS_ONLY = 2

    @classmethod
    def _missing_(cls, value: object) -> None:
        raise errors.InvalidReportingMode()


class EventsMode(WireEnum):
    NO_EVENTS = 0
    CEP47 = 1
    CES = 2
    NATIVE = 3
    NATIVE_BYTES = 4

    @classmethod
    def _missing_(cls, value: object) -> None:
        raise errors.InvalidEventsMode()
