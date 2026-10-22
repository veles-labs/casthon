"""Argument injection and return encoding occur only at the export boundary."""

from __future__ import annotations

from typing import Optional, cast
from casthon import (
    U32, AccountHash, Hash, URef, CLU32, CLString, SerializedCLValue,
    EntryPoint, InvalidArgument, User, export,
    OptionalArg, MISSING,
)
from casthon.contract_api import runtime, storage
from contracts import typed_exports_helpers

NullableAmount = Optional[U32]
calculate = export(typed_exports_helpers.calculate)


def _mark() -> None:
    key = runtime.get_key("typed_cleanup")
    if key is None:
        runtime.put_key("typed_cleanup", storage.new_uref(CLU32(1)))
    elif isinstance(key, URef):
        storage.write(key, CLU32(storage.read_or_revert(key, U32) + 1))
    else:
        raise InvalidArgument()


@export
def nullable(amount: NullableAmount) -> NullableAmount:
    return amount


@export
def defaults(amount: Optional[U32] = 7, *, label: str = "default") -> str:
    return label + ":" + str(amount)


@export
def owner(value: Optional[AccountHash]) -> Optional[AccountHash]:
    assert value is None or isinstance(value, AccountHash)
    return value


@export
def presence(value: OptionalArg[Optional[U32]]) -> str:
    if value is MISSING:
        return "missing"
    return "none" if value is None else str(value)


@export
def presence_default(value: OptionalArg[Optional[U32]] = None) -> str:
    if value is MISSING:
        return "missing"
    return "none" if value is None else str(value)


@export
def presence_number(value: OptionalArg[U32] = 7) -> str:
    return "missing" if value is MISSING else str(value)


ENTRY_POINTS = [
    EntryPoint.from_function(calculate),
    EntryPoint.from_function(nullable),
    EntryPoint.from_function(owner),
    EntryPoint.from_function(presence),
    EntryPoint.from_function(presence_default),
    EntryPoint.from_function(presence_number),
]


@export
def internal(amount: U32) -> U32:
    # This calls the root's exported function directly, with ordinary arguments.
    return calculate(amount, "abc") + 1


@export
def checked_return(operation: str) -> U32:
    try:
        if operation == "overflow":
            return 1 << 32
        if operation == "negative":
            return -1
        if operation == "bool":
            return cast(U32, True)
        if operation == "none":
            return cast(U32, None)
        if operation == "explicit":
            return cast(U32, CLU32(11))
        if operation == "wrong_cl_type":
            return cast(U32, CLString("bad"))
        if operation == "bad_payload":
            return cast(U32, SerializedCLValue(b"\1\0\0\0\7\4"))
        return 7
    finally:
        _mark()


@export
def key_return(valid: bool) -> AccountHash:
    if valid:
        return runtime.get_caller()
    return cast(AccountHash, Hash(bytes(32)))


@export
def early_ret(amount: U32) -> U32:
    try:
        runtime.ret(CLU32(amount))
    finally:
        _mark()


@export
def failure(code: U32) -> None:
    try:
        raise User(code)
    finally:
        _mark()


@export
def unit() -> None:
    _mark()


@export
def call() -> None:
    package, access = storage.create_contract_package_at_hash()
    contract, version = storage.add_contract_version(package, ENTRY_POINTS, {})
    runtime.put_key("py_typed_exports", contract)
    runtime.put_key("py_typed_exports_package", package)
    runtime.put_key("py_typed_exports_access", access)
