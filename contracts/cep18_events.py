# SPDX-License-Identifier: Apache-2.0
"""CEP-18 2.0.0 events and casper-event-standard 0.7.0 storage layouts."""

from casthon import Event, Bytesrepr, Json, JsonBytes, Key, Map, U8, U256, URef, CLType
from casthon import ces
from casthon.contract_api import runtime, storage
from casthon.events import emit as emit_event, json_string
from casthon.enums import WireEnum
from contracts.cep18_errors import InvalidEventsMode


class EventsMode(WireEnum):
    NO_EVENTS = 0
    CES = 1
    NATIVE = 2
    NATIVE_BYTES = 3

    @classmethod
    def _missing_(cls, value: object) -> None:
        raise InvalidEventsMode()


class Cep18Event(Event, Bytesrepr, JsonBytes):
    pass


class Mint(Cep18Event):
    recipient: Key
    amount: U256


class Burn(Cep18Event):
    owner: Key
    amount: U256


class SetAllowance(Cep18Event):
    owner: Key
    spender: Key
    allowance: U256


class IncreaseAllowance(SetAllowance):
    inc_by: U256


class DecreaseAllowance(SetAllowance):
    decr_by: U256


class Transfer(Cep18Event):
    sender: Key
    recipient: Key
    amount: U256


class TransferFrom(Cep18Event):
    spender: Key
    owner: Key
    recipient: Key
    amount: U256


class ChangeSecurity(Cep18Event):
    admin: Key
    sec_change_map: Map[Key, U8]

    def json_field(self, name: str, annotation: CLType, value: object) -> str:
        if name == "sec_change_map":
            # Upstream's JSON uses SecurityBadge variant names; its CL schema is U8.
            return "{" + ",".join(json_string(str(key)) + ":" + json_string(("Admin", "Minter", "None")[badge])
                                   for key, badge in sorted(self.sec_change_map.items())) + "}"
        return super().json_field(name, annotation, value)


class ChangeEventsMode(Cep18Event):
    events_mode: EventsMode


def initialize_events(events: tuple[type[Event], ...]) -> None:
    if _mode() is EventsMode.CES:
        ces.initialize(events)


def _mode() -> EventsMode:
    key = runtime.named_keys["events_mode"]
    if not isinstance(key, URef):
        raise TypeError("events_mode must be a URef")
    return storage.read_or_revert(key, EventsMode)  # type: ignore[no-any-return]


def emit(event: Cep18Event) -> None:
    """CEP-18's mode policy; carrier choice and JSON conventions stay here."""
    mode = _mode()
    if mode is EventsMode.CES:
        ces.emit(event)
    elif mode is EventsMode.NATIVE:
        emit_event(event, encoder=Json.to_message)
    elif mode is EventsMode.NATIVE_BYTES:
        emit_event(event, encoder=JsonBytes.to_message)
    else:
        event.validate()
