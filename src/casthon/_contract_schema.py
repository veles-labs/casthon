"""Native class inspection; replaced by frozen class schemas in Wasm."""

import inspect
from typing import Any, get_type_hints

from .contracts import Contract, EntryPointMethod, Method, Schema, StateConfiguration, StateField, _state_field
from .key import Key, URef
from .references import Dictionary, DictionaryType, URefType
from ._signatures import function_signature
from .types import optional_inner, wire_type, cl_type_of
from .arguments import optional_arg_inner
from ._wire_types import enum_type


def annotation_key(annotation: Any) -> Any:
    presence = optional_arg_inner(annotation)
    if presence is not None:
        return "OptionalArg", annotation_key(presence)
    descriptor = cl_type_of(annotation)
    if descriptor.children:
        return descriptor.tag, tuple(annotation_key(child) for child in descriptor.children)
    enum = enum_type(descriptor.annotation)
    if enum is not None:
        return "Enum", enum.__module__, enum.__name__
    if descriptor.tag == 11:
        return "Key", (descriptor.annotation or Key).__name__
    return descriptor.tag



def state_key(annotation: Any) -> Any:
    if isinstance(annotation, URefType):
        return "URef", annotation_key(annotation.annotation)
    if isinstance(annotation, DictionaryType):
        return "Dictionary", annotation.key_type, annotation_key(annotation.value_type)
    if isinstance(annotation, Dictionary):
        return "Dictionary", annotation._key_type, annotation_key(annotation._value_type)
    if isinstance(annotation, type) and issubclass(annotation, Key):
        return "Key", annotation.__name__
    raise TypeError("Unsupported state annotation")


def signature_key(signature: Any) -> Any:
    parameters, typed, returns = signature
    return tuple((name, annotation_key(annotation)) for name, annotation, default in parameters), typed, annotation_key(returns) if typed else None


def method_key(function: Any, cls: type[Contract]) -> Any:
    bound = function.__get__(object(), cls)
    positional = sum(parameter.kind == parameter.POSITIONAL_OR_KEYWORD
                     for parameter in inspect.signature(bound).parameters.values())
    return signature_key(function_signature(bound)), positional


def validate_inheritance(cls: type[Contract]) -> None:
    import ast
    import textwrap

    mro = [base for base in cls.__mro__ if base is not object]
    if all(len(base.__bases__) <= 1 for base in mro):
        return
    ignored = {"__dict__", "__weakref__", "__module__", "__doc__", "__qualname__", "__annotations__", "__annotate__", "__static_attributes__", "__firstlineno__", "_cspr_schema", "events"}

    def namespace(base: Any) -> set[str]:
        return (set(vars(base)) | set(inspect.get_annotations(base))) - ignored

    def dfs(base: Any) -> list[Any]:
        return [base] + [item for parent in base.__bases__ if parent is not object for item in dfs(parent)]

    depth_first = dfs(cls)
    for name in set().union(*(namespace(base) for base in mro)):
        if next((base for base in mro if name in namespace(base)), None) is not next((base for base in depth_first if name in namespace(base)), None):
            raise ValueError("MicroPython inheritance would resolve differently: " + name)
    for owner in mro:
        if owner is Contract:
            continue
        tree = ast.parse(textwrap.dedent(inspect.getsource(owner)))
        for part in ast.walk(tree):
            if isinstance(part, ast.Attribute) and isinstance(part.value, ast.Call) and isinstance(part.value.func, ast.Name) and part.value.func.id == "super":
                expected = next((base for base in mro[mro.index(owner) + 1:] if part.attr in namespace(base)), None)
                actual = next((base for parent in owner.__bases__ if parent is not object for base in dfs(parent) if part.attr in namespace(base)), None)
                if part.value.args or part.value.keywords or expected is not actual:
                    raise ValueError("MicroPython super() would resolve differently: " + part.attr)


def prepare_class(cls: type[Contract]) -> Schema:
    validate_inheritance(cls)
    fields: dict[str, StateField] = {}
    methods: dict[str, tuple[Any, EntryPointMethod[Any, Any, Any]]] = {}
    for base in reversed(cls.__mro__):
        if base in (object, Contract):
            continue
        own = vars(base)
        hints = get_type_hints(base, include_extras=True)
        state_names = set()
        for name in inspect.get_annotations(base):
            annotation = hints[name]
            configuration = own.get(name)
            if not (isinstance(configuration, (StateConfiguration, StateField)) or
                    isinstance(annotation, (URefType, DictionaryType)) or
                    isinstance(annotation, type) and issubclass(annotation, Key)):
                if name in fields:
                    raise TypeError("An inherited state field cannot be hidden: " + name)
                continue
            if annotation is URef:
                raise TypeError("State URefs require a value type: URef[T]")
            field = configuration if isinstance(configuration, StateField) else _state_field(name, annotation, configuration)
            if name in fields and (fields[name].name != field.name or
                                   field.value_property != fields[name].value_property or
                                   state_key(field.annotation) != state_key(fields[name].annotation)):
                raise TypeError("Inherited state schemas cannot be changed")
            fields[name] = field
            state_names.add(name)
            setattr(base, name, field)
        for name, value in list(own.items()):
            if isinstance(value, StateConfiguration) and value.value_property and name not in state_names:
                raise TypeError("State properties require a value annotation: " + name)
            if name in fields and name not in state_names:
                raise TypeError("An inherited state field cannot be hidden: " + name)
            if name in methods and not isinstance(value, EntryPointMethod) and not inspect.isfunction(value):
                raise ValueError("An inherited entrypoint must remain an instance method: " + name)
            if isinstance(value, EntryPointMethod):
                if name in methods and method_key(value.function, cls) != method_key(methods[name][0], cls):
                    raise ValueError("An inherited entrypoint cannot change its wire signature: " + name)
                methods[name] = (value.function, value)
            elif inspect.isfunction(value) and name in methods:
                previous = methods[name][1]
                if method_key(value, cls) != method_key(methods[name][0], cls):
                    raise ValueError("An inherited entrypoint cannot change its wire signature: " + name)
                descriptor: EntryPointMethod[Any, Any, Any] = EntryPointMethod(value, previous.name, previous.access, previous.groups,
                                              previous.entry_point_type, previous.payment)
                descriptor.__set_name__(base, name)
                setattr(base, name, descriptor)
                methods[name] = (value, descriptor)
    if set(fields) & set(methods):
        raise ValueError("State fields and entrypoints cannot share an attribute")
    names = [field.name for field in fields.values()]
    if len(set(names)) != len(names):
        raise TypeError("Different state fields use the same named key")
    entries = []
    for name, (function, marker) in methods.items():
        # Inspect a bound method to remove self without constructing a contract.
        raw = inspect.signature(function)
        parameters = list(raw.parameters.values())
        if not parameters or parameters[0].name != "self":
            raise ValueError("Entrypoint methods require self as their first parameter")
        bound = function.__get__(object(), cls)
        signature = function_signature(bound)
        positional = sum(parameter.kind == parameter.POSITIONAL_OR_KEYWORD for parameter in parameters[1:])
        method = Method(marker.name or name, name, signature, positional,
                        marker.access, marker.groups, marker.entry_point_type, marker.payment)
        method.entry_point()
        entries.append(method)
    if len({method.name for method in entries}) != len(entries):
        raise ValueError("Duplicate class entrypoint name")
    from .events import event_types
    events = event_types(vars(base).get("events", ()) for base in reversed(cls.__mro__) if base is not object)
    return Schema(cls, list(fields.values()), entries, events)
