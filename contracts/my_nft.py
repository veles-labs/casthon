# SPDX-License-Identifier: Apache-2.0
"""An inherited NFT collection with an explicit installer and Python upgrades."""

from typing import Any

from casthon import (
    CLString, ContractHash, ContractPackageHash, Hash, Key, MISSING,
    OptionalArg, U64, export,
)
from casthon.contract_api import runtime, storage
from casthon.contract_api.runtime import named_keys
from casthon.contracts import export_contract
from contracts.cep78 import Cep78
from contracts import cep78_errors as errors
from contracts.cep78_modalities import (
    BurnMode, EventsMode, MetadataMutability, MintingMode, NFTHolderMode,
    NFTIdentifierMode, NFTKind, NFTMetadataKind, OwnerReverseLookupMode,
    OwnershipMode, WhitelistMode,
)

DEFAULT_NAME = "My NFT"


@export_contract
class MyNft(Cep78):
    def __init__(self, collection_name: str = DEFAULT_NAME, collection_symbol: str = "MNFT",
                 total_token_supply: U64 = 1000, *,
                 nft_metadata_kind: NFTMetadataKind = NFTMetadataKind.NFT721,
                 metadata_mutability: MetadataMutability = MetadataMutability.MUTABLE,
                 owner_reverse_lookup_mode: OwnerReverseLookupMode = OwnerReverseLookupMode.COMPLETE,
                 events_mode: EventsMode = EventsMode.CES, **state: Any) -> None:
        super().__init__(collection_name, collection_symbol, total_token_supply,
                         nft_metadata_kind=nft_metadata_kind, metadata_mutability=metadata_mutability,
                         owner_reverse_lookup_mode=owner_reverse_lookup_mode,
                         events_mode=events_mode, **state)


@export
def call(collection_name: OptionalArg[str] = DEFAULT_NAME, *,
         collection_symbol: OptionalArg[str] = MISSING,
         total_token_supply: OptionalArg[U64] = MISSING,
         ownership_mode: OptionalArg[OwnershipMode] = MISSING,
         nft_metadata_kind: OptionalArg[NFTMetadataKind] = MISSING,
         identifier_mode: OptionalArg[NFTIdentifierMode] = MISSING,
         metadata_mutability: OptionalArg[MetadataMutability] = MISSING,
         minting_mode: OptionalArg[MintingMode] = MISSING,
         allow_minting: OptionalArg[bool] = MISSING,
         nft_kind: OptionalArg[NFTKind] = MISSING,
         holder_mode: OptionalArg[NFTHolderMode] = MISSING,
         whitelist_mode: OptionalArg[WhitelistMode] = MISSING,
         acl_whitelist: OptionalArg[list[Key]] = MISSING,
         acl_package_mode: OptionalArg[bool] = MISSING,
         package_operator_mode: OptionalArg[bool] = MISSING,
         operator_burn_mode: OptionalArg[bool] = MISSING,
         json_schema: OptionalArg[str] = MISSING,
         additional_required_metadata: OptionalArg[list[NFTMetadataKind]] = MISSING,
         optional_metadata: OptionalArg[list[NFTMetadataKind]] = MISSING,
         burn_mode: OptionalArg[BurnMode] = MISSING,
         owner_reverse_lookup_mode: OptionalArg[OwnerReverseLookupMode] = MISSING,
         events_mode: OptionalArg[EventsMode] = MISSING,
         transfer_filter_contract: OptionalArg[Key | None] = MISSING) -> None:
    if collection_name is MISSING:
        collection_name = DEFAULT_NAME
    package_name = "cep78_contract_package_" + collection_name
    access_name = "cep78_contract_package_access_" + collection_name
    contract_name = "cep78_contract_hash_" + collection_name
    version_name = "cep78_contract_version_" + collection_name
    if access_name in named_keys:
        package_key = named_keys.get(package_name)
        previous_key = named_keys.get(contract_name)
        if not isinstance(package_key, Hash):
            raise errors.MissingPackageHashForUpgrade()
        if not isinstance(previous_key, Hash):
            raise errors.InvalidContract()
        package = ContractPackageHash(bytes(package_key))
        previous = ContractHash(bytes(previous_key))
        contract, version = storage.add_contract_version(package, MyNft.entry_points(), {})
        contract.call(MyNft.migrate, events_mode=events_mode,
                      total_token_supply=total_token_supply,
                      acl_package_mode=acl_package_mode, package_operator_mode=package_operator_mode,
                      operator_burn_mode=operator_burn_mode)
        package.disable_contract_version(previous)
    else:
        options: dict[str, Any] = {"collection_name": collection_name}
        for argument, value in (
            ("collection_symbol", collection_symbol), ("total_token_supply", total_token_supply),
            ("ownership_mode", ownership_mode), ("nft_metadata_kind", nft_metadata_kind),
            ("identifier_mode", identifier_mode), ("metadata_mutability", metadata_mutability),
            ("minting_mode", minting_mode), ("allow_minting", allow_minting), ("nft_kind", nft_kind),
            ("holder_mode", holder_mode), ("whitelist_mode", whitelist_mode),
            ("acl_whitelist", acl_whitelist), ("acl_package_mode", acl_package_mode),
            ("package_operator_mode", package_operator_mode), ("operator_burn_mode", operator_burn_mode),
            ("json_schema", json_schema), ("additional_required_metadata", additional_required_metadata),
            ("optional_metadata", optional_metadata), ("burn_mode", burn_mode),
            ("owner_reverse_lookup_mode", owner_reverse_lookup_mode), ("events_mode", events_mode),
            ("transfer_filter_contract", transfer_filter_contract),
        ):
            if value is not MISSING:
                options[argument] = value
        nft = MyNft(**options)
        package, access = storage.create_contract_package_at_hash()
        contract, version = package.add_contract_version(nft, message_topics=("events",))
        named_keys[package_name] = package
        named_keys[access_name] = access
        contract.call(MyNft.init, cep78_package_key="contract-package-" + bytes(package)[1:].hex())
    named_keys[contract_name] = contract
    major, _, _ = runtime.get_protocol_version()
    named_keys[version_name] = storage.new_uref(CLString(str(major) + "." + str(version)))
