"""Invocation plumbing shared by frozen Wasm and native contract tests."""

from typing import Any, Callable
from .contract_api.runtime import get_named_arg
from .errors import MissingArgument
from .arguments import MISSING
from .return_value import serialize_return, serialize_typed_return


def invoke(function: Callable[..., Any], signature: tuple[Any, bool, Any]) -> bytes | None:
    parameters, typed_return, return_type = signature
    arguments = {}
    for name, annotation, has_default in parameters:
        try:
            value = get_named_arg(name, annotation)
            if value is not MISSING or not has_default:
                arguments[name] = value
        except MissingArgument:
            if not has_default:
                raise
    result = function(**arguments)
    if typed_return:
        return serialize_typed_return(return_type, result)
    if result is None:
        return None
    return serialize_return(result)
