"""Procedural probes for errors travelling through C helpers and callbacks."""

from typing import Any, NoReturn, cast
from casthon import CLU32, U32, URef, User, Ret, Revert, export
from casthon.contract_api import runtime, storage

SCOPE_MARKER = 17

EXPECTED = {
    "list_load": IndexError, "tuple_load": IndexError, "str_load": IndexError,
    "unicode_load": IndexError, "bytes_load": IndexError, "bytearray_load": IndexError,
    "list_store": IndexError, "list_delete": IndexError, "bytearray_store": IndexError,
    "list_pop": IndexError, "dict_load": KeyError, "dict_delete": KeyError,
    "set_remove": KeyError, "list_index": ValueError, "int_parse": ValueError,
    "float_parse": ValueError, "utf8_decode": UnicodeError, "wrong_index": TypeError,
    "wrong_add": TypeError, "wrong_int": TypeError, "missing_attr": AttributeError,
    "float_divide": ZeroDivisionError, "float_modulo": ZeroDivisionError,
    "float_floor": ZeroDivisionError, "int_true_divide": ZeroDivisionError,
    "negative_shift": ValueError, "missing_arg": TypeError, "extra_arg": TypeError,
    "duplicate_arg": TypeError, "unexpected_keyword": TypeError, "bad_star": TypeError,
    "constructor": User, "property": User, "property_store": User,
    "property_delete": User, "getitem": User, "getattr": User, "callable": User,
    "truth": User, "length": User, "hash": User, "compare": User, "string": User,
    "iterate": User, "next": User, "sort": User, "sorted": User, "map": User,
    "filter": User, "max": User, "int_callback": User, "import": User,
}


def mark(name: str, value: int) -> None:
    key = runtime.get_key(name)
    if isinstance(key, URef):
        storage.write(key, CLU32(value))
    else:
        runtime.put_key(name, storage.new_uref(CLU32(value)))


def signal(kind: str) -> NoReturn:
    try:
        if kind == "ret":
            runtime.ret(CLU32(11))
        if kind == "revert":
            runtime.revert(65536 + 73)
        raise User(71)
    finally:
        mark("native_inner_trace", 12)
        print("FINALLY:inner")


class Constructor:
    def __init__(self, kind: str) -> None:
        signal(kind)


class Callbacks:
    def __init__(self, kind: str) -> None:
        self.kind = kind

    @property
    def value(self) -> Any:
        signal(self.kind)

    @value.setter
    def value(self, value: Any) -> None:
        signal(self.kind)

    @value.deleter
    def value(self) -> None:
        signal(self.kind)

    def __getitem__(self, index: Any) -> Any:
        signal(self.kind)

    def __getattr__(self, name: str) -> Any:
        signal(self.kind)

    def __call__(self, *args: Any) -> Any:
        signal(self.kind)

    def __bool__(self) -> bool:
        signal(self.kind)

    def __len__(self) -> int:
        signal(self.kind)

    def __hash__(self) -> int:
        signal(self.kind)

    def __lt__(self, other: Any) -> bool:
        signal(self.kind)

    def __str__(self) -> str:
        signal(self.kind)

    def __iter__(self) -> Any:
        signal(self.kind)

    def __next__(self) -> Any:
        signal(self.kind)

    def __int__(self) -> int:
        signal(self.kind)


class Indexed:
    def __getitem__(self, index: int) -> int:
        if index >= 2:
            raise IndexError()
        return index


class Iterator:
    def __init__(self) -> None:
        self.index = 0

    def __iter__(self) -> "Iterator":
        return self

    def __next__(self) -> int:
        if self.index >= 2:
            raise StopIteration()
        self.index += 1
        return self.index


def requires(value: int) -> int:
    return value


def fault(name: str, kind: str) -> Any:
    values: list[int] = []
    mapping: dict[str, int] = {}
    mutable = bytearray(b"x")
    empty_set: set[int] = set()
    if name == "list_load": return values[0]
    if name == "tuple_load": return cast(Any, (1,))[9]
    if name == "str_load": return "x"[9]
    if name == "unicode_load": return "ż"[1]
    if name == "bytes_load": return b"x"[9]
    if name == "bytearray_load": return mutable[9]
    if name == "list_store": values[0] = 1
    if name == "list_delete": del values[0]
    if name == "bytearray_store": mutable[9] = 1
    if name == "list_pop": return values.pop()
    if name == "dict_load": return mapping["missing"]
    if name == "dict_delete": del mapping["missing"]
    if name == "set_remove": empty_set.remove(7)
    if name == "list_index": return values.index(7)
    if name == "int_parse": return int("bad")
    if name == "float_parse": return float("bad")
    if name == "utf8_decode": return b"\xff".decode("utf-8")
    if name == "wrong_index": return values[cast(Any, "x")]
    if name == "wrong_add": return 1 + cast(Any, "x")
    if name == "wrong_int": return int(cast(Any, []))
    if name == "missing_attr": return getattr(object(), "missing")
    if name == "float_divide": return 1.0 / 0.0
    if name == "float_modulo": return 1.0 % 0.0
    if name == "float_floor": return 1.0 // 0.0
    if name == "int_true_divide": return 1 / 0
    if name == "negative_shift": return 1 << -1
    if name == "missing_arg": return cast(Any, requires)()
    if name == "extra_arg": return cast(Any, requires)(1, 2)
    if name == "duplicate_arg": return cast(Any, requires)(1, value=2)
    if name == "unexpected_keyword": return cast(Any, requires)(missing=1)
    if name == "bad_star": return cast(Any, requires)(*cast(Any, 7))
    if name == "constructor": return Constructor(kind)
    if name == "import":
        import contracts.native_unwind_bad
        raise User(74)
    callbacks = Callbacks(kind)
    if name == "property": return callbacks.value
    if name == "property_store": callbacks.value = 1
    if name == "property_delete": del callbacks.value
    if name == "getitem": return callbacks[0]
    if name == "getattr": return getattr(callbacks, "missing")
    if name == "callable": return callbacks()
    if name == "truth": return bool(callbacks)
    if name == "length": return len(callbacks)
    if name == "hash": return hash(callbacks)
    if name == "compare": return callbacks < 1
    if name == "string": return str(callbacks)
    if name == "iterate": return iter(callbacks)
    if name == "next": return next(callbacks)
    if name == "sort": return [2, 1].sort(key=callbacks)
    if name == "sorted": return sorted([2, 1], key=callbacks)
    if name == "map": return next(map(callbacks, [1]))
    if name == "filter": return next(filter(callbacks, [1]))
    if name == "max": return max([1, 2], key=callbacks)
    if name == "int_callback": return int(callbacks)
    raise User(74)


def check(name: str, operation: str, kind: str) -> None:
    caught = False
    try:
        fault(name, kind)
    except IndexError:
        if operation != "caught": raise
        assert EXPECTED[name] is IndexError
        caught = True
    except Ret as result:
        if operation != "caught": raise
        assert kind == "ret" and result.payload == CLU32(11).to_bytes()
        caught = True
    except Revert as error:
        if operation != "caught": raise
        assert kind == "revert" and error.code == 65536 + 73
        caught = True
    except Exception as error:
        if operation != "caught": raise
        assert isinstance(error, EXPECTED[name])
        if isinstance(error, User): assert error.code == 65536 + (72 if name == "import" else 71)
        caught = True
    finally:
        mark("native_trace", 19)
        print("FINALLY:outer")
    assert caught
    # Failed binding/imports must leave the caller's globals and pystack usable.
    assert SCOPE_MARKER == 17 and requires(7) == 7


@export
def call() -> CLU32:
    operation = runtime.get_named_arg("operation", str)
    if operation == "matrix":
        for name in EXPECTED:
            check(name, "caught", "error")
        check("import", "caught", "error")
        # Native iterator handlers still swallow only exhaustion exceptions.
        assert list(cast(Any, Indexed())) == [0, 1]
        assert list(Iterator()) == [1, 2]
        mark("native_matrix_ok", len(EXPECTED))
        return CLU32(len(EXPECTED))
    name = runtime.get_named_arg("case", str)
    kind = runtime.try_get_named_arg("kind", str)
    check(name, operation, "error" if kind is None else kind)
    return CLU32(1)
