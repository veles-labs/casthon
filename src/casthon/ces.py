"""Explicit casper-event-standard storage and event envelopes."""

from typing import Mapping, Any
from .events import Event, Bytesrepr, event_schema, event_schemas
from .messages import MessageBytes
from .codec import encode
from .key import Key, URef
from .values import CLBytes, CLString, CLU32


def initial_named_keys(events: tuple[type[Event], ...]) -> dict[str, Key]:
    """Create CES state without binding it into the current account or contract."""
    from .contract_api import storage
    return {
        "__events": storage.new_dictionary_seed(),
        "__events_length": storage.new_uref(CLU32(0)),
        "__events_schema": storage.new_uref(event_schemas(events)),
        "__events_ces_version": storage.new_uref(CLString("1.1")),
    }


def initialize(events: tuple[type[Event], ...]) -> None:
    """Initialize CES once in the current stored-contract context."""
    from .contract_api.runtime import named_keys
    if "__events" not in named_keys:
        for name, key in initial_named_keys(events).items():
            named_keys[name] = key


def emit(event: Event, *, events: tuple[type[Event], ...] | None = None,
         named_keys: Mapping[str, Key] | None = None) -> None:
    """Write a CES envelope; optionally enforce an explicit event registry."""
    from .contract_api import runtime, storage
    if events is not None and type(event) not in events:
        raise TypeError("Event is not declared in the supplied CES registry")
    if not isinstance(event, Event) or type(event) is Event:
        raise TypeError("CES events require an Event record")
    message = Bytesrepr.to_message(event)
    if not isinstance(message, MessageBytes):
        raise TypeError("CES requires bytesrepr MessageBytes")
    data = encode(str, "event_" + event_schema(type(event)).name) + message.value
    keys: Any = runtime.named_keys if named_keys is None else named_keys
    seed, length = keys["__events"], keys["__events_length"]
    if not isinstance(seed, URef) or not isinstance(length, URef):
        raise TypeError("CES storage requires URefs")
    index = storage.read_or_revert(length, "U32")
    storage.dictionary_put(seed, str(index), CLBytes(data))
    storage.write(length, CLU32((index + 1) & 0xFFFFFFFF))
