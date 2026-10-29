"""Hello world with typed state, catchable errors and finally cleanup."""

from casthon import ContractHash, ContractPackageHash, U32, URef, UserError, export
from casthon.contract_api import storage
from casthon.contract_api.runtime import named_keys
from casthon.contracts import Contract, entry_point, export_contract


@export_contract
class Hello(Contract):
    calls: U32 = named_keys.property()

    @entry_point
    def greet(self, name: str) -> str:
        try:
            name = name.strip()
            if not name:
                raise ValueError("Empty name")
            if len(name) > 64:
                raise UserError(1)
            return f"Hello, {name}!"
        except ValueError:
            return "Hello, stranger!"
        finally:
            self.calls += 1
            print("Greeting finished")


installed = named_keys.reference("hello", ContractHash)
installed_package = named_keys.reference("hello_package", ContractPackageHash)
installed_access = named_keys.reference("hello_access", URef[None])


@export
def call() -> None:
    package, access = storage.create_contract_package_at_hash()
    contract, _ = package.add_contract_version(Hello(calls=0))
    installed.set(contract)
    installed_package.set(package)
    installed_access.set(access)
