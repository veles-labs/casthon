"""Typed event records and casper-event-standard schemas."""

from __future__ import annotations

from typing import Any, Callable, TypeVar, cast, dataclass_transform
from .codec import encode, validate
from .types import cl_type_of
from ._cl_types import CLType
from .values import SerializedCLValue
from .messages import MessageString, MessageBytes

_Event = TypeVar("_Event", bound="Event")


class EventSchema:
    def __init__(self, owner: type[Event], name: str, fields: list[tuple[str, Any]],
                 encoders: tuple[type[MessageEncoder], ...] = ()) -> None:
        if not name or type(name) is not str:
            raise TypeError("An event requires a nonempty wire name")
        self.owner, self.name = owner, name
        self.encoders = encoders
        self.encoder: Callable[[Any], MessageString | MessageBytes] | None = encoders[0].to_message if len(encoders) == 1 else None
        self.fields = []
        for field, annotation in fields:
            self.fields.append((field, cl_type_of(annotation)))


def _bind_event(owner: type[Event], name: str, fields: list[tuple[str, Any]],
                encoders: tuple[type[MessageEncoder], ...] = ()) -> None:
    owner._event_schema = EventSchema(owner, name, fields, encoders)


def _encoder(module: str, name: str) -> Any:
    # Frozen references resolve modules already imported by the class's bases.
    import sys
    return getattr(sys.modules[module], name)


def event_schema(owner: type[Event]) -> EventSchema:
    if owner is Event:
        return EventSchema(Event, "Event", [])
    schema = owner._event_schema
    if schema is None or schema.owner is not owner:
        from ._event_schema import prepare_event
        schema = prepare_event(owner)
        owner._event_schema = schema
    return cast(EventSchema, schema)


def event_types(declarations: Any) -> tuple[type[Event], ...]:
    result = []
    names: dict[str, type[Event]] = {}
    for declaration in declarations:
        if type(declaration) is not tuple:
            raise TypeError("Contract events must be declared as a tuple of Event classes")
        for owner in declaration:
            if not isinstance(owner, type) or owner is Event or not issubclass(owner, Event):
                raise TypeError("Contract events must contain Event subclasses")
            schema = event_schema(owner)
            if schema.name in names and names[schema.name] is not owner:
                raise ValueError("Different event classes share a wire name: " + schema.name)
            if owner not in result:
                names[schema.name] = owner
                result.append(owner)
    return tuple(result)


@dataclass_transform()
class Event:
    """An annotated record. Constructing it does not emit an event or access state."""

    _event_schema: Any = None

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        fields = event_schema(type(self)).fields
        if len(args) > len(fields):
            raise TypeError("Too many event arguments")
        names = [name for name, annotation in fields]
        if any(name not in names for name in kwargs):
            raise TypeError("Unknown event field")
        for index, name in enumerate(names):
            if index < len(args):
                if name in kwargs:
                    raise TypeError("Multiple values for event field: " + name)
                value = args[index]
            elif name in kwargs:
                value = kwargs[name]
            else:
                raise TypeError("Missing event field: " + name)
            setattr(self, name, value)

    def validate(self) -> None:
        for name, annotation in event_schema(type(self)).fields:
            validate(annotation, getattr(self, name))

    def to_message(self) -> MessageString | MessageBytes:
        """Use an explicit encoder, or default a plain record to Bytesrepr."""
        schema = event_schema(type(self))
        if schema.encoder is None:
            if schema.encoders:
                raise TypeError("Multiple event encoders; select Encoder.to_message(event) or define a default")
            if type(self) is Event:
                raise TypeError("Event has no message encoder")
            message = Bytesrepr.to_message(self)
        else:
            message = schema.encoder(self)
        if not isinstance(message, (MessageString, MessageBytes)):
            raise TypeError("An event encoder must return MessageString or MessageBytes")
        return message

    def __eq__(self, other: object) -> bool:
        return type(self) is type(other) and all(getattr(self, name) == getattr(other, name)
                                               for name, annotation in event_schema(type(self)).fields)

    def __repr__(self) -> str:
        return type(self).__name__ + "(" + ", ".join(name + "=" + repr(getattr(self, name))
            for name, annotation in event_schema(type(self)).fields) + ")"


class MessageEncoder:
    """A stateless event encoding mixin; delivery belongs to the caller."""

    def to_message(self) -> MessageString | MessageBytes:
        raise NotImplementedError("An encoder must implement to_message()")


def _record(value: object) -> Event:
    if not isinstance(value, Event):
        raise TypeError("Message encoders require an Event record")
    return value


class Bytesrepr(MessageEncoder):
    """Encode fields in declaration order, without an event envelope."""

    def to_message(self: object) -> MessageString | MessageBytes:
        record = _record(self)
        data = b""
        for name, annotation in event_schema(type(record)).fields:
            data += encode(annotation, getattr(record, name))
        return MessageBytes(data)


class Json(MessageEncoder):
    def json_field(self, name: str, annotation: CLType, value: Any) -> str:
        """Customize a field's JSON representation without changing its CL schema."""
        return json_value(annotation, value)

    def to_message(self) -> MessageString | MessageBytes:
        record = _record(self)
        parts = []
        json_field = getattr(type(self), "json_field", Json.json_field)
        for name, annotation in event_schema(type(record)).fields:
            value = getattr(record, name)
            validate(annotation, value)
            parts.append(json_string(name) + ":" + json_field(self, name, annotation, value))
        return MessageString("{" + ",".join(parts) + "}")


class JsonBytes(Json):
    """JSON carried as UTF-8 MessageBytes, as used by CEP-18."""

    def to_message(self) -> MessageString | MessageBytes:
        message = Json.to_message(self)
        if not isinstance(message, MessageString):
            raise TypeError("JSON text encoder must return MessageString")
        return MessageBytes(message.value.encode("utf-8"))


def emit(event: _Event, *, topic: str = "events",
         encoder: Callable[[_Event], MessageString | MessageBytes] | None = None) -> None:
    """Encode an event and emit it on the supplied Casper message topic."""
    from .contract_api import runtime

    if not topic:
        raise ValueError("Message topic must not be empty")
    if not isinstance(event, Event):
        raise TypeError("Expected Event instance")
    message = event.to_message() if encoder is None else encoder(event)
    if not isinstance(message, (MessageString, MessageBytes)):
        raise TypeError("Event encoder must return MessageString or MessageBytes")
    runtime.emit_message(topic, message)


def json_string(value: str) -> str:
    text = '"'
    for char in value:
        code = ord(char)
        if char == '"' or char == "\\":
            text += "\\" + char
        elif code < 32:
            text += "\\u" + ("0000" + hex(code)[2:])[-4:]
        else:
            text += char
    return text + '"'


def json_value(kind: CLType, value: Any) -> str:
    tag = kind.tag
    if tag == 13:
        return "null" if value is None else json_value(kind.children[0], value)
    if tag == 9:
        return "null"
    if tag == 0:
        return "true" if value else "false"
    if tag in (7, 8, 10, 11):
        return json_string(str(value))
    if tag in (3, 4, 5):
        return str(int(value))
    if tag == 14:
        return "[" + ",".join(json_value(kind.children[0], item) for item in value) + "]"
    if tag == 17:
        return "{" + ",".join(json_string(str(key)) + ":" + json_value(kind.children[1], item)
                               for key, item in sorted(value.items())) + "}"
    raise TypeError("Unsupported JSON event field")


def event_schemas(owners: tuple[type[Event], ...]) -> SerializedCLValue:
    """CES Schemas: Map<String, List<Tuple2<String, Any>>> containing CLType bytes."""
    schemas = sorted((event_schema(owner).name, event_schema(owner)) for owner in event_types((owners,)))
    data = encode("U32", len(schemas))
    for name, schema in schemas:
        data += encode(str, name) + encode("U32", len(schema.fields))
        for field, annotation in schema.fields:
            data += encode(str, field) + annotation.to_bytes()
    return SerializedCLValue(encode("U32", len(data)) + data + b"\x11\x0a\x0e\x13\x0a\x15")
