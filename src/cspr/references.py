"""Typed URef values, dictionary views and lazy named-key references."""

from __future__ import annotations

from typing import Any, Callable, Generic, Iterator, TypeVar, TYPE_CHECKING, cast, overload

from .codec import encode
from .errors import InvalidArgument, MissingKey
from .key import Key, URef
from .return_value import _validate_value, typed_value as _value
from .types import cl_type_of
from .values import CLValue

if TYPE_CHECKING:
    from .contract_api.runtime import NamedKeys

_V = TypeVar("_V")
_K = TypeVar("_K")
_R = TypeVar("_R")
_D = TypeVar("_D")
_UNSET = object()


class URefType(Generic[_V]):
    """Runtime schema produced by URef[T]; constructing it performs no I/O."""

    def __init__(self, annotation: Any) -> None:
        cl_type_of(annotation)
        self.annotation = annotation

    def wrap(self, key: Key) -> URef[_V]:
        if not isinstance(key, URef):
            raise InvalidArgument()
        result: URef[_V] = URef(bytes(key))
        result._value_type = self.annotation
        return result

    def create(self, value: _V | CLValue) -> URef[_V]:
        from .contract_api import storage
        return self.wrap(storage.new_uref(_value(self.annotation, value)))


def _identity(value: str) -> str:
    return value


def _check_item_type(annotation: Any, value: Any) -> None:
    if isinstance(annotation, type):
        if annotation in (int, bool, str, bytes):
            valid = type(value) is annotation
        else:
            valid = isinstance(value, annotation)
        if not valid:
            raise TypeError("Dictionary key does not match its declared type")
    else:
        # Annotated unsigned integers and frozen wire descriptors.
        encode(annotation, value)


class DictionaryType(Generic[_K, _V]):
    def __init__(self, key_type: Any, value_type: Any) -> None:
        cl_type_of(value_type)
        if not isinstance(key_type, type):
            cl_type_of(key_type)
        self.key_type, self.value_type = key_type, value_type

    def __call__(self, *, key: Callable[[_K], str] | None = None,
                 seed: URef | None = None) -> Dictionary[_K, _V]:
        return Dictionary(key=key, seed=seed, _key_type=self.key_type,
                          _value_type=self.value_type)


class Dictionary(Generic[_K, _V]):
    """Dictionary schema, or a typed view when supplied with a seed URef."""

    @classmethod
    def __class_getitem__(cls, parameters: Any) -> Any:
        if not isinstance(parameters, tuple) or len(parameters) != 2:
            raise TypeError("Use Dictionary[K, V]")
        if any(isinstance(parameter, TypeVar) for parameter in parameters):
            return cast(Any, super()).__class_getitem__(parameters)
        return cls.of(parameters[0], parameters[1])

    @classmethod
    def of(cls, key_type: type[_K], value_type: type[_V]) -> DictionaryType[_K, _V]:
        return DictionaryType(key_type, value_type)

    def __init__(self, *, key: Callable[[_K], str] | None = None,
                 seed: URef | None = None, _key_type: Any = _UNSET,
                 _value_type: Any = _UNSET) -> None:
        if _key_type is _UNSET or _value_type is _UNSET:
            raise TypeError("Use Dictionary[K, V] to declare key and value types")
        if key is None:
            if _key_type is not str:
                raise TypeError("A non-string dictionary key requires key=callable")
            key = cast(Callable[[_K], str], _identity)
        if not callable(key):
            raise TypeError("Dictionary key transform must be callable")
        if seed is not None and not isinstance(seed, URef):
            raise TypeError("Expected a dictionary seed URef")
        self._key_type, self._value_type = _key_type, _value_type
        self._key_transform, self._seed = key, seed

    @property
    def seed(self) -> URef:
        if self._seed is None:
            raise ValueError("Resolve the named-key reference before accessing dictionary items")
        return self._seed

    def _bind(self, seed: URef) -> Dictionary[_K, _V]:
        return Dictionary(key=self._key_transform, seed=seed, _key_type=self._key_type,
                          _value_type=self._value_type)

    def _item(self, key: _K) -> str:
        _check_item_type(self._key_type, key)
        item = self._key_transform(key)
        if not isinstance(item, str):
            raise TypeError("Dictionary key transform must return a string")
        return item

    def __getitem__(self, key: _K) -> _V:
        from .contract_api import storage
        value = storage.dictionary_get(self.seed, self._item(key), self._value_type,
                                       default=_UNSET)
        if value is _UNSET:
            raise KeyError(key)
        return cast(_V, value)

    def __setitem__(self, key: _K, value: _V | CLValue) -> None:
        from .contract_api import storage
        storage.dictionary_put(self.seed, self._item(key), _value(self._value_type, value))

    def __contains__(self, key: _K) -> bool:
        from .contract_api import storage
        return storage.dictionary_get(self.seed, self._item(key), self._value_type,
                                      default=_UNSET) is not _UNSET

    def __iter__(self) -> Iterator[_K]:
        raise TypeError("Casper dictionaries do not support item enumeration")

    @overload
    def get(self, key: _K) -> _V | None: ...

    @overload
    def get(self, key: _K, default: _D) -> _V | _D: ...

    def get(self, key: _K, default: _D | None = None) -> _V | _D | None:
        from .contract_api import storage
        return cast(_V | _D | None, storage.dictionary_get(
            self.seed, self._item(key), self._value_type, default=default))


class _NamedKeyBinding:
    """Name, schema and binding operations shared by typed references."""

    def __init__(self, keys: NamedKeys, name: str, annotation: Any) -> None:
        if not isinstance(name, str) or not name:
            raise ValueError("A reference requires a nonempty named-key name")
        self._keys, self._name, self._annotation = keys, name, annotation

    @property
    def name(self) -> str:
        return self._name

    def _key(self) -> Key:
        key = self._keys.get(self._name)
        if key is None:
            raise MissingKey()
        return key

    def remove(self) -> None:
        if self.name in self._keys:
            del self._keys[self.name]


class NamedKeyReference(_NamedKeyBinding, Generic[_R]):
    """A name and key schema; resolve against the current context on each get."""

    def get(self) -> _R:
        key = self._key()
        try:
            _validate_value(self._annotation, key)
        except TypeError:
            raise InvalidArgument()
        return cast(_R, key if self._annotation is Key else self._annotation(bytes(key)))

    def set(self, key: _R) -> None:
        _validate_value(self._annotation, key)
        self._keys[self.name] = cast(Key, key)


class URefReference(NamedKeyReference[Any], Generic[_V]):
    def get(self) -> URef[_V]:
        return cast(URefType[_V], self._annotation).wrap(self._key())

    def set(self, key: URef) -> None:
        if not isinstance(key, URef):
            raise TypeError("Expected URef")
        self._keys[self.name] = key

    def create(self, value: _V | CLValue) -> URef[_V]:
        return cast(URefType[_V], self._annotation).create(value)

    def read(self) -> _V:
        return self.get().read()

    def write(self, value: _V | CLValue) -> None:
        self.get().write(value)

    def add(self, value: _V | CLValue) -> None:
        self.get().add(value)


class DictionaryReference(Dictionary[_K, _V], _NamedKeyBinding):
    """A dictionary whose seed is resolved lazily for each item operation."""

    def __init__(self, keys: NamedKeys, name: str, annotation: Dictionary[_K, _V]) -> None:
        _NamedKeyBinding.__init__(self, keys, name, annotation)
        Dictionary.__init__(self, key=annotation._key_transform,
                            _key_type=annotation._key_type, _value_type=annotation._value_type)

    @property
    def seed(self) -> URef:
        key = self._key()
        if not isinstance(key, URef):
            raise InvalidArgument()
        return key

    def set(self, key: URef) -> None:
        if not isinstance(key, URef):
            raise TypeError("Expected a dictionary seed URef")
        self._keys[self.name] = key

    def create(self) -> URef:
        from .contract_api import storage
        return storage.new_dictionary_seed()


def reference(keys: NamedKeys, name: str, annotation: Any) -> Any:
    if isinstance(annotation, URefType):
        return URefReference(keys, name, annotation)
    if isinstance(annotation, DictionaryType):
        annotation = annotation()
    if isinstance(annotation, Dictionary):
        return DictionaryReference(keys, name, annotation)
    if isinstance(annotation, type) and issubclass(annotation, Key):
        if annotation is URef:
            raise TypeError("Declare the value type with URef[T]")
        return NamedKeyReference(keys, name, annotation)
    raise TypeError("A reference requires a Key type, URef[T], or Dictionary[K, V]")
