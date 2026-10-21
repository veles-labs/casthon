"""CPython inspection for EntryPoint.from_function; replaced in frozen Wasm."""

import inspect
import sys
from typing import Any, Callable

from ._signatures import Signature, function_signature, module_export_names


def describe_function(function: Callable[..., Any]) -> tuple[list[str], Any, bool, Any]:
    from .contracts import BoundEntryPoint, EntryPointReference
    if isinstance(function, (BoundEntryPoint, EntryPointReference)):
        names, parameters, typed, returns, positional = function.describe()
        return names, parameters, typed, returns
    signature: Signature = function_signature(function)
    # Prefer the module constructing the metadata, so imported functions retain
    # the root's selected export names. The function's module is a fallback for
    # callers collecting metadata in a reusable helper.
    frame = inspect.currentframe()
    try:
        caller = frame.f_back.f_back if frame is not None and frame.f_back is not None else None
        caller_module = sys.modules.get(caller.f_globals.get("__name__", "")) if caller is not None else None
    finally:
        del frame
    for module in (caller_module, inspect.getmodule(function)):
        if module is None:
            continue
        try:
            names = module_export_names(module)
        except (OSError, TypeError):
            continue
        selected = [name for name in names if vars(module).get(name) is function]
        if selected:
            return selected, *signature
    raise ValueError("Function has not been selected as a Wasm export")


def describe_call(function: Callable[..., Any]) -> tuple[list[str], Any, bool, Any, int]:
    from .contracts import BoundEntryPoint, EntryPointReference
    if isinstance(function, (BoundEntryPoint, EntryPointReference)):
        return function.describe()  # type: ignore[no-any-return]
    parameters, typed_return, returns = function_signature(function)
    names = []
    for module in tuple(sys.modules.values()):
        if module is None or not any(value is function for value in vars(module).values()):
            continue
        try:
            selected = module_export_names(module)
        except (OSError, TypeError):
            continue
        for name in selected:
            if vars(module).get(name) is function and name not in names:
                names.append(name)
    if not names:
        raise ValueError("Function has not been selected as a Wasm export")
    positional = sum(parameter.kind == parameter.POSITIONAL_OR_KEYWORD
                     for parameter in inspect.signature(function).parameters.values())
    return names, parameters, typed_return, returns, positional
