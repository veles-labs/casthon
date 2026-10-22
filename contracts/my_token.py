# SPDX-License-Identifier: Apache-2.0
"""An inherited CEP-18 token with defaults and an explicit installer/upgrade."""

from typing import Any

from casthon import (
    ABIError, ApiError, CLString, ContractEntity,
    Hash, Key, PackageHash, U8, U256, URef, OptionalArg, MISSING, export,
)
from casthon.contract_api import runtime, storage
from casthon.contract_api.runtime import named_keys
from casthon.contracts import export_contract
from contracts.cep18 import Cep18
from contracts.cep18_events import EventsMode
from contracts.cep18_errors import (
    FailedToDisableContractVersion, FailedToGetOldContractHashKey, FailedToGetOldPackageKey,
    InvalidKeyType,
    MissingContractHashForUpgrade, MissingPackageHashForUpgrade, MissingVersionContractKey,
)

DEFAULT_NAME = "My Token"


@export_contract
class MyToken(Cep18):
    def __init__(self, name: str = DEFAULT_NAME, symbol: str = "MYT", decimals: U8 = 18,
                 total_supply: U256 = 1_000_000 * 10**18, *, events_mode: EventsMode = EventsMode.CES,
                 enable_mint_burn: U8 = 1, **state: Any) -> None:
        super().__init__(name, symbol, decimals, total_supply, events_mode=events_mode,
                         enable_mint_burn=enable_mint_burn, **state)


@export
def call(name: OptionalArg[str] = DEFAULT_NAME, *, symbol: OptionalArg[str] = MISSING,
         decimals: OptionalArg[U8] = MISSING, total_supply: OptionalArg[U256] = MISSING,
         events_mode: OptionalArg[EventsMode] = MISSING,
         enable_mint_burn: OptionalArg[U8] = MISSING,
         admin_list: OptionalArg[list[Key]] = MISSING,
         minter_list: OptionalArg[list[Key]] = MISSING) -> None:
    if name is MISSING:
        name = DEFAULT_NAME
    package_name = "cep18_contract_package_" + name
    access_name = "cep18_contract_package_access_" + name
    contract_name = "cep18_contract_hash_" + name
    version_name = "cep18_contract_version_" + name
    if access_name in named_keys:
        package = named_keys.get(package_name)
        if package is None:
            raise FailedToGetOldPackageKey()
        if not isinstance(package, (Hash, PackageHash, ContractEntity)):
            raise MissingPackageHashForUpgrade()
        previous = named_keys.get(contract_name)
        if previous is None:
            raise FailedToGetOldContractHashKey()
        if not isinstance(previous, (Hash, ContractEntity)):
            raise MissingContractHashForUpgrade()
        version_key = named_keys.get(version_name)
        if version_key is None:
            raise MissingVersionContractKey()
        if not isinstance(version_key, URef):
            raise InvalidKeyType()
        # A nonempty version string identifies an existing 2.0 installation.
        # Upstream's 1.x migration also supplies a new message topic here.
        try:
            old_version = storage.read(version_key, str)
        except (ABIError, ApiError):
            old_version = ""
        topics = () if old_version else ("events",)
        contract, version = storage.add_contract_version(package, MyToken.entry_points(), {}, topics)
        try:
            storage.disable_contract_version(package, previous)
        except ApiError:
            raise FailedToDisableContractVersion()
        if events_mode is not MISSING:
            contract.call(MyToken.change_events_mode, events_mode)
    else:
        options: dict[str, Any] = {"name": name}
        for argument, value in (("symbol", symbol), ("decimals", decimals), ("total_supply", total_supply),
                                ("enable_mint_burn", enable_mint_burn), ("admin_list", admin_list),
                                ("minter_list", minter_list), ("events_mode", events_mode)):
            if value is not MISSING:
                options[argument] = value
        token = MyToken(**options)
        package, access = storage.create_contract_package_at_hash()
        contract, version = package.add_contract_version(token, message_topics=("events",))
        named_keys[package_name] = package
        named_keys[access_name] = access
        contract.call(MyToken.init, package_hash=package, contract_hash=contract)

    named_keys[contract_name] = contract
    major, _, _ = runtime.get_protocol_version()
    named_keys[version_name] = storage.new_uref(CLString(str(major) + "." + str(version)))
