# SPDX-License-Identifier: Apache-2.0
"""Catchable CEP-18 2.0.0 errors, preserving upstream User error numbers."""

from casthon import UserError


class Cep18Error(UserError):
    user_code = 60008

    def __init__(self) -> None:
        super().__init__(self.user_code)


class InvalidContext(Cep18Error):
    user_code = 60000


class InsufficientBalance(Cep18Error):
    user_code = 60001


class InsufficientAllowance(Cep18Error):
    user_code = 60002


class Overflow(Cep18Error):
    user_code = 60003


class PackageHashMissing(Cep18Error):
    user_code = 60004


class PackageHashNotPackage(Cep18Error):
    user_code = 60005


class InvalidEventsMode(Cep18Error):
    user_code = 60006


class MissingEventsMode(Cep18Error):
    user_code = 60007


class Phantom(Cep18Error):
    user_code = 60008


class FailedToGetArgBytes(Cep18Error):
    user_code = 60009


class InsufficientRights(Cep18Error):
    user_code = 60010


class InvalidAdminList(Cep18Error):
    user_code = 60011


class InvalidMinterList(Cep18Error):
    user_code = 60012


class InvalidNoneList(Cep18Error):
    user_code = 60013


class InvalidEnableMBFlag(Cep18Error):
    user_code = 60014


class AlreadyInitialized(Cep18Error):
    user_code = 60015


class MintBurnDisabled(Cep18Error):
    user_code = 60016


class CannotTargetSelfUser(Cep18Error):
    user_code = 60017


class InvalidBurnTarget(Cep18Error):
    user_code = 60018


class MissingPackageHashForUpgrade(Cep18Error):
    user_code = 60019


class MissingContractHashForUpgrade(Cep18Error):
    user_code = 60020


class InvalidKeyType(Cep18Error):
    user_code = 60021


class FailedToConvertToJson(Cep18Error):
    user_code = 60022


class FailedToReturnEntryPointResult(Cep18Error):
    user_code = 60023


class FailedToCreateDictionary(Cep18Error):
    user_code = 60024


class FailedToConvertBytes(Cep18Error):
    user_code = 60025


class FailedToChangeTotalSupply(Cep18Error):
    user_code = 60026


class FailedToReadFromStorage(Cep18Error):
    user_code = 60027


class FailedToGetKey(Cep18Error):
    user_code = 60028


class FailedToDisableContractVersion(Cep18Error):
    user_code = 60029


class FailedToInsertToSecurityList(Cep18Error):
    user_code = 60030


class UrefNotFound(Cep18Error):
    user_code = 60031


class FailedToGetOldContractHashKey(Cep18Error):
    user_code = 60032


class FailedToGetOldPackageKey(Cep18Error):
    user_code = 60033


class FailedToGetPackageKey(Cep18Error):
    user_code = 60034


class MissingStorageUref(Cep18Error):
    user_code = 60035


class InvalidStorageUref(Cep18Error):
    user_code = 60036


class MissingVersionContractKey(Cep18Error):
    user_code = 60037


class InvalidVersionContractKey(Cep18Error):
    user_code = 60038
