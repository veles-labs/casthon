# SPDX-License-Identifier: Apache-2.0
"""Catchable CEP-78 2.0.0 errors, retaining upstream User error numbers."""

from casthon import UserError


class Cep78Error(UserError):
    user_code = 57

    def __init__(self) -> None:
        super().__init__(self.user_code)


class InvalidAccount(Cep78Error):
    user_code = 1


class MissingInstaller(Cep78Error):
    user_code = 2


class InvalidInstaller(Cep78Error):
    user_code = 3


class UnexpectedKeyVariant(Cep78Error):
    user_code = 4


class MissingTokenOwner(Cep78Error):
    user_code = 5


class InvalidTokenOwner(Cep78Error):
    user_code = 6


class FailedToGetArgBytes(Cep78Error):
    user_code = 7


class FailedToCreateDictionary(Cep78Error):
    user_code = 8


class MissingStorageUref(Cep78Error):
    user_code = 9


class InvalidStorageUref(Cep78Error):
    user_code = 10


class MissingOwnersUref(Cep78Error):
    user_code = 11


class InvalidOwnersUref(Cep78Error):
    user_code = 12


class FailedToAccessStorageDictionary(Cep78Error):
    user_code = 13


class FailedToAccessOwnershipDictionary(Cep78Error):
    user_code = 14


class DuplicateMinted(Cep78Error):
    user_code = 15


class FailedToConvertToCLValue(Cep78Error):
    user_code = 16


class MissingCollectionName(Cep78Error):
    user_code = 17


class InvalidCollectionName(Cep78Error):
    user_code = 18


class FailedToSerializeMetaData(Cep78Error):
    user_code = 19


class MissingAccount(Cep78Error):
    user_code = 20


class MissingMintingStatus(Cep78Error):
    user_code = 21


class InvalidMintingStatus(Cep78Error):
    user_code = 22


class MissingCollectionSymbol(Cep78Error):
    user_code = 23


class InvalidCollectionSymbol(Cep78Error):
    user_code = 24


class MissingTotalTokenSupply(Cep78Error):
    user_code = 25


class InvalidTotalTokenSupply(Cep78Error):
    user_code = 26


class MissingTokenID(Cep78Error):
    user_code = 27


class InvalidTokenIdentifier(Cep78Error):
    user_code = 28


class MissingTokenOwners(Cep78Error):
    user_code = 29


class MissingAccountHash(Cep78Error):
    user_code = 30


class InvalidAccountHash(Cep78Error):
    user_code = 31


class TokenSupplyDepleted(Cep78Error):
    user_code = 32


class MissingOwnedTokensDictionary(Cep78Error):
    user_code = 33


class TokenAlreadyBelongsToMinterFatal(Cep78Error):
    user_code = 34


class FatalTokenIdDuplication(Cep78Error):
    user_code = 35


class InvalidMinter(Cep78Error):
    user_code = 36


class MissingMintingMode(Cep78Error):
    user_code = 37


class InvalidMintingMode(Cep78Error):
    user_code = 38


class MissingInstallerKey(Cep78Error):
    user_code = 39


class FailedToConvertToAccountHash(Cep78Error):
    user_code = 40


class InvalidBurner(Cep78Error):
    user_code = 41


class PreviouslyBurntToken(Cep78Error):
    user_code = 42


class MissingAllowMinting(Cep78Error):
    user_code = 43


class InvalidAllowMinting(Cep78Error):
    user_code = 44


class MissingNumberOfMintedTokens(Cep78Error):
    user_code = 45


class InvalidNumberOfMintedTokens(Cep78Error):
    user_code = 46


class MissingTokenMetaData(Cep78Error):
    user_code = 47


class InvalidTokenMetaData(Cep78Error):
    user_code = 48


class MissingApprovedAccountHash(Cep78Error):
    user_code = 49


class InvalidApprovedAccountHash(Cep78Error):
    user_code = 50


class MissingApprovedTokensDictionary(Cep78Error):
    user_code = 51


class TokenAlreadyApproved(Cep78Error):
    user_code = 52


class MissingApproveAll(Cep78Error):
    user_code = 53


class InvalidApproveAll(Cep78Error):
    user_code = 54


class MissingOperator(Cep78Error):
    user_code = 55


class InvalidOperator(Cep78Error):
    user_code = 56


class Phantom(Cep78Error):
    user_code = 57


class ContractAlreadyInitialized(Cep78Error):
    user_code = 58


class MintingIsPaused(Cep78Error):
    user_code = 59


class FailureToParseAccountHash(Cep78Error):
    user_code = 60


class VacantValueInDictionary(Cep78Error):
    user_code = 61


class MissingOwnershipMode(Cep78Error):
    user_code = 62


class InvalidOwnershipMode(Cep78Error):
    user_code = 63


class InvalidTokenMinter(Cep78Error):
    user_code = 64


class MissingOwnedTokens(Cep78Error):
    user_code = 65


class InvalidAccountKeyInDictionary(Cep78Error):
    user_code = 66


class MissingJsonSchema(Cep78Error):
    user_code = 67


class InvalidJsonSchema(Cep78Error):
    user_code = 68


class InvalidKey(Cep78Error):
    user_code = 69


class InvalidOwnedTokens(Cep78Error):
    user_code = 70


class MissingTokenURI(Cep78Error):
    user_code = 71


class InvalidTokenURI(Cep78Error):
    user_code = 72


class MissingNftKind(Cep78Error):
    user_code = 73


class InvalidNftKind(Cep78Error):
    user_code = 74


class MissingHolderMode(Cep78Error):
    user_code = 75


class InvalidHolderMode(Cep78Error):
    user_code = 76


class MissingWhitelistMode(Cep78Error):
    user_code = 77


class InvalidWhitelistMode(Cep78Error):
    user_code = 78


class MissingContractWhiteList(Cep78Error):
    user_code = 79


class InvalidContractWhitelist(Cep78Error):
    user_code = 80


class UnlistedContractHash(Cep78Error):
    user_code = 81


class InvalidContract(Cep78Error):
    user_code = 82


class EmptyContractWhitelist(Cep78Error):
    user_code = 83


class MissingReceiptName(Cep78Error):
    user_code = 84


class InvalidReceiptName(Cep78Error):
    user_code = 85


class InvalidJsonMetadata(Cep78Error):
    user_code = 86


class InvalidJsonFormat(Cep78Error):
    user_code = 87


class FailedToParseCep99Metadata(Cep78Error):
    user_code = 88


class FailedToParse721Metadata(Cep78Error):
    user_code = 89


class FailedToParseCustomMetadata(Cep78Error):
    user_code = 90


class InvalidCEP99Metadata(Cep78Error):
    user_code = 91


class FailedToJsonifyCEP99Metadata(Cep78Error):
    user_code = 92


class InvalidNFT721Metadata(Cep78Error):
    user_code = 93


class FailedToJsonifyNFT721Metadata(Cep78Error):
    user_code = 94


class InvalidCustomMetadata(Cep78Error):
    user_code = 95


class MissingNFTMetadataKind(Cep78Error):
    user_code = 96


class InvalidNFTMetadataKind(Cep78Error):
    user_code = 97


class MissingIdentifierMode(Cep78Error):
    user_code = 98


class InvalidIdentifierMode(Cep78Error):
    user_code = 99


class FailedToParseTokenId(Cep78Error):
    user_code = 100


class MissingMetadataMutability(Cep78Error):
    user_code = 101


class InvalidMetadataMutability(Cep78Error):
    user_code = 102


class FailedToJsonifyCustomMetadata(Cep78Error):
    user_code = 103


class ForbiddenMetadataUpdate(Cep78Error):
    user_code = 104


class MissingBurnMode(Cep78Error):
    user_code = 105


class InvalidBurnMode(Cep78Error):
    user_code = 106


class MissingHashByIndex(Cep78Error):
    user_code = 107


class InvalidHashByIndex(Cep78Error):
    user_code = 108


class MissingIndexByHash(Cep78Error):
    user_code = 109


class InvalidIndexByHash(Cep78Error):
    user_code = 110


class MissingPageTableURef(Cep78Error):
    user_code = 111


class InvalidPageTableURef(Cep78Error):
    user_code = 112


class MissingPageLimit(Cep78Error):
    user_code = 113


class InvalidPageLimit(Cep78Error):
    user_code = 114


class InvalidPageNumber(Cep78Error):
    user_code = 115


class InvalidPageIndex(Cep78Error):
    user_code = 116


class MissingUnmatchedHashCount(Cep78Error):
    user_code = 117


class InvalidUnmatchedHashCount(Cep78Error):
    user_code = 118


class MissingPackageHashForUpgrade(Cep78Error):
    user_code = 119


class MissingPageUref(Cep78Error):
    user_code = 120


class InvalidPageUref(Cep78Error):
    user_code = 121


class CannotUpgradeWithZeroSupply(Cep78Error):
    user_code = 122


class CannotInstallWithZeroSupply(Cep78Error):
    user_code = 123


class MissingMigrationFlag(Cep78Error):
    user_code = 124


class InvalidMigrationFlag(Cep78Error):
    user_code = 125


class ContractAlreadyMigrated(Cep78Error):
    user_code = 126


class UnregisteredOwnerInMint(Cep78Error):
    user_code = 127


class UnregisteredOwnerInTransfer(Cep78Error):
    user_code = 128


class MissingReportingMode(Cep78Error):
    user_code = 129


class InvalidReportingMode(Cep78Error):
    user_code = 130


class MissingPage(Cep78Error):
    user_code = 131


class UnregisteredOwnerFromMigration(Cep78Error):
    user_code = 132


class ExceededMaxTotalSupply(Cep78Error):
    user_code = 133


class MissingCep78PackageHash(Cep78Error):
    user_code = 134


class InvalidCep78InvalidHash(Cep78Error):
    user_code = 135


class InvalidPackageHashName(Cep78Error):
    user_code = 136


class InvalidAccessKeyName(Cep78Error):
    user_code = 137


class InvalidCheckForUpgrade(Cep78Error):
    user_code = 138


class InvalidNamedKeyConvention(Cep78Error):
    user_code = 139


class OwnerReverseLookupModeNotTransferable(Cep78Error):
    user_code = 140


class InvalidAdditionalRequiredMetadata(Cep78Error):
    user_code = 141


class InvalidOptionalMetadata(Cep78Error):
    user_code = 142


class MissingOptionalNFTMetadataKind(Cep78Error):
    user_code = 143


class InvalidOptionalNFTMetadataKind(Cep78Error):
    user_code = 144


class MissingAdditionalNFTMetadataKind(Cep78Error):
    user_code = 145


class InvalidAdditionalNFTMetadataKind(Cep78Error):
    user_code = 146


class InvalidRequirement(Cep78Error):
    user_code = 147


class MissingEventsMode(Cep78Error):
    user_code = 148


class InvalidEventsMode(Cep78Error):
    user_code = 149


class CannotUpgradeToMoreSupply(Cep78Error):
    user_code = 150


class MissingOperatorDict(Cep78Error):
    user_code = 151


class MissingApprovedDict(Cep78Error):
    user_code = 152


class MissingSpenderAccountHash(Cep78Error):
    user_code = 153


class InvalidSpenderAccountHash(Cep78Error):
    user_code = 154


class MissingOwnerTokenIdentifierKey(Cep78Error):
    user_code = 155


class InvalidTransferFilterContract(Cep78Error):
    user_code = 156


class MissingTransferFilterContract(Cep78Error):
    user_code = 157


class TransferFilterContractNeedsTransferableMode(Cep78Error):
    user_code = 158


class TransferFilterContractDenied(Cep78Error):
    user_code = 159


class MissingACLWhiteList(Cep78Error):
    user_code = 160


class InvalidACLWhitelist(Cep78Error):
    user_code = 161


class EmptyACLWhitelist(Cep78Error):
    user_code = 162


class InvalidACLPackageMode(Cep78Error):
    user_code = 163


class MissingACLPackageMode(Cep78Error):
    user_code = 164


class InvalidPackageOperatorMode(Cep78Error):
    user_code = 165


class MissingPackageOperatorMode(Cep78Error):
    user_code = 166


class InvalidOperatorBurnMode(Cep78Error):
    user_code = 167


class MissingOperatorBurnMode(Cep78Error):
    user_code = 168


class InvalidIdentifier(Cep78Error):
    user_code = 169


class DuplicateIdentifier(Cep78Error):
    user_code = 170


class CannotInsertArg(Cep78Error):
    user_code = 171


class InvalidPackageHash(Cep78Error):
    user_code = 172


class InvalidUrefMigrationKey(Cep78Error):
    user_code = 173


class InvalidRloKey(Cep78Error):
    user_code = 174


class UnlistedEntity(Cep78Error):
    user_code = 175


class FailedToConvertToEntityHash(Cep78Error):
    user_code = 176


class InvalidMinterEntity(Cep78Error):
    user_code = 177


class FailedToConvertEventToJson(Cep78Error):
    user_code = 178


class MissingVersionContractKey(Cep78Error):
    user_code = 179


class InvalidVersionContractKey(Cep78Error):
    user_code = 180
