# SPDX-License-Identifier: Apache-2.0
"""CEP-78 events, with explicit CES, CEP47 and native message policies."""

from cspr import Bytesrepr, CLType, CLValue, Event, Json, JsonBytes, Key, Map, U64, URef, ces
from cspr.contract_api import runtime, storage
from cspr.events import emit as emit_event, event_schema
from contracts.cep78_modalities import EventsMode
from contracts.cep78_metadata import json_string


class Cep78Event(Event, Bytesrepr, JsonBytes):
    def json_field(self, name: str, annotation: CLType, value: object) -> str:
        if annotation.tag == 10 and isinstance(value, str):
            return json_string(value)
        return super().json_field(name, annotation, value)


class Mint(Cep78Event):
    recipient: Key
    token_id: str
    data: str


class Burn(Cep78Event):
    owner: Key
    token_id: str
    burner: Key


class Approval(Cep78Event):
    owner: Key
    spender: Key
    token_id: str


class ApprovalRevoked(Cep78Event):
    owner: Key
    token_id: str


class ApprovalForAll(Cep78Event):
    owner: Key
    operator: Key


class RevokedForAll(ApprovalForAll):
    pass


class Transfer(Cep78Event):
    owner: Key
    spender: Key | None
    recipient: Key
    token_id: str


class MetadataUpdated(Cep78Event):
    token_id: str
    data: str


class VariablesSet(Cep78Event):
    pass


class Migration(Cep78Event):
    pass


def initialize_events(events: tuple[type[Event], ...]) -> None:
    if _mode() is EventsMode.CES:
        ces.initialize(events)


def _mode() -> EventsMode:
    key = runtime.named_keys["events_mode"]
    if not isinstance(key, URef):
        raise TypeError("events_mode must be a URef")
    return storage.read_or_revert(key, EventsMode)  # type: ignore[no-any-return]


def emit(event: Cep78Event) -> None:
    mode = _mode()
    if mode is EventsMode.CES:
        ces.emit(event)
    elif mode is EventsMode.NATIVE:
        emit_event(event, encoder=Json.to_message)
    elif mode is EventsMode.NATIVE_BYTES:
        emit_event(event, encoder=JsonBytes.to_message)
    elif mode is EventsMode.CEP47:
        _emit_cep47(event)
    else:
        event.validate()


def _emit_cep47(event: Cep78Event) -> None:
    event.validate()
    collection = runtime.named_keys.reference("collection_name", URef[str]).read()
    package = runtime.named_keys.reference("cep78_" + collection, URef[str]).read()
    name = event_schema(type(event)).name
    record = {"cep78_contract_package": package,
              "event_type": {"Approval": "Approve", "MetadataUpdated": "MetadataUpdate"}.get(name, name)}
    if isinstance(event, Transfer):
        record["sender"] = str(event.spender if event.spender is not None else event.owner)
        record["recipient"] = str(event.recipient)
        record["token_id"] = event.token_id
    else:
        for field, _ in event_schema(type(event)).fields:
            if field != "data":
                record[field] = str(getattr(event, field))
    # CEP47 keeps maps and its U64 length in one dictionary, so its schema is
    # deliberately handled here rather than as homogeneous Dictionary state.
    seed = runtime.named_keys.get("events")
    if seed is None:
        seed = storage.new_dictionary("events")
    if not isinstance(seed, URef):
        raise TypeError("events must be a dictionary seed")
    length = storage.dictionary_get(seed, "len", U64, default=0)
    storage.dictionary_put(seed, str(length), CLValue(Map[str, str], record))
    storage.dictionary_put(seed, "len", CLValue(U64, length + 1))
