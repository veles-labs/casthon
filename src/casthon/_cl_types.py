"""Structural CL types shared by native Python and frozen contracts."""

from typing import Any
from .key import Key
from . import key as _key_types
from ._wire_types import _Unsigned, _Optional, _EnumRef, enum_type

NAMES = {0: "Bool", 3: "U8", 4: "U32", 5: "U64", 7: "U256", 8: "U512",
         9: "Unit", 10: "String", 11: "Key", 12: "URef", 13: "Option", 14: "List", 17: "Map",
         18: "Tuple1", 19: "Tuple2", 20: "Tuple3"}
BITS = {3: 8, 4: 32, 5: 64, 7: 256, 8: 512}


class CLType:
    def __init__(self, tag: int, children: tuple[Any, ...] = (), annotation: Any = None) -> None:
        if tag not in NAMES or len(children) != {13: 1, 14: 1, 17: 2, 18: 1, 19: 2, 20: 3}.get(tag, 0):
            raise TypeError("Unsupported CL type descriptor")
        self.tag, self.annotation = tag, annotation
        self.depth = 0
        resolved = []
        for child in children:
            child = child if isinstance(child, CLType) else resolve_type(child)
            self.depth = max(self.depth, child.depth + 1)
            if self.depth > 32:
                raise TypeError("CL type nesting limit")
            resolved.append(child)
        self.children = tuple(resolved)

    def __str__(self) -> str:
        if self.annotation is bytes:
            return "Bytes"
        name = NAMES[self.tag]
        if not self.children:
            return name
        parts = []
        for child in self.children:
            parts.append(str(child))
        return name + "<" + ",".join(parts) + ">"

    def __repr__(self) -> str:
        return str(self)

    def to_bytes(self) -> bytes:
        data = bytes([self.tag])
        for child in self.children:
            data += child.to_bytes()
        return data


SCALARS = {}
for _tag, _name in NAMES.items():
    if _tag not in (13, 14, 17, 18, 19, 20):
        SCALARS[_name] = CLType(_tag)
SCALARS["Key"].annotation = Key
SCALARS["Bytes"] = CLType(14, (SCALARS["U8"],), bytes)
# Key variants are SDK types known at startup. Reuse their descriptors rather
# than constructing objects underneath deeply nested contract imports.
KEY_TYPES = {Key: SCALARS["Key"]}
for _name in dir(_key_types):
    _variant = getattr(_key_types, _name)
    if isinstance(_variant, type) and _variant is not Key and issubclass(_variant, Key):
        KEY_TYPES[_variant] = CLType(11, annotation=_variant)

# Compatibility for existing low-level callers. New type expressions never
# stringify their children and do not use this legacy-name boundary.
LEGACY = SCALARS.copy()
LEGACY["List<Key>"] = CLType(14, (SCALARS["Key"],))
LEGACY["Map<Key,U8>"] = CLType(17, (SCALARS["Key"], SCALARS["U8"]))


def resolve_type(annotation: Any, depth: int = 0) -> CLType:
    if depth > 32:
        raise TypeError("CL type nesting limit")
    if isinstance(annotation, CLType):
        return annotation
    # A typed URef used as a wire value has Casper's URef CLType. Bare Key
    # subclasses, including bare URef, retain their existing Key encoding.
    from .references import URefType
    if isinstance(annotation, URefType):
        return CLType(12, annotation=annotation)
    if isinstance(annotation, _Unsigned):
        return SCALARS[annotation.kind]
    if isinstance(annotation, _Optional):
        return CLType(13, (resolve_type(annotation.annotation, depth + 1),))
    if isinstance(annotation, _EnumRef) or enum_type(annotation) is not None:
        return CLType(3, annotation=annotation)
    if isinstance(annotation, type) and issubclass(annotation, Key):
        if annotation not in KEY_TYPES:
            KEY_TYPES[annotation] = CLType(11, annotation=annotation)
        return KEY_TYPES[annotation]
    if annotation is bytes:
        return SCALARS["Bytes"]
    if annotation is bool:
        return SCALARS["Bool"]
    if annotation is str:
        return SCALARS["String"]
    if annotation is None or annotation is type(None):
        return SCALARS["Unit"]
    if type(annotation) is str:
        if annotation in LEGACY:
            return LEGACY[annotation]
        if annotation.startswith("Option<") and annotation.endswith(">"):
            return CLType(13, (resolve_type(annotation[7:-1], depth + 1),))
    raise TypeError("Use an explicit Casper wire type: " + str(annotation))
