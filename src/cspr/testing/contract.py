"""Explicit native invocation boundaries around ordinary contract functions."""

from dataclasses import dataclass
from types import ModuleType
from typing import Any, Callable, Mapping

from .._dispatch import invoke
from .._signatures import function_signature, module_exports
from ..contracts import Contract, EntryPointReference, _schema
from ..enums import EntryPointAccess, EntryPointType, EntryPointPayment
from ..errors import InvalidArgument, MissingArgument, Ret
from ..key import AccountHash, Key, URef
from ..return_value import serialize_return, validate_return_payload
from ..types import wire_type
from ..values import CLValue, SerializedCLValue
from . import use_host
from .mock import MockHost, UnsupportedHostCall
from .values import inspect_value


@dataclass(frozen=True)
class InvocationResult:
    payload: bytes | None

    @property
    def cl_value(self) -> SerializedCLValue | None:
        return None if self.payload is None else SerializedCLValue(self.payload)

    @property
    def value(self) -> Any:
        return None if self.payload is None else inspect_value(self.payload)[1]


class ContractHarness:
    def __init__(self, module: ModuleType | type[Contract], *, host: MockHost | None = None,
                 contract: Key | None = None,
                 exports: Mapping[str, Callable[..., Any]] | None = None) -> None:
        self.module, self.host, self.contract = module, host or MockHost(), contract
        if exports is not None:
            self.exports = dict(exports)
        elif isinstance(module, type):
            self.exports = {method.name: getattr(module, method.attribute) for method in _schema(module).methods}
        else:
            self.exports = module_exports(module)
        self.signatures = {name: function_signature(function) for name, function in self.exports.items()}

    def at(self, contract: Key) -> "ContractHarness":
        return ContractHarness(self.module, host=self.host, contract=contract, exports=self.exports)

    def invoke(self, entry: str, args: Mapping[str, CLValue] | None = None, *,
               caller: AccountHash | None = None, raw_args: Mapping[str, bytes] | None = None) -> InvocationResult:
        if entry not in self.exports:
            raise ValueError(f"No selected export named {entry}")
        if args is not None and raw_args is not None:
            raise ValueError("Choose typed args or raw_args")
        args = dict(args or {})
        encoded = {name: serialize_return(value) for name, value in args.items()}
        payloads = dict(raw_args) if raw_args is not None else {
            name: data[4:4 + int.from_bytes(data[:4], "little")] for name, data in encoded.items()}
        caller = caller or self.host.caller
        values = [inspect_value(data)[1] for data in encoded.values()]
        with self.host.transaction():
            with self.host.context(account=caller, caller=caller):
                for value in values:
                    self._grant(value, validate=True)
            with self.host.context(account=caller if self.contract is None else None,
                                   contract=self.contract, caller=caller, args=payloads, module=self.module), use_host(self.host):
                self._validate_entry(entry, encoded, payloads)
                for value in values:
                    self._grant(value)
                try:
                    function = self.exports[entry]
                    if isinstance(function, EntryPointReference):
                        function = getattr(function.owner.bind(), function.attribute)
                    payload = invoke(function, self.signatures[entry])
                except Ret as signal:
                    try:
                        payload = signal.payload
                        validate_return_payload(payload)
                    except BaseException:
                        raise InvalidArgument() from None
                return InvocationResult(payload)

    def _grant(self, value: Any, *, validate: bool = False) -> None:
        if isinstance(value, URef):
            if validate:
                self.host._uref(bytes(value), 0)
            else:
                self.host.grant(value)
        elif isinstance(value, (list, tuple)):
            for item in value:
                self._grant(item, validate=validate)
        elif isinstance(value, dict):
            for key, item in value.items():
                self._grant(key, validate=validate)
                self._grant(item, validate=validate)

    def _validate_entry(self, entry: str, args: dict[str, bytes], payloads: dict[str, bytes]) -> None:
        if self.contract is None:
            return
        if self.contract in self.host.disabled:
            raise InvalidArgument()
        metadata = self.host.entry_points.get(self.contract)
        if metadata is None or entry not in metadata:
            raise ValueError(f"Stored entrypoint {entry} has not been registered")
        point = metadata[entry]
        if (point.access != EntryPointAccess.PUBLIC or point.entry_point_type != EntryPointType.CALLED
                or point.payment != EntryPointPayment.CALLER):
            raise UnsupportedHostCall("MockHost supports public CALLED entrypoints with caller payment only")
        if self.host.strict_arguments:
            for name, annotation in point.args.items():
                kind = wire_type(annotation)
                if name not in payloads:
                    if not kind.startswith("Option<"):
                        raise MissingArgument()
                elif name not in args:
                    raise ValueError("Strict CLType checking requires typed args, not raw_args")
                elif inspect_value(args[name])[0] != kind:
                    raise InvalidArgument()
