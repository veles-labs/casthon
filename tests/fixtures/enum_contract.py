"""Probe typed enum state and calls without changing CEP-18's stored ABI."""

from typing import Any, Optional

from cspr import ContractHash, Dictionary, MISSING, OptionalArg, URef, WireEnum, export
from cspr.contract_api import runtime, storage
from cspr.contracts import Contract, entry_point, export_contract
from contracts.cep18_events import EventsMode


class LocalMode(WireEnum):
    OFF = 0
    ON = 1


@export
def local(mode: LocalMode) -> LocalMode:
    assert mode is LocalMode.from_value(int(mode))
    return mode


@export_contract
class Modes(Contract):
    mode: URef[EventsMode]
    previous: Dictionary[str, EventsMode]
    nullable: URef[Optional[EventsMode]]

    def __init__(self, **state: Any) -> None:
        super().__init__(mode=EventsMode.CES, nullable=None, **state)

    @entry_point
    def get(self) -> EventsMode:
        mode = self.mode.read()
        assert isinstance(mode, EventsMode)
        assert mode is EventsMode.from_value(int(mode))
        return mode

    @entry_point
    def set(self, mode: EventsMode) -> EventsMode:
        old = self.mode.read()
        self.previous["last"] = old
        self.mode.write(mode)
        assert self.mode.read() is mode
        assert self.previous["last"] is old
        return old

    @entry_point
    def optional(self, mode: OptionalArg[Optional[EventsMode]] = MISSING) -> Optional[EventsMode]:
        if mode is MISSING:
            return self.nullable.read()
        self.nullable.write(mode)
        assert self.nullable.read() is mode
        return mode


@export
def call(contract: OptionalArg[ContractHash] = MISSING) -> None:
    if contract is MISSING:
        instance = Modes()
        package, access = storage.create_contract_package_at_hash()
        deployed, version = package.add_contract_version(instance)
        runtime.named_keys["py_modes"] = deployed
        runtime.named_keys["py_modes_access"] = access
        return
    assert contract.call(Modes.get) is EventsMode.CES
    assert contract.call(Modes.set, EventsMode.NATIVE) is EventsMode.CES
    assert contract.call(Modes.get) is EventsMode.NATIVE
    assert contract.call(Modes.optional) is None
    assert contract.call(Modes.optional, EventsMode.NATIVE_BYTES) is EventsMode.NATIVE_BYTES
    assert contract.call(Modes.optional) is EventsMode.NATIVE_BYTES
    assert contract.call(Modes.optional, None) is None
