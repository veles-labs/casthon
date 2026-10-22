"""Wire descriptors shared by the authoring and frozen SDKs."""

from typing import Any
from .key import Key
from .enums import WireEnum

UNSIGNED = ("U8", "U32", "U64", "U256", "U512")
WIRE_TYPES = UNSIGNED + ("Bool", "String", "Unit", "Key", "Bytes", "List<Key>", "Map<Key,U8>")


class _Unsigned:
    """Frozen equivalent of an Annotated[int, unsigned wire type]."""

    def __init__(self, kind: str) -> None:
        self.kind = kind

    def __call__(self, value: Any) -> int:
        return int(value)


class _Optional:
    """Frozen Optional annotation, retaining concrete Key subclasses."""

    def __init__(self, annotation: Any) -> None:
        self.annotation = "Unit" if annotation is None else annotation


class _OptionalArg:
    """Frozen argument-presence marker; this is not a Casper wire type."""

    def __init__(self, annotation: Any) -> None:
        self.annotation = "Unit" if annotation is None else annotation


class _EnumRef:
    """Frozen enum reference, resolved after application modules have loaded."""

    def __init__(self, module: str, name: str) -> None:
        self.module, self.name = module, name

    def resolve(self) -> Any:
        import sys
        return getattr(sys.modules[self.module], self.name)


def enum_type(annotation: Any) -> Any:
    if isinstance(annotation, _EnumRef):
        return annotation.resolve()
    if isinstance(annotation, type) and annotation is not WireEnum and issubclass(annotation, WireEnum):
        return annotation
    return None


def optional_inner(annotation: Any) -> Any:
    if isinstance(annotation, _Optional):
        return annotation.annotation
    if type(annotation) is str and annotation.startswith("Option<") and annotation.endswith(">"):
        return annotation[7:-1]
    return None


def resolve(annotation: Any) -> str:
    # Metadata can be serialized before the referenced application is imported.
    if isinstance(annotation, _EnumRef) or enum_type(annotation) is not None:
        return "U8"
    if isinstance(annotation, _Unsigned) and annotation.kind in UNSIGNED:
        return annotation.kind
    if isinstance(annotation, _Optional):
        return resolve("Option<" + resolve(annotation.annotation) + ">")
    if type(annotation) is str:
        inner, depth = annotation, 0
        while inner.startswith("Option<") and inner.endswith(">"):
            inner, depth = inner[7:-1], depth + 1
        collection_depth = int(inner in ("Bytes", "List<Key>", "Map<Key,U8>"))
        if depth + collection_depth <= 32 and inner in WIRE_TYPES:
            return annotation
    if isinstance(annotation, type) and issubclass(annotation, Key):
        return "Key"
    if annotation is bytes:
        return "Bytes"
    if annotation is bool:
        return "Bool"
    if annotation is str:
        return "String"
    if annotation is None or annotation is type(None):
        return "Unit"
    raise TypeError("Use an explicit Casper wire type: " + str(annotation))
