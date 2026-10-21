"""Argument presence is independent of Casper's Option wire encoding."""

from enum import Enum
import sys
from typing import Any, Final, TypeVar, Union, get_args, get_origin

if sys.version_info >= (3, 12):
    from typing import TypeAliasType
else:
    from typing_extensions import TypeAliasType

from ._wire_types import _OptionalArg


class MissingType(Enum):
    MISSING = 0

    def __repr__(self) -> str:
        return "MISSING"

    def __str__(self) -> str:
        return "MISSING"


MISSING: Final = MissingType.MISSING
_T = TypeVar("_T")
OptionalArg = TypeAliasType("OptionalArg", Union[_T, MissingType], type_params=(_T,))


def optional_arg_inner(annotation: Any) -> Any:
    if isinstance(annotation, _OptionalArg):
        return annotation.annotation
    if get_origin(annotation) is OptionalArg:
        inner, = get_args(annotation)
        return type(None) if inner is None else inner
    return None


def argument_type(annotation: Any) -> Any:
    inner = optional_arg_inner(annotation)
    return annotation if inner is None else inner


def argument_in_abi(annotation: Any) -> bool:
    return optional_arg_inner(annotation) is None
