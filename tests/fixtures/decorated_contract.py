"""Ordinary decorators on free exports and class entrypoints."""

from functools import wraps

from cspr import MISSING, OptionalArg, U32, UserError, export
from cspr.contracts import Contract, entry_point, export_contract

trace = []


def plus_ten(function):
    @wraps(function)
    def decorated(*args, **kwargs):
        return function(*args, **kwargs) + 10
    return decorated


def double(function):
    @wraps(function)
    def decorated(*args, **kwargs):
        return function(*args, **kwargs) * 2
    return decorated


def record(function):
    @wraps(function)
    def decorated(self, *args, **kwargs):
        trace.append("guard")
        try:
            return function(self, *args, **kwargs)
        finally:
            print("decorator finally")
    return decorated


@export
@plus_ten
@double
def call(value: U32 = 1) -> U32:
    return value


@export_contract
class Example(Contract):
    @entry_point
    @record
    def read(self, value: OptionalArg[U32] = MISSING) -> U32:
        if value is MISSING:
            raise UserError(90)
        return value + len(trace)
