"""Typed outbound calls; function references provide ABI data, never execution."""

from typing import Any, Callable, Mapping

from .key import ContractHash
from .return_value import typed_value
from .arguments import MISSING, argument_type, optional_arg_inner


def call_function(contract: ContractHash, function: Callable[..., Any],
                  args: tuple[Any, ...], kwargs: Mapping[str, Any]) -> Any:
    from ._entry_point_signature import describe_call
    from .contract_api.runtime import call_contract

    names, parameters, typed_return, returns, positional = describe_call(function)
    if len(names) != 1:
        raise ValueError("Function has multiple export names; use runtime.call_contract with an explicit name")
    if not typed_return:
        raise ValueError("Remote calls require a wire return annotation; use runtime.call_contract with an explicit return type")
    if len(args) > positional:
        raise TypeError("Too many positional arguments")
    values = dict(kwargs)
    for (name, annotation, has_default), value in zip(parameters, args):
        if name in values:
            raise TypeError("Multiple values for argument: " + name)
        values[name] = value
    allowed = {name for name, annotation, has_default in parameters}
    for name in values:
        if name not in allowed:
            raise TypeError("Unexpected argument: " + name)
    for name, annotation, has_default in parameters:
        if name not in values and not has_default and optional_arg_inner(annotation) is None:
            raise TypeError("Missing argument: " + name)
    encoded = {}
    for name, annotation, has_default in parameters:
        if name not in values:
            continue
        value = values[name]
        if value is MISSING and optional_arg_inner(annotation) is not None:
            continue
        encoded[name] = typed_value(argument_type(annotation), value)
    return call_contract(contract, names[0], encoded, returns)
