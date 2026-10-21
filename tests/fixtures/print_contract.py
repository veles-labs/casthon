"""Built-in printing and outer-dispatch outcomes in debug/release builds."""

from cspr import ABIError, ApiError, CLU32, Revert, Ret, U32, export
from cspr.contract_api import runtime, storage

conversions = 0


class Printable:
    def __str__(self):
        global conversions
        conversions += 1
        return "object"


class InvalidCode(Revert):
    def __init__(self):
        pass

    @property
    def code(self):
        raise ValueError("invalid error code")


class Unprintable:
    def __str__(self):
        raise RuntimeError("diagnostic formatting failed")


class UnprintableApiError(ApiError):
    def __init__(self, detail):
        self.code = 17


def nested_failure():
    raise ValueError("nested failure 🐍")


def long_failure():
    raise ValueError("x" * 251 + "🐍" * 100 + " long failure end")


@export
def call() -> U32:
    print("count", 7, Printable(), sep=" | ", end="!\n")
    print("Zażółć 🐍", end="")
    print()
    return conversions


@export
def fail(mode: U32) -> None:
    try:
        if mode == 0:
            raise ApiError(17)
        if mode == 1:
            raise Revert(65577)
        if mode == 2:
            raise ABIError("invalid input")
        if mode == 3:
            raise ValueError("unexpected")
        if mode == 4:
            raise Ret(CLU32(9).to_bytes())
        if mode == 5:
            raise Ret(b"invalid")
        if mode == 7:
            nested_failure()
        if mode == 8:
            raise UnprintableApiError(Unprintable())
        if mode == 9:
            long_failure()
        raise InvalidCode()
    finally:
        print("finally")
        runtime.named_keys["cleanup"] = storage.new_uref(CLU32(1))


@export
def caught() -> U32:
    try:
        nested_failure()
    except ValueError:
        return 42
