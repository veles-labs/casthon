"""Explicit stored-contract entrypoint metadata, independent of Wasm exports."""

# These values are serialized by storage when registering a contract version.

from typing import Any, Callable, Mapping, Sequence, cast
from .codec import ABIError, cl_type, encode
from .types import cl_type_of
from .enums import EntryPointAccess, EntryPointType, EntryPointPayment
from .arguments import argument_in_abi, argument_type

_INFER = object()


class EntryPoint:
    def __init__(self, name: str, args: Mapping[str, Any] | Sequence[tuple[str, Any]], returns: Any = None, *,
                 access: EntryPointAccess = EntryPointAccess.PUBLIC,
                 groups: Sequence[str] = (), entry_point_type: EntryPointType = EntryPointType.CALLED,
                 payment: EntryPointPayment = EntryPointPayment.CALLER) -> None:
        parameters = list(cast(Mapping[str, Any], args).items()) if hasattr(args, "items") else list(args)
        self.name, self.args, self.returns = name, dict(parameters), returns
        if len(self.args) != len(parameters):
            raise ABIError("Duplicate entrypoint parameter")
        self._parameters = parameters
        self.access, self.groups = access, groups
        self.entry_point_type, self.payment = entry_point_type, payment

    @classmethod
    def from_function(cls, function: Callable[..., Any], *, name: str | None = None,
                      returns: Any = _INFER,
                      access: EntryPointAccess = EntryPointAccess.PUBLIC,
                      groups: Sequence[str] = (),
                      entry_point_type: EntryPointType = EntryPointType.CALLED,
                      payment: EntryPointPayment = EntryPointPayment.CALLER) -> "EntryPoint":
        """Describe a selected export using its invocation annotations.

        Registration remains explicit. Python defaults do not change parameter
        CLTypes or make a non-Option parameter optional to Casper's validator.
        Raw CLValue returns require an explicit returns= annotation.
        """
        from ._entry_point_signature import describe_function

        names, parameters, typed_return, return_type = describe_function(function)
        if name is None:
            if len(names) > 1:
                raise ValueError("Function has multiple export names; pass name= explicitly")
            name = names[0] if names else function.__name__
        if returns is _INFER:
            if not typed_return:
                raise ValueError("Return CLType cannot be inferred; add a wire annotation or pass returns=")
            returns = return_type
        cl_type_of(returns)
        return cls(name, [(label, argument_type(annotation)) for label, annotation, _ in parameters
                          if argument_in_abi(annotation)], returns,
                   access=access, groups=groups, entry_point_type=entry_point_type, payment=payment)

    def to_bytes(self) -> bytes:
        data = encode("String", self.name) + encode("U32", len(self._parameters))
        for name, annotation in self._parameters:
            data += encode("String", name) + cl_type(annotation)
        access = EntryPointAccess.from_value(int(self.access))
        access_bytes = bytes([int(access)])
        if access == EntryPointAccess.GROUPS:
            access_bytes += encode("U32", len(self.groups))
            for label in self.groups:
                access_bytes += encode("String", label)
        elif self.groups:
            raise ABIError("Groups require EntryPointAccess.GROUPS")
        kind = EntryPointType.from_value(int(self.entry_point_type))
        payment = EntryPointPayment.from_value(int(self.payment))
        return data + cl_type(self.returns) + access_bytes + bytes([int(kind), int(payment)])

    def to_legacy_bytes(self) -> bytes:
        if self.entry_point_type == EntryPointType.FACTORY or self.access == EntryPointAccess.TEMPLATE or self.payment != EntryPointPayment.CALLER:
            raise ABIError("Legacy entrypoints cannot represent this metadata")
        return self.to_bytes()[:-1]


def serialize_entry_points(entries: Sequence[EntryPoint], legacy: bool = False) -> bytes:
    by_name = {entry.name: entry for entry in entries}
    if len(by_name) != len(entries):
        raise ABIError("Duplicate stored entrypoint")
    data = encode("U32", len(entries))
    for name, entry in sorted(by_name.items()):
        data += encode("String", name) + (entry.to_legacy_bytes() if legacy else entry.to_bytes())
    return data
