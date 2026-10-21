"""Frozen argument annotations and the same identity-based MISSING sentinel."""

from ._wire_types import _OptionalArg


class MissingType:
    def __new__(cls, value):
        if value != 0:
            raise ValueError("Invalid MissingType value")
        return MISSING

    @property
    def name(self):
        return "MISSING"

    @property
    def value(self):
        return 0

    def __repr__(self):
        return "MISSING"

    def __str__(self):
        return "MISSING"


MISSING = object.__new__(MissingType)
MissingType.MISSING = MISSING
OptionalArg = _OptionalArg


def optional_arg_inner(annotation):
    return annotation.annotation if isinstance(annotation, _OptionalArg) else None


def argument_type(annotation):
    inner = optional_arg_inner(annotation)
    return annotation if inner is None else inner


def argument_in_abi(annotation):
    return optional_arg_inner(annotation) is None
