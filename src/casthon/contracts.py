"""Class contracts: lazy annotated state, ordinary local calls and explicit exports."""

from __future__ import annotations

from typing import Any, Callable, Concatenate, Generic, Mapping, ParamSpec, TypeVar, ClassVar, cast, overload

from .enums import EntryPointAccess, EntryPointPayment, EntryPointType
from .key import Key
from .references import Dictionary, DictionaryType, URefType, reference
from .return_value import _validate_value, typed_value
from .arguments import argument_in_abi, argument_type
from .events import Event

_C = TypeVar("_C")
_P = ParamSpec("_P")
_R = TypeVar("_R")
_Contract = TypeVar("_Contract", bound="Contract")


class StateConfiguration:
    """Optional storage name and dictionary key transform for an annotated field."""

    def __init__(self, name: str | None = None, key: Callable[..., str] | None = None) -> None:
        self.name, self.key = name, key


class StateField:
    def __init__(self, attribute: str, name: str, annotation: Any, binding: Any) -> None:
        self.attribute, self.name = attribute, name
        self.annotation, self.reference = annotation, binding

    def __get__(self, instance: Any, owner: Any = None) -> Any:
        if instance is None:
            return self
        references = instance._state_references
        binding = self.reference if references is None else references[self.attribute]
        if isinstance(self.annotation, Dictionary):
            return binding
        return binding.get()

    def __set__(self, instance: Any, value: Any) -> None:
        raise TypeError("Use URef.write(), dictionary items or named_keys to update state")

    def validate(self, value: Any) -> None:
        if isinstance(self.annotation, URefType):
            typed_value(self.annotation.annotation, value)
        elif isinstance(self.annotation, Dictionary):
            if not isinstance(value, dict):
                raise TypeError("Initial dictionary values must be a dict")
            for key, item in value.items():
                self.annotation._item(key)
                typed_value(self.annotation._value_type, item)
        else:
            _validate_value(self.annotation, value)

    def create(self, value: Any) -> Key:
        if isinstance(self.annotation, URefType):
            return self.annotation.create(value)
        if isinstance(self.annotation, Dictionary):
            from .contract_api.storage import new_dictionary_seed

            seed = new_dictionary_seed()
            dictionary = self.annotation._bind(seed)
            for key, item in value.items():
                # A direct Python call avoids retaining a native subscription
                # frame while the constructor is already on the Wasm stack.
                dictionary.__setitem__(key, item)
            return seed
        return value  # type: ignore[no-any-return]


def _state_field(attribute: str, annotation: Any, configuration: Any = None) -> StateField:
    from .contract_api.runtime import named_keys

    if configuration is not None and not isinstance(configuration, StateConfiguration):
        raise TypeError("Annotated storage fields only accept named_keys.reference(...) configuration")
    name = configuration.name if configuration is not None and configuration.name is not None else attribute
    key = configuration.key if configuration is not None else None
    if not isinstance(name, str) or not name:
        raise TypeError("A state field requires a nonempty storage name")
    if isinstance(annotation, DictionaryType):
        annotation = annotation(key=key)
    elif key is not None:
        raise TypeError("key= is only valid for dictionary state")
    binding = reference(named_keys, name, annotation)
    return StateField(attribute, name, annotation, binding)


class EntryPointReference(Generic[_P, _R]):
    """Class-level ABI reference; self is absent from its public call signature."""

    def __init__(self, owner: type[Contract], attribute: str) -> None:
        self.owner, self.attribute = owner, attribute

    def describe(self) -> Any:
        method = _schema(self.owner).method(self.attribute)
        parameters, typed, returns = method.signature
        return [method.name], parameters, typed, returns, method.positional

    def __call__(self, *args: _P.args, **kwargs: _P.kwargs) -> _R:
        raise TypeError("Call an entrypoint on an instance or through ContractHash.call()")


class BoundEntryPoint:
    def __init__(self, instance: Contract, method: EntryPointMethod[Any, Any, Any]) -> None:
        self.instance, self.method = instance, method

    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        return self.method.function(self.instance, *args, **kwargs)

    def describe(self) -> Any:
        return EntryPointReference(type(self.instance), self.method.attribute).describe()


class EntryPointMethod(Generic[_C, _P, _R]):
    def __init__(self, function: Callable[..., Any], name: str | None = None,
                 access: EntryPointAccess = EntryPointAccess.PUBLIC, groups: tuple[str, ...] = (),
                 entry_point_type: EntryPointType = EntryPointType.CALLED,
                 payment: EntryPointPayment = EntryPointPayment.CALLER) -> None:
        self.function, self.name = function, name
        self.access, self.groups = access, groups
        self.entry_point_type, self.payment = entry_point_type, payment
        self.attribute = ""

    def __set_name__(self, owner: Any, name: str) -> None:
        self.attribute = name

    @overload
    def __get__(self, instance: None, owner: type[_C]) -> EntryPointReference[_P, _R]: ...

    @overload
    def __get__(self, instance: _C, owner: type[_C] | None = None) -> Callable[_P, _R]: ...

    def __get__(self, instance: Any, owner: Any = None) -> Any:
        if instance is None:
            return EntryPointReference(owner, self.attribute)
        return BoundEntryPoint(instance, self)


@overload
def entry_point(function: Callable[Concatenate[_C, _P], _R]) -> EntryPointMethod[_C, _P, _R]: ...

@overload
def entry_point(*, name: str | None = None, access: EntryPointAccess = EntryPointAccess.PUBLIC,
                groups: tuple[str, ...] = (), entry_point_type: EntryPointType = EntryPointType.CALLED,
                payment: EntryPointPayment = EntryPointPayment.CALLER
                ) -> Callable[[Callable[Concatenate[_C, _P], _R]], EntryPointMethod[_C, _P, _R]]: ...

def entry_point(function: Any = None, *, name: str | None = None,
                access: EntryPointAccess = EntryPointAccess.PUBLIC, groups: tuple[str, ...] = (),
                entry_point_type: EntryPointType = EntryPointType.CALLED,
                payment: EntryPointPayment = EntryPointPayment.CALLER) -> Any:
    def decorate(function: Any) -> Any:
        return EntryPointMethod(function, name, access, groups, entry_point_type, payment)
    return decorate(function) if function is not None else decorate


class Method:
    def __init__(self, name: str, attribute: str, signature: Any, positional: int,
                 access: Any = EntryPointAccess.PUBLIC, groups: tuple[str, ...] = (),
                 entry_point_type: Any = EntryPointType.CALLED,
                 payment: Any = EntryPointPayment.CALLER) -> None:
        self.name, self.attribute = name, attribute
        self.signature, self.positional = signature, positional
        self.access, self.groups = access, groups
        self.entry_point_type, self.payment = entry_point_type, payment

    def entry_point(self) -> Any:
        from .entry_points import EntryPoint
        parameters, typed, returns = self.signature
        if not typed:
            raise ValueError("Class entrypoints require a wire return annotation, including -> None")
        return EntryPoint(self.name, [(name, argument_type(annotation)) for name, annotation, default in parameters
                                     if argument_in_abi(annotation)], returns,
                          access=self.access, groups=self.groups, entry_point_type=self.entry_point_type,
                          payment=self.payment)


class Schema:
    def __init__(self, owner: type[Contract], fields: list[StateField], methods: list[Method], events: tuple[type[Event], ...] = ()) -> None:
        self.owner, self.fields, self.methods = owner, fields, methods
        self.events = events

    def method(self, attribute: str) -> Method:
        for method in self.methods:
            if method.attribute == attribute:
                return method
        raise ValueError("Method is not a declared entrypoint: " + attribute)


def _schema(cls: type[Contract]) -> Schema:
    existing = getattr(cls, "_cspr_schema", None)
    if existing is not None and existing.owner is cls:
        return existing  # type: ignore[no-any-return]
    from ._contract_schema import prepare_class
    schema = prepare_class(cls)
    cls._cspr_schema = schema
    return schema


class Contract:
    events: ClassVar[tuple[type[Event], ...]] = ()
    _cspr_schema: Any = None

    def __init__(self, **values: Any) -> None:
        """Create fresh state without binding its names into the current account."""
        fields = _schema(type(self)).fields
        for name in values:
            if not any(field.attribute == name for field in fields):
                raise TypeError("Unknown state field: " + name)
        initial = {}
        for field in fields:
            if field.attribute in values:
                value = values[field.attribute]
            elif isinstance(field.annotation, Dictionary):
                value = {}
            else:
                raise TypeError("Missing initial value for state field: " + field.attribute)
            field.validate(value)
            initial[field.attribute] = value
        # Avoid retaining a comprehension VM frame across storage allocation.
        self._named_keys: Any = {}
        for field in fields:
            self._named_keys[field.name] = field.create(initial[field.attribute])
        self._state_references: Any = {
            field.attribute: reference(cast(Any, self._named_keys), field.name, field.annotation) for field in fields}

    @classmethod
    def bind(cls: type[_Contract]) -> _Contract:
        """Bind existing state in the current context without running __init__."""
        from .contract_api.runtime import named_keys

        _schema(cls)
        instance = object.__new__(cls)
        instance._named_keys = named_keys
        instance._state_references = None
        return instance

    @property
    def named_keys(self) -> Mapping[str, Key]:
        """The new instance's state keys, or the current context for a bound view."""
        return self._named_keys  # type: ignore[no-any-return]

    @classmethod
    def entry_points(cls) -> Any:
        return [method.entry_point() for method in _schema(cls).methods]

    @classmethod
    def event_types(cls) -> tuple[type[Event], ...]:
        return _schema(cls).events


def export_contract(cls: type[_Contract]) -> type[_Contract]:
    """Select a concrete class's entrypoints as root Wasm exports."""
    return cls
