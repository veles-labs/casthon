"""Minimal stored counter shared by the tooling benchmarks."""

from cspr import ContractHash, U32, URef, export
from cspr.contract_api import storage
from cspr.contract_api.runtime import named_keys
from cspr.contracts import Contract, entry_point, export_contract


@export_contract
class BenchCounter(Contract):
    value: URef[U32]

    def __init__(self) -> None:
        super().__init__(value=0)

    @entry_point
    def get(self) -> U32:
        return self.value.read()

    @entry_point
    def set(self, value: U32) -> None:
        self.value.write(value)

    @entry_point
    def increment_by(self, amount: U32) -> None:
        self.value.write(self.value.read() + amount)

    @entry_point
    def version(self) -> U32:
        return 1  # benchmark-edit


installed = named_keys.reference("bench_counter", ContractHash)


@export
def call() -> None:
    counter = BenchCounter()
    package, _access = storage.create_contract_package_at_hash()
    contract, _version = package.add_contract_version(counter)
    installed.set(contract)
