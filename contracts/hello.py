"""Hello world with typed state, catchable errors and finally cleanup."""

from cspr import U32, URef, UserError, export
from cspr.contract_api import storage
from cspr.contract_api.runtime import named_keys
from cspr.contracts import Contract, entry_point, export_contract


@export_contract
class Hello(Contract):
    calls: URef[U32]

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
            self.calls.write(self.calls.read() + 1)
            print("Greeting finished")


@export
def call() -> None:
    package, access = storage.create_contract_package_at_hash()
    contract, _ = Hello(calls=0).add_contract_version(package)
    named_keys["hello"] = contract
    named_keys["hello_package"] = package
    named_keys["hello_access"] = access
