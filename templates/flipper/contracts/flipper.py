"""A minimal boolean smart contract."""

from casthon import ContractHash, ContractPackageHash, InvalidArgument, URef, export
from casthon.contract_api import storage
from casthon.contract_api.runtime import named_keys
from casthon.contracts import Contract, entry_point, export_contract


@export_contract
class Flipper(Contract):
    value: bool = named_keys.property()

    @entry_point
    def flip(self) -> None:
        self.value = not self.value

    @entry_point
    def get(self) -> bool:
        return self.value


installed = named_keys.reference("flipper", ContractHash)
installed_package = named_keys.reference("flipper_package", ContractPackageHash)
installed_access = named_keys.reference("flipper_access", URef[None])


@export
def call(initial: bool = False) -> None:
    if installed.name in named_keys:
        raise InvalidArgument()
    package, access = storage.create_contract_package_at_hash()
    contract, _ = package.add_contract_version(Flipper(value=initial))
    installed.set(contract)
    installed_package.set(package)
    installed_access.set(access)
