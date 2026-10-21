"""Development-side signature policy; this module is never frozen into Wasm."""

import ast
import inspect
from types import ModuleType, UnionType
from typing import Any, Callable, Iterable, Union, get_args, get_origin, get_type_hints

from .types import wire_type
from .values import CLValue
from .arguments import argument_type

Signature = tuple[list[tuple[str, Any, bool]], bool, Any]


def explicit_return(annotation: Any) -> bool:
    if isinstance(annotation, type) and issubclass(annotation, CLValue):
        return True
    args = get_args(annotation)
    return bool(args) and get_origin(annotation) in (Union, UnionType) and all(
        item is type(None) or explicit_return(item) for item in args)


def normalize_signature(parameters: Iterable[tuple[str, Any, bool]], returns: Any,
                        has_return: bool) -> Signature:
    parameters = list(parameters)
    for name, annotation, _ in parameters:
        try:
            wire_type(argument_type(annotation))
        except TypeError as error:
            raise ValueError(f"Parameter {name}: {error}") from error
    typed = has_return and not explicit_return(returns)
    if typed:
        try:
            wire_type(returns)
        except TypeError as error:
            raise ValueError(f"Return: {error}") from error
    return parameters, typed, returns


def function_signature(function: Callable[..., Any]) -> Signature:
    from .contracts import BoundEntryPoint, EntryPointReference
    if isinstance(function, (BoundEntryPoint, EntryPointReference)):
        names, parameters, typed, returns, positional = function.describe()
        return parameters, typed, returns
    signature = inspect.signature(function)
    hints = get_type_hints(inspect.unwrap(function), include_extras=True)
    parameters = []
    for parameter in signature.parameters.values():
        if parameter.kind not in (parameter.POSITIONAL_OR_KEYWORD, parameter.KEYWORD_ONLY):
            raise ValueError("Exports require named parameters without *args or **kwargs")
        if parameter.annotation is parameter.empty:
            raise ValueError(f"Parameter {parameter.name}: a wire annotation is required")
        parameters.append((parameter.name, hints[parameter.name], parameter.default is not parameter.empty))
    return normalize_signature(parameters, hints.get("return"), signature.return_annotation is not signature.empty)


def discover_exports(tree: ast.Module, is_export: Callable[[ast.expr], bool]) -> list[str]:
    exports = []
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and any(is_export(d) for d in node.decorator_list):
            exports.append(node.name)
        elif isinstance(node, (ast.Assign, ast.AnnAssign)):
            value = node.value
            if isinstance(value, ast.Call) and is_export(value.func):
                targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                if len(targets) != 1 or not isinstance(targets[0], ast.Name):
                    raise ValueError("export() requires a single top-level binding")
                exports.append(targets[0].id)
    return list(dict.fromkeys(exports))


def module_export_names(module: ModuleType) -> list[str]:
    from . import export

    def resolve(node: ast.expr) -> Any:
        if isinstance(node, ast.Name):
            return vars(module).get(node.id)
        if isinstance(node, ast.Attribute):
            owner = resolve(node.value)
            return vars(owner).get(node.attr) if isinstance(owner, ModuleType) else None
        return None

    names = discover_exports(ast.parse(inspect.getsource(module)), lambda node: resolve(node) is export)
    from .contracts import _schema
    for cls in module_contracts(module):
        for method in _schema(cls).methods:
            if method.name in names:
                raise ValueError("Duplicate root export: " + method.name)
            names.append(method.name)
    return names


def module_contracts(module: ModuleType) -> list[Any]:
    from .contracts import Contract, export_contract

    def resolve(node: ast.expr) -> Any:
        if isinstance(node, ast.Name):
            return vars(module).get(node.id)
        if isinstance(node, ast.Attribute):
            owner = resolve(node.value)
            return vars(owner).get(node.attr) if isinstance(owner, ModuleType) else None
        return None

    classes = []
    for node in ast.parse(inspect.getsource(module)).body:
        if isinstance(node, ast.ClassDef):
            markers = [d for d in node.decorator_list if resolve(d) is export_contract]
            if not markers:
                continue
            if len(markers) != 1:
                raise ValueError("Use a single @export_contract without parentheses")
            cls = vars(module).get(node.name)
        elif isinstance(node, ast.Expr) and isinstance(node.value, ast.Call) and resolve(node.value.func) is export_contract:
            if len(node.value.args) != 1 or node.value.keywords:
                raise ValueError("export_contract() requires one contract class")
            cls = resolve(node.value.args[0])
        else:
            continue
        if not isinstance(cls, type) or not issubclass(cls, Contract):
            raise ValueError("export_contract requires a Contract subclass")
        classes.append(cls)
    return classes


def module_exports(module: ModuleType) -> dict[str, Callable[..., Any]]:
    names = module_export_names(module)
    if not names:
        raise ValueError("Declare exports with @export, or pass an explicit exports mapping for a dynamic fixture")
    result = {name: getattr(module, name) for name in names if hasattr(module, name)}
    from .contracts import _schema
    for cls in module_contracts(module):
        for method in _schema(cls).methods:
            result[method.name] = getattr(cls, method.attribute)
    return result
