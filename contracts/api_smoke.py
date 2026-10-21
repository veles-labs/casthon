"""Small procedural sessions exercising the low-level host API."""

from cspr import (
    U32,
    U256,
    URef,
    CLU32,
    CLU256,
    CLBytes,
    CLString,
    CLUnit,
    api_error,
    export,
)
from cspr.contract_api import runtime, storage
from contracts import api_smoke_helpers

ENTRY_POINTS = [*api_smoke_helpers.ENTRY_POINTS]
read_count = export(api_smoke_helpers.read_count)


@export
def call() -> None:
    if runtime.try_get_named_arg("operation", str) == "call_counter":
        call_counter()
        return
    name = runtime.try_get_named_arg("dictionary_name", str)
    if name is None:
        name = "api_smoke_dictionary"
    seed = storage.new_dictionary(name)
    if storage.dictionary_get(seed, "missing", U256) is not None:
        runtime.revert(api_error.user(200))
    storage.dictionary_put(seed, "answer", CLU256(42))
    if storage.dictionary_get(seed, "answer", U256) != 42:
        runtime.revert(api_error.user(201))
    storage.read_or_revert(storage.new_uref(CLUnit()), None)
    keys = runtime.named_keys
    keys["api_smoke_count"] = storage.new_uref(CLU256(0))
    count = keys["api_smoke_count"]
    if not isinstance(count, URef):
        raise TypeError("Expected count URef")
    count.write(CLU256(7))
    count.add(CLU256(5))
    keys["api_smoke_caller"] = runtime.get_caller()
    runtime.put_key(
        "api_smoke_hash", storage.new_uref(CLBytes(runtime.blake2b(b"Casper")))
    )
    major, minor, patch = runtime.get_protocol_version()
    runtime.put_key(
        "api_smoke_protocol", storage.new_uref(CLString(f"{major}.{minor}.{patch}"))
    )
    keys["temporary"] = count
    snapshot = keys.items()
    del keys["temporary"]
    if not any(name == "temporary" for name, key in snapshot):
        runtime.revert(api_error.user(202))
    if "temporary" in keys or keys.get("temporary") is not None:
        runtime.revert(api_error.user(203))
    if "api_smoke_count" not in keys or count not in keys.values():
        runtime.revert(api_error.user(205))
    if "api_smoke_count" not in keys.keys() or len(keys) != len(runtime.list_named_keys()):
        runtime.revert(api_error.user(206))
    runtime.ret(CLU32(count.read(U256)))


@export
def call_counter() -> None:
    contract = runtime.get_key("py_counter")
    if contract is None:
        runtime.revert(api_error.MISSING_KEY)
    amount = runtime.get_named_arg("amount", U32)
    runtime.call_contract(contract, "increment_by", {"amount": CLU32(amount)})
    value = runtime.call_contract(contract, "get", {}, U32)
    expected = runtime.try_get_named_arg("expected", U32)
    if expected is not None and value != expected:
        runtime.revert(api_error.user(204))
    runtime.ret(CLU32(value))
