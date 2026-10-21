"""Constructor lifecycle probe, compiled by the Wasm test suite."""

from cspr import Dictionary, U32, URef, UserError, export
from cspr.contract_api import storage
from cspr.contract_api.runtime import named_keys
from cspr.contracts import Contract, entry_point, export_contract


class State(Contract):
    value: URef[U32]
    items: Dictionary[str, U32]

    def __init__(self, initial: U32) -> None:
        super().__init__(value=initial, items={"initial": initial})
        self.value.write(self.value.read() + 1)
        self.items["after"] = self.value.read()
        self.temporary = 100


class Example(State):
    def __init__(self, initial: U32) -> None:
        super().__init__(initial)

    @entry_point
    def get(self) -> U32:
        self.temporary = getattr(self, "temporary", 0) + 1
        return self.value.read() + self.temporary

    @entry_point
    def read_new(self, initial: U32) -> U32:
        created = Example(initial)
        if created.items["initial"] != initial or created.items["after"] != initial + 1:
            raise UserError(78)
        return created.value.read()

    @entry_point
    def update(self, value: U32) -> U32:
        previous = self.value
        old_value = previous.read()
        self.value.write(value)
        if self.value != previous or previous.read() != value:
            raise UserError(78)
        return old_value

    @entry_point
    def update_new(self, initial: U32) -> U32:
        created = Example(initial)
        previous = created.value
        created.value.write(initial + 2)
        if created.value != previous or previous.read() != initial + 2:
            raise UserError(78)
        return created.value.read()


export_contract(Example)


@export
def call(initial: U32) -> None:
    created = Example(initial)
    if created.value.read() != initial + 1:
        raise UserError(78)
    package, access = storage.create_contract_package_at_hash()
    contract, version = created.add_contract_version(package)
    named_keys["py_constructor"] = contract


@export
def fail() -> None:
    created = Example(5)
    try:
        raise UserError(79)
    finally:
        created.value.write(99)
        created.items["cleanup"] = 1
        print("CONSTRUCTOR_FINALLY")
