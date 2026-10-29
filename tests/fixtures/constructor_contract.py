"""Constructor lifecycle probe, compiled by the Wasm test suite."""

from casthon import Dictionary, U32, URef, UserError, export
from casthon.contract_api import storage
from casthon.contract_api.runtime import named_keys
from casthon.contracts import Contract, entry_point, export_contract


class State(Contract):
    value: U32 = named_keys.property()
    items: Dictionary[str, U32] = named_keys.property()

    def __init__(self, initial: U32) -> None:
        super().__init__(value=initial, items={"initial": initial})
        self.value += 1
        self.items["after"] = self.value
        self.temporary = 100


class Example(State):
    def __init__(self, initial: U32) -> None:
        super().__init__(initial)

    @entry_point
    def get(self) -> U32:
        self.temporary = getattr(self, "temporary", 0) + 1
        return self.value + self.temporary

    @entry_point
    def read_new(self, initial: U32) -> U32:
        created = Example(initial)
        if created.items["initial"] != initial or created.items["after"] != initial + 1:
            raise UserError(78)
        return created.value

    @entry_point
    def update(self, value: U32) -> U32:
        previous = URef.of(U32).wrap(self.named_keys["value"])
        old_value = previous.read()
        self.value = value
        if self.named_keys["value"] != previous or previous.read() != value:
            raise UserError(78)
        return old_value

    @entry_point
    def update_new(self, initial: U32) -> U32:
        created = Example(initial)
        previous = URef.of(U32).wrap(created.named_keys["value"])
        created.value = initial + 2
        if created.named_keys["value"] != previous or previous.read() != initial + 2:
            raise UserError(78)
        return created.value


export_contract(Example)


@export
def call(initial: U32) -> None:
    created = Example(initial)
    if created.value != initial + 1:
        raise UserError(78)
    package, access = storage.create_contract_package_at_hash()
    contract, version = package.add_contract_version(created)
    named_keys["py_constructor"] = contract


@export
def fail() -> None:
    created = Example(5)
    try:
        raise UserError(79)
    finally:
        created.value = 99
        created.items["cleanup"] = 1
        print("CONSTRUCTOR_FINALLY")
