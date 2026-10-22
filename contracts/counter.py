"""An annotated class contract inheriting pause controls and ownership."""

from typing import Any

from casthon import (
    U32, URef, AccountHash, ContractHash, ContractPackageHash, Dictionary,
    InvalidArgument, export,
)
from casthon.contract_api import storage
from casthon.contract_api.runtime import get_caller, named_keys
from casthon.contracts import entry_point, export_contract
from contracts.pausable import Pausable, require_unpaused


def _account_key(account: AccountHash) -> str:
    return bytes(account)[1:].hex()


@export_contract
class Counter(Pausable):
    count: URef[U32]
    increments: Dictionary[AccountHash, U32] = named_keys.reference(key=_account_key)

    def __init__(self, initial: U32 = 0, **state: Any) -> None:
        super().__init__(count=initial, **state)

    def _increment_by(self, amount: U32) -> None:
        self.count.write(self.count.read() + amount)
        caller = get_caller()
        self.increments[caller] = self.increments.get(caller, 0) + amount

    @entry_point
    @require_unpaused
    def increment(self) -> None:
        self._increment_by(1)

    @entry_point
    @require_unpaused
    def increment_by(self, amount: U32) -> None:
        self._increment_by(amount)

    @entry_point
    def get(self) -> U32:
        return self.count.read()

    @entry_point
    def get_increments(self, owner: AccountHash) -> U32:
        return self.increments.get(owner, 0)


installed = named_keys.reference("py_counter", ContractHash)
installed_package = named_keys.reference("py_counter_package", ContractPackageHash)
installed_access = named_keys.reference("py_counter_access", URef[None])


@export
def call(initial: U32 = 0) -> None:
    if installed.name in named_keys:
        raise InvalidArgument()
    counter = Counter(initial)
    package, access = storage.create_contract_package_at_hash()
    contract, version = package.add_contract_version(counter)
    installed.set(contract)
    installed_package.set(package)
    installed_access.set(access)
