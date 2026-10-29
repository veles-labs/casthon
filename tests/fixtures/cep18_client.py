"""Stored caller probe: token operations belong to this contract's package."""

from casthon import ContractHash, ContractPackageHash, Key, U256, export
from casthon.contract_api import storage
from casthon.contract_api.runtime import named_keys
from casthon.contracts import Contract, entry_point, export_contract
from contracts.cep18 import Cep18


@export_contract
class TokenClient(Contract):
    token: ContractHash = named_keys.property()
    package: ContractPackageHash = named_keys.property()

    @entry_point
    def approve(self, spender: Key, amount: U256) -> None:
        self.token.call(Cep18.approve, spender, amount)

    @entry_point
    def transfer(self, recipient: Key, amount: U256) -> None:
        self.token.call(Cep18.transfer, recipient, amount)

    @entry_point
    def transfer_from(self, owner: Key, recipient: Key, amount: U256) -> None:
        self.token.call(Cep18.transfer_from, owner, recipient, amount)

    @entry_point
    def balance(self) -> U256:
        return self.token.call(Cep18.balance_of, self.package)


@export
def call(token: ContractHash) -> None:
    package, access = storage.create_contract_package_at_hash()
    client = TokenClient(token=token, package=package)
    contract, version = package.add_contract_version(client)
    named_keys["py_token_client"] = contract
    named_keys["py_token_client_package"] = package
    named_keys["py_token_client_access"] = access
