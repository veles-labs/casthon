"""Annotation facade; resolution uses the same implementation as CPython."""

from ._wire_types import UNSIGNED, _Unsigned, optional_inner as optional_inner, resolve as wire_type
from ._cl_types import CLType, resolve_type as cl_type_of

U8, U32, U64, U256, U512 = [_Unsigned(kind) for kind in UNSIGNED]


def wire_type(annotation):
    return str(cl_type_of(annotation))

# Generic subscriptions are compiled into structural CLType descriptors.
Map = dict
