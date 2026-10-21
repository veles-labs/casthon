"""Native event inspection; the freezer binds the same schemas statically."""

import inspect
from typing import Any, get_type_hints
from .events import Event, EventSchema, MessageEncoder, Json
from ._contract_schema import annotation_key


def _validate_lookup(owner: type[Event]) -> None:
    import ast
    import textwrap

    order = [base for base in owner.__mro__ if base is not object]
    ignored = {"__dict__", "__weakref__", "__module__", "__doc__", "__qualname__",
               "__annotations__", "__annotate__", "__static_attributes__", "__firstlineno__", "_event_schema"}

    def namespace(base: Any) -> set[str]:
        return set(vars(base)) - ignored

    def dfs(base: Any) -> list[Any]:
        return [base] + [item for parent in base.__bases__ if parent is not object for item in dfs(parent)]

    micro = dfs(owner)
    for name in set().union(*(namespace(base) for base in order)):
        if next((base for base in order if name in namespace(base)), None) is not next((base for base in micro if name in namespace(base)), None):
            raise ValueError("MicroPython event inheritance would resolve differently: " + name)
    for base in order:
        if base in (Event, MessageEncoder, Json) or base.__module__ == "cspr.events":
            continue
        for function in vars(base).values():
            if not inspect.isfunction(function) or "super" not in function.__code__.co_names:
                continue
            tree = ast.parse(textwrap.dedent(inspect.getsource(function)))
            for part in ast.walk(tree):
                if isinstance(part, ast.Attribute) and isinstance(part.value, ast.Call) and isinstance(part.value.func, ast.Name) and part.value.func.id == "super":
                    expected = next((parent for parent in order[order.index(base) + 1:] if part.attr in namespace(parent)), None)
                    actual = next((parent for direct in base.__bases__ if direct is not object for parent in dfs(direct) if part.attr in namespace(parent)), None)
                    if part.value.args or part.value.keywords or expected is not actual:
                        raise ValueError("MicroPython event super() would resolve differently: " + part.attr)


def prepare_event(owner: type[Event]) -> EventSchema:
    _validate_lookup(owner)
    records = []
    encoders: list[type[MessageEncoder]] = []
    for base in owner.__mro__:
        if base in (object, Event, MessageEncoder):
            continue
        if issubclass(base, Event):
            if not base.__bases__ or not issubclass(base.__bases__[0], Event):
                raise TypeError("An event's first base must be its Event record parent")
            if any(issubclass(parent, Event) or not issubclass(parent, MessageEncoder)
                   for parent in base.__bases__[1:]):
                raise TypeError("Event records support one record parent and stateless encoder mixins")
            records.append(base)
        elif issubclass(base, MessageEncoder):
            if "__init__" in vars(base) or inspect.get_annotations(base):
                raise TypeError("Message encoder mixins must be stateless")
            if base.to_message is MessageEncoder.to_message:
                raise TypeError("A message encoder must implement to_message()")
            if not any(issubclass(known, base) for known in encoders):
                encoders.append(base)
        else:
            raise TypeError("Unsupported event base class")
    fields: dict[str, Any] = {}
    for base in reversed(records):
        if "__init__" in vars(base):
            raise TypeError("Event constructors are generated from their annotated fields")
        hints = get_type_hints(base, include_extras=True)
        for name in inspect.get_annotations(base):
            if name == "self" or name.startswith("_") or hasattr(Event, name) or hasattr(Json, name):
                raise TypeError("Reserved event field: " + name)
            if name in vars(base):
                raise TypeError("Event fields require explicit values; defaults are unsupported")
            if name in fields and annotation_key(fields[name]) != annotation_key(hints[name]):
                raise TypeError("Inherited event field types cannot change: " + name)
            fields[name] = hints[name]
    return EventSchema(owner, vars(owner).get("__event_name__", owner.__name__), list(fields.items()), tuple(encoders))
