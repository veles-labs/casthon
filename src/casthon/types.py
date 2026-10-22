"""Python annotations for Casper wire types."""

from types import UnionType
from typing import Annotated, Any, Union, get_args, get_origin, TypeAlias, TypeVar

from ._wire_types import UNSIGNED, optional_inner as _optional_inner
from ._cl_types import CLType as CLType, SCALARS, resolve_type

U8 = Annotated[int, "U8"]
U32 = Annotated[int, "U32"]
U64 = Annotated[int, "U64"]
U256 = Annotated[int, "U256"]
U512 = Annotated[int, "U512"]
_K = TypeVar("_K")
_V = TypeVar("_V")
Map: TypeAlias = dict[_K, _V]


def optional_inner(annotation: Any) -> Any:
    if get_origin(annotation) in (Union, UnionType):
        args = get_args(annotation)
        if len(args) == 2 and type(None) in args:
            return args[0] if args[1] is type(None) else args[1]
    return _optional_inner(annotation)


def cl_type_of(annotation: Any, depth: int = 0) -> CLType:
    if depth > 32:
        raise TypeError("CL type nesting limit")
    if get_origin(annotation) is Annotated:
        args = get_args(annotation)
        if args[0] is int and args[1] in UNSIGNED:
            return SCALARS[args[1]]
        return cl_type_of(args[0], depth)
    inner = optional_inner(annotation)
    if inner is not None:
        return CLType(13, (cl_type_of(inner, depth + 1),))
    origin, args = get_origin(annotation), get_args(annotation)
    if origin is tuple:
        if not 1 <= len(args) <= 3 or Ellipsis in args:
            raise TypeError("Casper tuples require one to three fixed elements")
        return CLType(17 + len(args), tuple(cl_type_of(arg, depth + 1) for arg in args))
    if origin in (list, dict):
        expected = 1 if origin is list else 2
        if len(args) != expected:
            raise TypeError("Collection type parameters are required")
        return CLType(14 if origin is list else 17,
                      tuple(cl_type_of(arg, depth + 1) for arg in args))
    return resolve_type(annotation, depth)


def wire_type(annotation: Any) -> str:
    """Display spelling retained for low-level clients and build reports."""
    return str(cl_type_of(annotation))
