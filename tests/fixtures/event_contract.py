"""Typed event records composed across a diamond of contract mixins."""

from casthon import ABIError, Event, Bytesrepr, Json, JsonBytes, MessageEncoder, MessageString, MessageBytes, Key, Map, U32, export
from casthon.contract_api import runtime, storage
from casthon import ces, emit
from casthon.contract_api.runtime import named_keys
from casthon.contracts import Contract, entry_point, export_contract


class Started(Event, Bytesrepr):
    actor: Key


class Added(Started):
    values: Map[str, U32 | None]


class Text(Event, Json):
    value: U32


class Both(Event, Bytesrepr, Json):
    value: U32


class Default(Both):
    def to_message(self) -> MessageString | MessageBytes:
        return Json.to_message(self)


class Utf8(Event, JsonBytes):
    value: U32


class CustomEncoder(MessageEncoder):
    def to_message(self) -> MessageString | MessageBytes:
        return MessageString("custom")


class Custom(Event, CustomEncoder):
    value: U32


class Root(Contract):
    events = (Started,)


class Audit(Root):
    events = (Added,)


class Permissions(Root):
    events = (Started,)


@export_contract
class Events(Audit, Permissions):
    count: U32 = named_keys.property()
    events = (Added,)

    @entry_point
    def add(self, amount: U32) -> Map[str, U32 | None]:
        value = self.count + amount
        self.count = value
        values: Map[str, U32 | None] = {'count': value, 'empty': None}
        ces.emit(Added(runtime.get_caller(), values))
        return values

    @entry_point
    def caught(self) -> U32:
        try:
            ces.emit(Added(runtime.get_caller(), {'bad': -1}))
        except ABIError:
            return self.count
        return 999

    @entry_point
    def undeclared(self) -> bool:
        try:
            ces.emit(Event(), events=Events.event_types())
        except TypeError:
            return True
        return False

    @entry_point
    def messages(self, value: U32) -> None:
        emit(Text(value))
        emit(Both(value), encoder=Bytesrepr.to_message)
        emit(Both(value), encoder=Json.to_message)
        emit(Utf8(value))
        emit(Default(value))
        emit(Custom(value))
        emit(Text(value), topic="audit")

    @entry_point
    def ambiguous(self) -> bool:
        try:
            emit(Both(7))
        except TypeError:
            return True
        return False

    @entry_point
    def invalid_encoder(self) -> bool:
        try:
            emit(Text(7), encoder=lambda event: b"wrong carrier")
        except TypeError:
            return True
        return False

    @entry_point
    def fail(self) -> None:
        self.count = 999
        ces.emit(Added(runtime.get_caller(), {'bad': -1}))


@export
def call() -> None:
    instance = Events(count=0)
    package, access = storage.create_contract_package_at_hash()
    initial_keys = dict(instance.named_keys)
    initial_keys.update(ces.initial_named_keys(Events.event_types()))
    contract, version = storage.add_contract_version(package, Events.entry_points(), initial_keys, ("events", "audit"))
    ces.emit(Started(runtime.get_caller()), named_keys=initial_keys)
    runtime.named_keys['events_contract'] = contract
    runtime.named_keys['events_access'] = access
