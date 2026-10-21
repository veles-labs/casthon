"""Basic procedural counter using explicit Casper arguments and ordinary return/raise."""

from cspr import (
    U8,
    U32,
    U256,
    URef,
    CLU8,
    CLU32,
    CLU256,
    CLString,
    EntryPoint,
    MissingKey,
    InvalidArgument,
    User,
    export,
)
from cspr.contract_api import runtime, storage

MODE_PAUSED = 0
MODE_ACTIVE = 1
ENTRY_POINTS = [
    EntryPoint("increment", {}),
    EntryPoint("increment_by", {"amount": U32}),
    EntryPoint("add_fractional", {"amount": U32}),
    EntryPoint("get", {}, U32),
    EntryPoint("set_mode", {"mode": U8}),
    EntryPoint("get_mode", {}, U8),
    EntryPoint("mode_name", {}, str),
    EntryPoint("add_big", {"amount": U256}),
    EntryPoint("get_big", {}, U256),
    EntryPoint("fail_after_write", {}),
]


def _uref(name: str) -> URef:
    key = runtime.get_key(name)
    if key is None:
        raise MissingKey()
    if not isinstance(key, URef):
        raise InvalidArgument()
    return key


def _check_active() -> None:
    if storage.read_or_revert(_uref("mode"), U8) == MODE_PAUSED:
        raise User(100)


def _increment_by(amount: U32) -> None:
    _check_active()
    count = _uref("count")
    storage.write(count, CLU32(storage.read_or_revert(count, U32) + amount))


@export
def increment() -> None:
    _increment_by(1)


@export
def increment_by() -> None:
    _increment_by(runtime.get_named_arg("amount", U32))


@export
def add_fractional() -> None:
    amount = runtime.get_named_arg("amount", U32)
    _check_active()
    count = _uref("count")
    current = storage.read_or_revert(count, U32)
    updated = int(float(current) + float(amount) / 2.0)
    storage.write(count, CLU32(updated))


@export
def get() -> CLU32:
    return CLU32(storage.read_or_revert(_uref("count"), U32))


@export
def set_mode() -> None:
    mode = runtime.get_named_arg("mode", U8)
    if mode not in (MODE_PAUSED, MODE_ACTIVE):
        raise InvalidArgument()
    storage.write(_uref("mode"), CLU8(mode))


@export
def get_mode() -> CLU8:
    return CLU8(storage.read_or_revert(_uref("mode"), U8))


@export
def mode_name() -> CLString:
    mode = storage.read_or_revert(_uref("mode"), U8)
    return CLString("ACTIVE" if mode == MODE_ACTIVE else "PAUSED")


@export
def add_big() -> None:
    amount = runtime.get_named_arg("amount", U256)
    _check_active()
    total = _uref("total")
    storage.write(total, CLU256(storage.read_or_revert(total, U256) + amount))


@export
def get_big() -> CLU256:
    return CLU256(storage.read_or_revert(_uref("total"), U256))


@export
def fail_after_write() -> None:
    count = _uref("count")
    storage.write(count, CLU32(storage.read_or_revert(count, U32) + 1))
    raise User(101)


@export
def call() -> None:
    if runtime.has_key("py_basic"):
        raise InvalidArgument()
    package, access = storage.create_contract_package_at_hash()
    contract, version = storage.add_contract_version(
        package,
        ENTRY_POINTS,
        {
            "count": storage.new_uref(CLU32(0)),
            "total": storage.new_uref(CLU256(0)),
            "mode": storage.new_uref(CLU8(MODE_ACTIVE)),
        },
    )
    runtime.put_key("py_basic", contract)
    runtime.put_key("py_basic_package", package)
    runtime.put_key("py_basic_access", access)
