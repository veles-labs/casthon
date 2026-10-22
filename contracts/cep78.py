# SPDX-License-Identifier: Apache-2.0
"""Reusable CEP-78 2.0.0 class contract (9a624aa9a4f5cba59260f93652b76948e528c7f2).

Constructors create typed state; init completes deployment in stored context.
The reference license and the port's compatibility notes are in reference/cep78
and docs/cep78.md. Historical Rust storage migrations are outside this port.
"""

from typing import Any, cast

from casthon import (
    AccountCaller, AccountEntity, AccountHash, ContractCaller, ContractEntity,
    ContractHash, Dictionary, DictionaryAddress, EntityCaller, Hash, Key,
    Map, MISSING, OptionalArg, PackageHash, U8, U64, URef, CLKey, CLString,
    CLU8, CLU64, CLUnit,
)
from casthon.contract_api import runtime, storage
from casthon.contract_api.runtime import named_keys
from casthon.contracts import Contract, entry_point
from contracts import cep78_errors as errors
from contracts.cep78_events import (
    Approval, ApprovalForAll, ApprovalRevoked, Burn, MetadataUpdated, Migration,
    Mint, RevokedForAll, Transfer, VariablesSet, emit, initialize_events,
)
from contracts.cep78_metadata import validate_metadata, validate_schema
from contracts.cep78_modalities import (
    BurnMode, EventsMode, MetadataMutability, MintingMode, NFTHolderMode,
    NFTIdentifierMode, NFTKind, NFTMetadataKind, OwnerReverseLookupMode,
    OwnershipMode, Requirement, WhitelistMode,
)

MAX_TOTAL_TOKEN_SUPPLY = 1_000_000
PAGE_SIZE = 1000


def address_key(address: Key) -> str:
    """Upstream Display of the underlying address, without the Key tag/prefix."""
    if isinstance(address, (AccountHash, Hash, PackageHash)):
        return bytes(address)[1:].hex()
    if isinstance(address, (AccountEntity, ContractEntity)):
        return bytes(address)[2:].hex()
    raise errors.InvalidKey()


def operator_key(pair: bytes) -> str:
    return runtime.blake2b(pair).hex()


def immediate_caller() -> tuple[Key, Key | None]:
    """CEP-78 owns by contract version; packages are separate ACL/operators."""
    info = runtime.get_immediate_caller()
    if isinstance(info, AccountCaller) and info.account_hash is not None:
        return info.account_hash, None
    if isinstance(info, ContractCaller) and info.contract_hash is not None:
        return info.contract_hash, info.contract_package_hash
    if isinstance(info, EntityCaller) and info.entity is not None:
        return info.entity, info.package_hash
    raise errors.UnexpectedKeyVariant()


def _dictionary_address(seed: URef, item: str) -> DictionaryAddress:
    return DictionaryAddress(runtime.blake2b(seed.address + item.encode("utf-8")))


class Cep78(Contract):
    events = (Mint, Burn, Approval, ApprovalRevoked, ApprovalForAll, RevokedForAll,
              Transfer, MetadataUpdated, VariablesSet, Migration)

    installer: AccountHash
    collection_name: URef[str]
    collection_symbol: URef[str]
    total_token_supply: URef[U64]
    allow_minting: URef[bool]
    minting_mode: URef[MintingMode]
    ownership_mode: URef[OwnershipMode]
    nft_kind: URef[NFTKind]
    holder_mode: URef[NFTHolderMode]
    whitelist_mode: URef[WhitelistMode]
    acl_package_mode: URef[bool]
    package_operator_mode: URef[bool]
    operator_burn_mode: URef[bool]
    json_schema: URef[str]
    nft_metadata_kind: URef[NFTMetadataKind]
    nft_metadata_kinds: URef[Map[U8, U8]]
    identifier_mode: URef[NFTIdentifierMode]
    metadata_mutability: URef[MetadataMutability]
    burn_mode: URef[BurnMode]
    reporting_mode: URef[OwnerReverseLookupMode]
    events_mode: URef[EventsMode]
    receipt_name: URef[str]
    number_of_minted_tokens: URef[U64]
    page_limit: URef[U64]
    rlo_mflag: URef[bool]
    transfer_filter_contract: URef[Key | None]
    token_owners: Dictionary[str, Key]
    token_issuers: Dictionary[str, Key]
    approved: Dictionary[str, Key | None]
    operators: Dictionary[bytes, bool] = named_keys.reference(key=operator_key)
    burnt_tokens: Dictionary[str, None]
    balances: Dictionary[Key, U64] = named_keys.reference(key=address_key)
    acl_whitelist: Dictionary[Key, bool] = named_keys.reference(key=address_key)
    metadata_cep78: Dictionary[str, str]
    metadata_nft721: Dictionary[str, str]
    metadata_raw: Dictionary[str, str]
    metadata_custom_validated: Dictionary[str, str]
    hash_by_index: Dictionary[str, str]
    index_by_hash: Dictionary[str, U64]
    page_table: Dictionary[Key, list[bool]] = named_keys.reference(key=address_key)

    def __init__(self, collection_name: str, collection_symbol: str, total_token_supply: U64, *,
                 ownership_mode: OwnershipMode = OwnershipMode.TRANSFERABLE,
                 nft_metadata_kind: NFTMetadataKind = NFTMetadataKind.CEP78,
                 identifier_mode: NFTIdentifierMode = NFTIdentifierMode.ORDINAL,
                 metadata_mutability: MetadataMutability = MetadataMutability.IMMUTABLE,
                 minting_mode: MintingMode = MintingMode.INSTALLER,
                 allow_minting: bool = True, nft_kind: NFTKind = NFTKind.VIRTUAL,
                 holder_mode: NFTHolderMode = NFTHolderMode.MIXED,
                 whitelist_mode: WhitelistMode = WhitelistMode.UNLOCKED,
                 acl_whitelist: list[Key] | None = None, acl_package_mode: bool = False,
                 package_operator_mode: bool = False, operator_burn_mode: bool = False,
                 json_schema: str = "", additional_required_metadata: list[NFTMetadataKind] | None = None,
                 optional_metadata: list[NFTMetadataKind] | None = None,
                 burn_mode: BurnMode = BurnMode.BURNABLE,
                 owner_reverse_lookup_mode: OwnerReverseLookupMode = OwnerReverseLookupMode.NO_LOOKUP,
                 events_mode: EventsMode = EventsMode.NO_EVENTS,
                 transfer_filter_contract: Key | None = None, **state: Any) -> None:
        if total_token_supply == 0:
            raise errors.CannotInstallWithZeroSupply()
        if total_token_supply > MAX_TOTAL_TOKEN_SUPPLY:
            raise errors.ExceededMaxTotalSupply()
        if identifier_mode == NFTIdentifierMode.HASH and metadata_mutability == MetadataMutability.MUTABLE:
            raise errors.InvalidMetadataMutability()
        if (owner_reverse_lookup_mode == OwnerReverseLookupMode.TRANSFERS_ONLY
                and ownership_mode != OwnershipMode.TRANSFERABLE):
            raise errors.OwnerReverseLookupModeNotTransferable()
        if (ownership_mode == OwnershipMode.MINTER and minting_mode == MintingMode.INSTALLER
                and owner_reverse_lookup_mode == OwnerReverseLookupMode.COMPLETE):
            raise errors.InvalidReportingMode()
        if acl_whitelist and minting_mode != MintingMode.ACL:
            raise errors.InvalidMintingMode()
        if minting_mode == MintingMode.ACL and whitelist_mode == WhitelistMode.LOCKED and not acl_whitelist:
            raise errors.EmptyACLWhitelist()
        if transfer_filter_contract is not None:
            if ownership_mode != OwnershipMode.TRANSFERABLE:
                raise errors.TransferFilterContractNeedsTransferableMode()
            if not isinstance(transfer_filter_contract, (Hash, ContractEntity)):
                raise errors.InvalidTransferFilterContract()
        requirements = {int(kind): int(Requirement.OPTIONAL) for kind in optional_metadata or []}
        for kind in additional_required_metadata or []:
            requirements[int(kind)] = int(Requirement.REQUIRED)
        requirements[int(nft_metadata_kind)] = int(Requirement.REQUIRED)
        for discriminant in requirements:
            NFTMetadataKind.from_value(discriminant)
        if nft_metadata_kind == NFTMetadataKind.CUSTOM_VALIDATED and not json_schema:
            raise errors.MissingJsonSchema()
        if int(NFTMetadataKind.CUSTOM_VALIDATED) in requirements:
            validate_schema(json_schema)
        super().__init__(
            installer=runtime.get_caller(), collection_name=collection_name,
            collection_symbol=collection_symbol, total_token_supply=total_token_supply,
            allow_minting=allow_minting, minting_mode=minting_mode, ownership_mode=ownership_mode,
            nft_kind=nft_kind, holder_mode=holder_mode, whitelist_mode=whitelist_mode,
            acl_whitelist={key: True for key in acl_whitelist or []}, acl_package_mode=acl_package_mode,
            package_operator_mode=package_operator_mode, operator_burn_mode=operator_burn_mode,
            json_schema=json_schema, nft_metadata_kind=nft_metadata_kind, nft_metadata_kinds=requirements,
            identifier_mode=identifier_mode, metadata_mutability=metadata_mutability, burn_mode=burn_mode,
            reporting_mode=owner_reverse_lookup_mode, events_mode=events_mode,
            receipt_name="cep78_" + collection_name, number_of_minted_tokens=0,
            page_limit=(total_token_supply + PAGE_SIZE - 1) // PAGE_SIZE,
            rlo_mflag=False, transfer_filter_contract=transfer_filter_contract, **state)

    def _require_installer(self) -> None:
        caller, _ = immediate_caller()
        if caller != self.installer:
            raise errors.InvalidAccount()

    @entry_point
    def init(self, cep78_package_key: OptionalArg[str] = MISSING) -> None:
        marker = "cep78_" + self.collection_name.read()
        if marker in named_keys:
            raise errors.ContractAlreadyInitialized()
        self._require_installer()
        if cep78_package_key is MISSING:
            raise errors.MissingCep78PackageHash()
        named_keys[marker] = storage.new_uref(CLString(cep78_package_key))
        initialize_events(self.event_types())
        named_keys["cep78_python_layout"] = storage.new_uref(CLU8(1))

    def _require_transferable(self) -> None:
        if self.ownership_mode.read() is not OwnershipMode.TRANSFERABLE:
            raise errors.InvalidOwnershipMode()

    def _identifier(self, token_id: OptionalArg[U64], token_hash: OptionalArg[str], *,
                    check_bounds: bool = False) -> str:
        if self.identifier_mode.read() is NFTIdentifierMode.ORDINAL:
            if token_id is MISSING:
                raise errors.MissingTokenID()
            if check_bounds and token_id >= self.number_of_minted_tokens.read():
                raise errors.InvalidTokenIdentifier()
            return str(token_id)
        if token_hash is MISSING:
            raise errors.MissingTokenID()
        return token_hash

    def _owner(self, identifier: str) -> Key:
        owner = self.token_owners.get(identifier)
        if owner is None:
            raise errors.MissingOwnerTokenIdentifierKey()
        return owner

    def _require_not_burnt(self, identifier: str) -> None:
        if identifier in self.burnt_tokens:
            raise errors.PreviouslyBurntToken()

    def _is_operator(self, owner: Key, caller: Key, package: Key | None) -> bool:
        if self.operators.get(bytes(owner) + bytes(caller), False):
            return True
        return bool(self.package_operator_mode.read() and package is not None
                    and self.operators.get(bytes(owner) + bytes(package), False))

    def _metadata_dictionary(self, kind: NFTMetadataKind) -> Dictionary[str, str]:
        if kind is NFTMetadataKind.CEP78:
            return self.metadata_cep78
        if kind is NFTMetadataKind.NFT721:
            return self.metadata_nft721
        if kind is NFTMetadataKind.RAW:
            return self.metadata_raw
        return self.metadata_custom_validated

    def _validated_metadata(self, text: str) -> list[tuple[NFTMetadataKind, str]]:
        result = []
        for kind, required in sorted(self.nft_metadata_kinds.read().items()):
            if required == int(Requirement.UNNEEDED):
                continue
            mode = NFTMetadataKind.from_value(kind)
            try:
                result.append((mode, validate_metadata(mode, text, self.json_schema.read())))
            except errors.Cep78Error:
                if required == int(Requirement.REQUIRED):
                    raise
        return result

    @entry_point
    def set_variables(self, *, allow_minting: OptionalArg[bool] = MISSING,
                      acl_whitelist: OptionalArg[list[Key]] = MISSING,
                      acl_package_mode: OptionalArg[bool] = MISSING,
                      package_operator_mode: OptionalArg[bool] = MISSING,
                      operator_burn_mode: OptionalArg[bool] = MISSING) -> None:
        self._require_installer()
        if acl_whitelist is not MISSING and acl_whitelist:
            if self.whitelist_mode.read() is WhitelistMode.LOCKED:
                raise errors.InvalidWhitelistMode()
            seed = storage.new_dictionary_seed()
            replacement = Dictionary[Key, bool](seed=seed, key=address_key)
            for key in acl_whitelist:
                replacement[key] = True
            named_keys["acl_whitelist"] = seed
        for reference, value in ((self.allow_minting, allow_minting),
                                 (self.acl_package_mode, acl_package_mode),
                                 (self.package_operator_mode, package_operator_mode),
                                 (self.operator_burn_mode, operator_burn_mode)):
            if value is not MISSING:
                reference.write(value)
        emit(VariablesSet())

    @entry_point
    def mint(self, token_owner: Key, token_meta_data: str, *,
             token_hash: OptionalArg[str] = MISSING) -> tuple[str, Key, str]:
        if not self.allow_minting.read():
            raise errors.MintingIsPaused()
        index = self.number_of_minted_tokens.read()
        if index >= self.total_token_supply.read():
            raise errors.TokenSupplyDepleted()
        caller, package = immediate_caller()
        holder_mode = self.holder_mode.read()
        account_caller = isinstance(caller, (AccountHash, AccountEntity))
        if holder_mode is NFTHolderMode.CONTRACTS and account_caller:
            raise errors.InvalidHolderMode()
        mode = self.minting_mode.read()
        if mode is MintingMode.INSTALLER and caller != self.installer:
            raise errors.InvalidMinter()
        if mode is MintingMode.ACL:
            identity = package if self.acl_package_mode.read() and package is not None else caller
            if not self.acl_whitelist.get(identity, False):
                if isinstance(caller, Hash):
                    raise errors.UnlistedContractHash()
                if isinstance(caller, (AccountEntity, ContractEntity)):
                    raise errors.UnlistedEntity()
                raise errors.InvalidMinter()
        owner = caller if self.ownership_mode.read() is OwnershipMode.MINTER else token_owner
        address_key(owner)
        identifier = str(index)
        hash_mode = self.identifier_mode.read() is NFTIdentifierMode.HASH
        if hash_mode:
            identifier = token_hash if token_hash is not MISSING and token_hash else runtime.blake2b(token_meta_data.encode("utf-8")).hex()
            if identifier in self.index_by_hash:
                raise errors.DuplicateIdentifier()
        metadata = self._validated_metadata(token_meta_data)
        complete = self.reporting_mode.read() is OwnerReverseLookupMode.COMPLETE
        if complete and owner not in self.page_table:
            raise errors.UnregisteredOwnerInMint()
        for kind, value in metadata:
            self._metadata_dictionary(kind)[identifier] = value
        self.token_owners[identifier] = owner
        self.token_issuers[identifier] = caller
        if hash_mode:
            self.hash_by_index[str(index)] = identifier
            self.index_by_hash[identifier] = index
        self.balances[owner] = self.balances.get(owner, 0) + 1
        self.number_of_minted_tokens.write(index + 1)
        emit(Mint(owner, identifier, token_meta_data))
        if complete:
            seed = self._set_page(index, owner, True, on_mint=True)
            return self._receipt_name(index // PAGE_SIZE), _dictionary_address(seed, address_key(owner)), identifier
        # Rust returns Unit when lookup is disabled, despite its tuple ABI.
        runtime.ret(CLUnit())

    @entry_point
    def burn(self, *, token_id: OptionalArg[U64] = MISSING,
             token_hash: OptionalArg[str] = MISSING) -> None:
        if self.burn_mode.read() is BurnMode.NON_BURNABLE:
            raise errors.InvalidBurnMode()
        identifier = self._identifier(token_id, token_hash)
        owner = self._owner(identifier)
        caller, package = immediate_caller()
        if caller != owner and not (self.operator_burn_mode.read() and self._is_operator(owner, caller, package)):
            raise errors.InvalidTokenOwner()
        self._require_not_burnt(identifier)
        balance = self.balances.get(owner, 0)
        if balance == 0:
            raise errors.FatalTokenIdDuplication()
        self.burnt_tokens[identifier] = None
        self.balances[owner] = balance - 1
        # Burn preserves owner, metadata, minted count and reverse lookup bits.
        emit(Burn(owner, identifier, caller))

    @entry_point
    def approve(self, spender: Key, *, token_id: OptionalArg[U64] = MISSING,
                token_hash: OptionalArg[str] = MISSING) -> None:
        self._require_transferable()
        identifier = self._identifier(token_id, token_hash, check_bounds=True)
        owner = self._owner(identifier)
        caller, package = immediate_caller()
        if caller != owner and not self._is_operator(owner, caller, package):
            raise errors.InvalidTokenOwner()
        self._require_not_burnt(identifier)
        if spender == caller:
            raise errors.InvalidAccount()
        self.approved[identifier] = spender
        emit(Approval(owner, spender, identifier))

    @entry_point
    def revoke(self, *, token_id: OptionalArg[U64] = MISSING,
               token_hash: OptionalArg[str] = MISSING) -> None:
        self._require_transferable()
        identifier = self._identifier(token_id, token_hash, check_bounds=True)
        owner = self._owner(identifier)
        caller, package = immediate_caller()
        if caller != owner and not self._is_operator(owner, caller, package):
            raise errors.InvalidTokenOwner()
        self._require_not_burnt(identifier)
        self.approved[identifier] = None
        emit(ApprovalRevoked(owner, identifier))

    @entry_point
    def set_approval_for_all(self, approve_all: bool, operator: Key) -> None:
        self._require_transferable()
        caller, _ = immediate_caller()
        if caller == operator:
            raise errors.InvalidAccount()
        self.operators[bytes(caller) + bytes(operator)] = approve_all
        emit(ApprovalForAll(caller, operator) if approve_all else RevokedForAll(caller, operator))

    @entry_point
    def is_approved_for_all(self, token_owner: Key, operator: Key) -> bool:
        return self.operators.get(bytes(token_owner) + bytes(operator), False)

    @entry_point
    def transfer(self, source_key: Key, target_key: Key, *,
                 token_id: OptionalArg[U64] = MISSING,
                 token_hash: OptionalArg[str] = MISSING) -> tuple[str, Key]:
        self._require_transferable()
        identifier = self._identifier(token_id, token_hash)
        self._require_not_burnt(identifier)
        owner = self._owner(identifier)
        if source_key != owner:
            raise errors.InvalidTokenOwner()
        caller, package = immediate_caller()
        if (caller != owner and self.approved.get(identifier) != caller
                and not self._is_operator(owner, caller, package)):
            raise errors.InvalidTokenOwner()
        address_key(target_key)
        filter_contract = self.transfer_filter_contract.read()
        if filter_contract is not None:
            identifier_value = CLU64(cast(int, token_id)) if self.identifier_mode.read() is NFTIdentifierMode.ORDINAL else CLString(identifier)
            result = runtime.call_contract(filter_contract, "can_transfer", {
                "source_key": CLKey(source_key), "target_key": CLKey(target_key),
                "token_id": identifier_value}, U8)
            if result == 0:
                raise errors.TransferFilterContractDenied()
        balance = self.balances.get(owner, 0)
        if balance == 0:
            raise errors.FatalTokenIdDuplication()
        reporting = self.reporting_mode.read()
        if reporting is not OwnerReverseLookupMode.NO_LOOKUP:
            if source_key not in self.page_table or target_key not in self.page_table:
                raise errors.UnregisteredOwnerInTransfer()
        self.token_owners[identifier] = target_key
        self.balances[owner] = balance - 1
        self.balances[target_key] = self.balances.get(target_key, 0) + 1
        self.approved[identifier] = None
        emit(Transfer(owner, None if caller == owner else caller, target_key, identifier))
        if reporting is not OwnerReverseLookupMode.NO_LOOKUP:
            index = int(identifier) if self.identifier_mode.read() is NFTIdentifierMode.ORDINAL else self.index_by_hash[identifier]
            if reporting is OwnerReverseLookupMode.TRANSFERS_ONLY:
                self._set_page(index, source_key, True)
            seed = self._set_page(index, source_key, False)
            self._set_page(index, target_key, True)
            return self._receipt_name(index // PAGE_SIZE), _dictionary_address(seed, address_key(source_key))
        runtime.ret(CLUnit())

    @entry_point
    def balance_of(self, token_owner: Key) -> U64:
        return self.balances.get(token_owner, 0)

    @entry_point
    def owner_of(self, *, token_id: OptionalArg[U64] = MISSING,
                 token_hash: OptionalArg[str] = MISSING) -> Key:
        return self._owner(self._identifier(token_id, token_hash, check_bounds=True))

    @entry_point
    def metadata(self, *, token_id: OptionalArg[U64] = MISSING,
                 token_hash: OptionalArg[str] = MISSING) -> str:
        identifier = self._identifier(token_id, token_hash, check_bounds=True)
        for kind, requirement in sorted(self.nft_metadata_kinds.read().items()):
            if requirement == int(Requirement.REQUIRED):
                value = self._metadata_dictionary(NFTMetadataKind.from_value(kind)).get(identifier)
                if value is None:
                    raise errors.InvalidTokenIdentifier()
                return value
        raise errors.MissingTokenMetaData()

    @entry_point
    def get_approved(self, *, token_id: OptionalArg[U64] = MISSING,
                     token_hash: OptionalArg[str] = MISSING) -> Key | None:
        identifier = self._identifier(token_id, token_hash, check_bounds=True)
        self._require_not_burnt(identifier)
        return self.approved.get(identifier)

    @entry_point
    def set_token_metadata(self, token_meta_data: str, *, token_id: OptionalArg[U64] = MISSING,
                           token_hash: OptionalArg[str] = MISSING) -> None:
        if self.metadata_mutability.read() is MetadataMutability.IMMUTABLE:
            raise errors.ForbiddenMetadataUpdate()
        identifier = self._identifier(token_id, token_hash)
        if self._owner(identifier) != immediate_caller()[0]:
            raise errors.InvalidTokenOwner()
        for kind, value in self._validated_metadata(token_meta_data):
            self._metadata_dictionary(kind)[identifier] = value
        emit(MetadataUpdated(identifier, token_meta_data))

    def _receipt_name(self, page: int) -> str:
        return self.receipt_name.read() + "_m_1000_p_" + str(page)

    def _page(self, page: int) -> Dictionary[Key, list[bool]]:
        if page >= self.page_limit.read():
            raise errors.InvalidPageNumber()
        name = "page_" + str(page)
        seed = named_keys.get(name)
        if seed is None:
            seed = storage.new_dictionary(name)
        if not isinstance(seed, URef):
            raise errors.InvalidPageUref()
        return Dictionary[Key, list[bool]](seed=seed, key=address_key)

    def _set_page(self, index: int, owner: Key, value: bool, *, on_mint: bool = False) -> URef:
        page_number, offset = index // PAGE_SIZE, index % PAGE_SIZE
        table = self.page_table.get(owner)
        if table is None:
            if on_mint:
                raise errors.UnregisteredOwnerInMint()
            raise errors.UnregisteredOwnerInTransfer()
        page = self._page(page_number)
        bits = page.get(owner)
        if bits is None:
            if not value:
                raise errors.InvalidPageNumber()
            bits = [False] * PAGE_SIZE
        if not value and not bits[offset]:
            raise errors.InvalidTokenIdentifier()
        bits[offset] = value
        page[owner] = bits
        if not table[page_number]:
            table[page_number] = True
            self.page_table[owner] = table
        return page.seed

    @entry_point
    def register_owner(self, token_owner: Key) -> tuple[str, URef[str]]:
        if self.reporting_mode.read() is OwnerReverseLookupMode.NO_LOOKUP:
            runtime.ret(CLUnit())
        owner = immediate_caller()[0] if self.ownership_mode.read() is OwnershipMode.MINTER else token_owner
        if owner not in self.page_table:
            self.page_table[owner] = [False] * self.page_limit.read()
        collection = self.collection_name.read()
        package = named_keys.reference("cep78_" + collection, URef[str]).read()
        return collection, storage.new_uref(CLString(package))

    @entry_point
    def updated_receipts(self) -> list[tuple[str, Key]]:
        if self.reporting_mode.read() is not OwnerReverseLookupMode.COMPLETE:
            runtime.ret(CLUnit())
        caller, _ = immediate_caller()
        receipts: list[tuple[str, Key]] = []
        for page, allocated in enumerate(self.page_table.get(caller, [])):
            if allocated:
                receipts.append((self._receipt_name(page), _dictionary_address(self._page(page).seed, address_key(caller))))
        return receipts

    @entry_point
    def migrate(self, *, events_mode: OptionalArg[EventsMode] = MISSING,
                total_token_supply: OptionalArg[U64] = MISSING,
                acl_package_mode: OptionalArg[bool] = MISSING,
                package_operator_mode: OptionalArg[bool] = MISSING,
                operator_burn_mode: OptionalArg[bool] = MISSING) -> None:
        """Configure an upgrade of this Python layout; not a Rust 1.x migration."""
        self._require_installer()
        if "cep78_python_layout" not in named_keys:
            raise errors.InvalidMigrationFlag()
        if total_token_supply is not MISSING:
            if total_token_supply == 0:
                raise errors.CannotUpgradeWithZeroSupply()
            if total_token_supply > self.total_token_supply.read():
                raise errors.CannotUpgradeToMoreSupply()
            if total_token_supply < self.number_of_minted_tokens.read():
                raise errors.ExceededMaxTotalSupply()
            self.total_token_supply.write(total_token_supply)
        if events_mode is not MISSING:
            self.events_mode.write(events_mode)
        for reference, value in ((self.acl_package_mode, acl_package_mode),
                                 (self.package_operator_mode, package_operator_mode),
                                 (self.operator_burn_mode, operator_burn_mode)):
            if value is not MISSING and value:
                reference.write(value)
        initialize_events(self.event_types())
        emit(Migration())
