"""Freeze procedural Python; explicit @export markers select Wasm exports."""

import ast
import re
from pathlib import Path
from typing import Annotated, List, Dict, Optional, Union, get_args, get_origin

import casthon
from casthon.types import optional_inner
from casthon.arguments import argument_type, optional_arg_inner
from casthon._signatures import discover_exports, normalize_signature

ROOT = Path(__file__).resolve().parent.parent


def enum_members(node):
    """Read a closed U8 enum without executing its application code."""
    if node.decorator_list or node.keywords:
        raise ValueError("Frozen WireEnums do not accept decorators or class options")
    members = {}
    for item in node.body:
        if isinstance(item, ast.Expr) and isinstance(item.value, ast.Constant) and isinstance(item.value.value, str):
            continue
        if isinstance(item, ast.FunctionDef) and item.name == "_missing_":
            if (len(item.decorator_list) != 1 or not isinstance(item.decorator_list[0], ast.Name)
                    or item.decorator_list[0].id != "classmethod"):
                raise ValueError("An enum _missing_ hook must use @classmethod")
            continue
        if not (isinstance(item, ast.Assign) and len(item.targets) == 1 and isinstance(item.targets[0], ast.Name)):
            raise ValueError("Frozen WireEnums support integer members and a _missing_ hook")
        value = ast.literal_eval(item.value)
        if type(value) is not int or not 0 <= value <= 255:
            raise ValueError("Frozen WireEnum discriminants must fit U8")
        name = item.targets[0].id
        if name in members or value in members.values():
            raise ValueError("Frozen WireEnums require distinct names and values")
        members[name] = value
    if not members:
        raise ValueError("A wire enum requires members")
    return members


def check_profile(tree):
    for node in ast.walk(tree):
        if isinstance(
            node,
            (
                ast.TryStar,
                ast.With,
                ast.AsyncWith,
                ast.AsyncFunctionDef,
                ast.Await,
                ast.Yield,
                ast.YieldFrom,
                ast.Match,
            ),
        ):
            raise ValueError(
                f"Line {node.lineno}: {type(node).__name__} is outside the Casper MVP profile"
            )
        if isinstance(node, ast.Constant) and isinstance(node.value, complex):
            raise ValueError(f"Line {node.lineno}: complex numbers are disabled")
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id in ("eval", "exec", "compile", "__import__")
        ):
            raise ValueError(f"Line {node.lineno}: dynamic code is disabled")
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            modules = (
                [node.module]
                if isinstance(node, ast.ImportFrom)
                else [a.name for a in node.names]
            )
            for module in modules:
                if not isinstance(module, str):
                    raise ValueError(
                        f"Line {node.lineno}: relative contract imports are unsupported"
                    )
                if module == "casthon.testing" or module.startswith("casthon.testing.") or module == "casthon._signatures":
                    raise ValueError("Testing and development helpers cannot be imported by frozen contracts")
                if isinstance(node, ast.ImportFrom) and module == "casthon" and any(
                        alias.name in ("testing", "_signatures") for alias in node.names):
                    raise ValueError("Testing and development helpers cannot be imported by frozen contracts")
                if module == "functools" and isinstance(node, ast.ImportFrom) and all(
                        alias.name == "wraps" for alias in node.names):
                    continue
                if module not in ("typing", "__future__") and not (
                    module == "casthon"
                    or module.startswith("casthon.")
                    or module == "contracts"
                    or module.startswith("contracts.")
                ):
                    raise ValueError(
                        f"Line {node.lineno}: import is outside the frozen contract profile"
                    )


class Lower(ast.NodeTransformer):
    """Remove development annotations; bind SDK host access directly in Wasm."""

    def __init__(self, sdk=False, graph=None, path=None):
        self.sdk = sdk
        self.graph, self.path = graph, path
        self.optional_factory = None
        self.argument_factory = False

    def visit_Module(self, node):
        names = {part.id for part in ast.walk(node) if isinstance(part, ast.Name)}
        names.update(part.arg for part in ast.walk(node) if isinstance(part, ast.arg))
        names.update(alias.asname or alias.name.split(".")[0]
                     for part in ast.walk(node) if isinstance(part, (ast.Import, ast.ImportFrom))
                     for alias in part.names)
        names.update(part.name for part in ast.walk(node)
                     if isinstance(part, (ast.FunctionDef, ast.ClassDef)))
        self.optional_name = "_cspr_optional"
        while self.optional_name in names:
            self.optional_name += "_"
        self.argument_name = "_cspr_optional_arg"
        while self.argument_name in names:
            self.argument_name += "_"
        self.enum_name = "_cspr_enum"
        while self.enum_name in names:
            self.enum_name += "_"
        self.contracts_name = "_cspr_contracts"
        while self.contracts_name in names:
            self.contracts_name += "_"
        self.events_name = "_cspr_events"
        while self.events_name in names:
            self.events_name += "_"
        self.cspr_name = "_cspr_types"
        while self.cspr_name in names:
            self.cspr_name += "_"
        node = self.generic_visit(node)
        if getattr(self, "uses_events", False):
            node.body.insert(0, ast.Import(names=[ast.alias(name="casthon.events", asname=self.events_name)]))
        if getattr(self, "uses_contracts", False):
            index = int(bool(node.body and isinstance(node.body[0], ast.Expr) and isinstance(node.body[0].value, ast.Constant) and isinstance(node.body[0].value.value, str)))
            node.body.insert(index, ast.Import(names=[ast.alias(name="casthon.contracts", asname=self.contracts_name)]))
        if self.optional_factory or self.argument_factory:
            index = int(bool(node.body and isinstance(node.body[0], ast.Expr)
                             and isinstance(node.body[0].value, ast.Constant)
                             and isinstance(node.body[0].value.value, str)))
            node.body.insert(index, ast.ImportFrom(module="casthon._wire_types", level=0,
                names=[ast.alias(name="_Optional", asname=self.optional_name),
                       ast.alias(name="_OptionalArg", asname=self.argument_name),
                       ast.alias(name="_EnumRef", asname=self.enum_name)]))
            node.body.insert(index, ast.Import(names=[ast.alias(name="casthon", asname=self.cspr_name)]))
        return node

    def is_export(self, node):
        return self.graph is not None and self.graph.is_export(self.path, node)

    def visit_Import(self, node):
        node.names = [alias for alias in node.names if alias.name not in ("typing", "__future__")]
        return node if node.names else None

    def visit_ImportFrom(self, node):
        if node.module in ("typing", "__future__", "functools"):
            return None
        if self.sdk and node.module == "_context" and node.level:
            return ast.copy_location(
                ast.Import(names=[ast.alias(name="_casper", asname="host")]), node
            )
        if not self.sdk:
            node.names = [
                alias for alias in node.names
                if not self.is_export(ast.Name(id=alias.asname or alias.name))
            ]
            if not node.names:
                return None
        return node

    def visit_FunctionDef(self, node):
        if self.sdk and node.name == "__class_getitem__":
            # Contract subscriptions become .of(); MicroPython needs no generic hooks.
            return None
        if any(
            isinstance(d, ast.Name) and d.id == "overload" for d in node.decorator_list
        ):
            return None
        decorators = []
        for decorator in node.decorator_list:
            if self.is_export(decorator):
                continue
            if (not self.sdk and isinstance(decorator, ast.Call)
                    and class_planner(self.graph).symbol(self.path, decorator.func) == "functools.wraps"):
                if len(decorator.args) != 1 or decorator.keywords:
                    raise ValueError("Frozen functools.wraps accepts one wrapped function")
                # Inspection metadata is frozen from the annotated definition.
                # MicroPython functions do not support these writable attributes.
                continue
            decorators.append(decorator)
        node.decorator_list = decorators
        node.returns = None
        args = [*node.args.posonlyargs, *node.args.args, *node.args.kwonlyargs]
        if node.args.vararg:
            args.append(node.args.vararg)
        if node.args.kwarg:
            args.append(node.args.kwarg)
        for arg in args:
            arg.annotation = None
        return self.generic_visit(node)

    def visit_If(self, node):
        # Type-only imports disappear with the SDK's development annotations.
        if self.sdk and isinstance(node.test, ast.Name) and node.test.id == "TYPE_CHECKING":
            return [result for statement in node.orelse
                    if (result := self.visit(statement)) is not None]
        return self.generic_visit(node)

    def visit_ClassDef(self, node):
        fields = []
        if not self.sdk:
            # Application enums use the same small frozen implementation as
            # host enums, without importing CPython's enum package in Wasm.
            if len(node.bases) == 1 and class_planner(self.graph).symbol(self.path, node.bases[0]) in ("casthon.enums.WireEnum", "casthon.WireEnum"):
                members = []
                for name, value in enum_members(node).items():
                    members.append(ast.Assign(targets=[ast.Attribute(value=ast.Name(id=node.name, ctx=ast.Load()), attr=name, ctx=ast.Store())],
                        value=ast.Call(func=ast.Name(id=node.name, ctx=ast.Load()), args=[ast.Constant(value=value), ast.Constant(value=name)], keywords=[])))
                node.body = [self.visit(item) for item in node.body if isinstance(item, ast.FunctionDef)] or [ast.Pass()]
                return [node, *members]
            event = event_planner(self.graph).plan(self.path, node)
            if event is not None:
                self.uses_events, self.optional_factory = True, True
                parameters = ", ".join(event.fields)
                constructor = "def __init__(self" + (", " + parameters if parameters else "") + "):\n"
                constructor += "\n".join("    self." + name + " = " + name for name in event.fields) or "    pass"
                node.body.append(ast.parse(constructor).body[0])
                result = self.generic_visit(node)
                fields_text = ", ".join("(" + repr(name) + ", " + frozen_annotation(annotation, self.cspr_name,
                    self.optional_name, self.argument_name, self.enum_name, self.path) + ")" for name, annotation in event.fields.items())
                encoder_refs = []
                for encoder in event.encoders:
                    if encoder.path is None:
                        encoder_refs.append(self.cspr_name + "." + encoder.name)
                    else:
                        module = "__name__" if encoder.path == self.path else repr(encoder.path.relative_to(self.graph.root).with_suffix("").as_posix().replace("/", "."))
                        encoder_refs.append(self.events_name + "._encoder(" + module + ", " + repr(encoder.name) + ")")
                encoder_tuple = "(" + ", ".join(encoder_refs) + ("," if encoder_refs else "") + ")"
                bind = ast.parse(self.events_name + "._bind_event(" + node.name + ", " + repr(event.name) + ", [" + fields_text + "], " + encoder_tuple + ")").body[0]
                return [result, bind]
            plan = class_planner(self.graph).plan(self.path, node)
            if plan is not None:
                node.decorator_list = [d for d in node.decorator_list if not class_planner(self.graph).export_marker(self.path, d)]
                self.uses_contracts = True
                body = []
                for item in node.body:
                    if isinstance(item, ast.AnnAssign) and isinstance(item.target, ast.Name) and item.target.id in plan.fields:
                        configuration = item.value or ast.Constant(value=None)
                        field = plan.fields[item.target.id]
                        # Reuse the subscription/Optional lowering already used by contract expressions.
                        value = ast.Call(func=ast.Attribute(value=ast.Name(id=self.contracts_name, ctx=ast.Load()), attr="_state_field", ctx=ast.Load()),
                                         args=[ast.Constant(value=field.attribute), item.annotation, configuration], keywords=[])
                        # Construct descriptors outside __build_class__'s extra VM
                        # frame to stay within Casper's 500 native stack slots.
                        target = ast.Attribute(value=ast.Name(id=node.name, ctx=ast.Load()), attr=item.target.id, ctx=ast.Store())
                        fields.append(ast.copy_location(ast.Assign(targets=[target], value=value), item))
                        continue
                    if isinstance(item, ast.FunctionDef) and item.name in plan.methods:
                        # Freeze metadata, preserving ordinary Python decorators.
                        item.decorator_list = [d for d in item.decorator_list if not class_planner(self.graph).marker(self.path, d)]
                    body.append(item)
                node.body = body or [ast.Pass()]
        if self.sdk:
            node.decorator_list = [d for d in node.decorator_list if not (isinstance(d, ast.Call) and isinstance(d.func, ast.Name) and d.func.id == "dataclass_transform")]
            bases = []
            for base in node.bases:
                origin = base.value if isinstance(base, ast.Subscript) else base
                if isinstance(origin, ast.Name) and origin.id == "Generic":
                    continue
                bases.append(origin)
            node.bases = bases
        result = self.generic_visit(node)
        return [result, *(self.visit(field) for field in fields)] if fields else result

    def visit_AnnAssign(self, node):
        if node.value is None:
            return None
        return ast.copy_location(
            ast.Assign(targets=[node.target], value=self.visit(node.value)), node
        )

    def visit_Assign(self, node):
        if (self.sdk and isinstance(node.value, ast.Call)
                and isinstance(node.value.func, ast.Name) and node.value.func.id in ("TypeVar", "ParamSpec")):
            return None
        if (not self.sdk and isinstance(node.value, ast.Call)
                and class_planner(self.graph).symbol(self.path, node.value.func) in ("typing.TypeVar", "typing.ParamSpec")):
            return None
        return self.generic_visit(node)

    def annotation_value(self, path, node, seen=()):
        """Resolve type expressions without executing contract or helper code."""
        if isinstance(node, ast.Constant):
            return node.value
        if (isinstance(node, ast.ClassDef) and len(node.bases) == 1
                and class_planner(self.graph).symbol(path, node.bases[0]) in ("casthon.enums.WireEnum", "casthon.WireEnum")):
            return self.graph.enum(path, node)
        if isinstance(node, ast.Call) and ast.dump(node) == ast.dump(ast.parse("type(None)", mode="eval").body):
            return type(None)
        if isinstance(node, ast.Name) and node.id not in self.graph.module(path)[1]:
            builtins = {"list": list, "dict": dict, "tuple": tuple, "int": int, "str": str,
                        "bytes": bytes, "bool": bool}
            if node.id in builtins:
                return builtins[node.id]
        if isinstance(node, (ast.Name, ast.Attribute)):
            owner, symbol = self.graph.resolve(path, node)
            if owner is not None:
                key = owner, ast.dump(symbol)
                if key in seen:
                    raise ValueError("Cyclic wire annotation")
                return self.annotation_value(owner, symbol, (*seen, key))
            if symbol in ("typing.Annotated", "typing.List", "typing.Dict", "typing.Optional", "typing.Union"):
                return {"typing.Annotated": Annotated, "typing.List": List,
                        "typing.Dict": Dict, "typing.Optional": Optional,
                        "typing.Union": Union}[symbol]
            if isinstance(symbol, str) and symbol.startswith(("casthon.", "casthon.types.", "casthon.key.")):
                name = symbol.rsplit(".", 1)[-1]
                value = getattr(casthon, name, None)
                if value is not None:
                    return value
        if isinstance(node, ast.Subscript):
            origin = self.annotation_value(path, node.value, seen)
            items = node.slice.elts if isinstance(node.slice, ast.Tuple) else [node.slice]
            args = tuple(self.annotation_value(path, item, seen) for item in items)
            if origin in (casthon.URef, casthon.Dictionary):
                return origin[args[0] if len(args) == 1 else args]
            if origin in (list, dict, tuple, List, Dict, Annotated, Optional, Union, casthon.OptionalArg, casthon.Map):
                return origin[args[0] if len(args) == 1 else args]
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.BitOr):
            args = (self.annotation_value(path, node.left, seen),
                    self.annotation_value(path, node.right, seen))
            if all(value is None or isinstance(value, type) or get_origin(value) is not None
                   for value in args):
                return Union[args]
        raise ValueError("Unsupported wire annotation: " + ast.unparse(node))

    def lower_optional(self, annotation):
        casthon.wire_type(annotation)
        inner = optional_inner(annotation)
        if inner is None:
            raise TypeError("Only nullable unions have a Casper wire type")
        self.optional_factory = True
        return ast.Call(func=ast.Name(id=self.optional_name, ctx=ast.Load()),
                        args=[ast.parse(frozen_annotation(inner, self.cspr_name, self.optional_name, self.argument_name,
                                                         self.enum_name, self.path), mode="eval").body], keywords=[])

    def visit_BinOp(self, node):
        if not self.sdk and isinstance(node.op, ast.BitOr):
            try:
                annotation = self.annotation_value(self.path, node)
            except (ValueError, TypeError):
                pass
            else:
                return ast.copy_location(self.lower_optional(annotation), node)
        return self.generic_visit(node)

    def visit_Subscript(self, node):
        if not self.sdk:
            try:
                origin = self.annotation_value(self.path, node.value)
            except ValueError:
                origin = None
                if isinstance(node.value, (ast.Name, ast.Attribute)):
                    try:
                        _, symbol = self.graph.resolve(self.path, node.value)
                    except ValueError:
                        symbol = None
                    if isinstance(symbol, str) and symbol.startswith("typing."):
                        raise TypeError("Unsupported frozen wire annotation: " + ast.unparse(node))
            if origin in (casthon.URef, casthon.Dictionary):
                args = node.slice.elts if isinstance(node.slice, ast.Tuple) else [node.slice]
                expected = 1 if origin is casthon.URef else 2
                if len(args) != expected:
                    raise TypeError("Incorrect number of storage type parameters")
                return ast.copy_location(ast.Call(
                    func=ast.Attribute(value=self.visit(node.value), attr="of", ctx=ast.Load()),
                    args=[self.visit(arg) for arg in args], keywords=[]), node)
            if origin in (Optional, Union):
                return ast.copy_location(self.lower_optional(self.annotation_value(self.path, node)), node)
            if origin is casthon.OptionalArg or origin is Annotated:
                annotation = self.annotation_value(self.path, node)
                inner = optional_arg_inner(annotation)
                if inner is not None:
                    casthon.wire_type(inner)
                    self.argument_factory, self.optional_factory = True, True
                    return ast.copy_location(ast.parse(frozen_annotation(annotation, self.cspr_name, self.optional_name,
                                                                        self.argument_name, self.enum_name, self.path), mode="eval").body, node)
            if origin in (list, dict, List, Dict, Annotated, casthon.Map):
                # Carry the type tree directly; no string grammar in frozen contracts.
                annotation = self.annotation_value(self.path, node)
                self.optional_factory = True
                return ast.copy_location(ast.parse(frozen_annotation(annotation, self.cspr_name, self.optional_name,
                    self.argument_name, self.enum_name, self.path), mode="eval").body, node)
        return self.generic_visit(node)

    def lower_sequence(self, node, constructor):
        # MicroPython's parser does not accept [*items] or (*items,).
        # Preserve shallow-copy semantics and left-to-right evaluation.
        if not any(isinstance(item, ast.Starred) for item in node.elts):
            return self.generic_visit(node)
        chunks, pending = [], []
        for item in node.elts:
            if isinstance(item, ast.Starred):
                if pending:
                    chunks.append(type(node)(elts=pending, ctx=ast.Load()))
                    pending = []
                chunks.append(ast.Call(func=ast.Name(id=constructor, ctx=ast.Load()),
                                       args=[self.visit(item.value)], keywords=[]))
            else:
                pending.append(self.visit(item))
        if pending:
            chunks.append(type(node)(elts=pending, ctx=ast.Load()))
        result = chunks[0]
        for chunk in chunks[1:]:
            result = ast.BinOp(left=result, op=ast.Add(), right=chunk)
        return ast.copy_location(result, node)

    def visit_List(self, node):
        if isinstance(node.ctx, ast.Store):
            return self.generic_visit(node)
        return self.lower_sequence(node, "list")

    def visit_Tuple(self, node):
        if isinstance(node.ctx, ast.Store):
            return self.generic_visit(node)
        return self.lower_sequence(node, "tuple")

    def visit_Call(self, node):
        if self.is_export(node.func):
            if len(node.args) != 1 or node.keywords:
                raise ValueError("export() requires one function reference")
            return self.visit(node.args[0])
        is_cast = self.sdk and isinstance(node.func, ast.Name) and node.func.id == "cast"
        if not self.sdk and isinstance(node.func, (ast.Name, ast.Attribute)):
            try:
                _, symbol = self.graph.resolve(self.path, node.func)
                is_cast = symbol == "typing.cast"
            except ValueError:
                pass
        if is_cast:
            return self.visit(node.args[1])
        if (
            self.sdk
            and isinstance(node.func, ast.Name)
            and node.func.id == "_host"
            and not node.args
            and not node.keywords
        ):
            return ast.copy_location(ast.Name(id="host", ctx=ast.Load()), node)
        return self.generic_visit(node)


def lower(path, sdk=False, project_root=None):
    path = Path(path).resolve()
    tree = ast.parse(path.read_text())
    if not sdk:
        check_profile(tree)
    tree = Lower(sdk, None if sdk else SourceGraph(project_root), path).visit(tree)
    return ast.unparse(ast.fix_missing_locations(tree)) + "\n"


def lower_enums(path):
    """Freeze SDK IntEnums without requiring the CPython enum module."""
    result = lower(ROOT / 'runtime/enums.py', sdk=True)
    for node in ast.parse(Path(path).read_text()).body:
        if not isinstance(node, ast.ClassDef) or node.name == "WireEnum":
            continue
        result += "\nclass " + node.name + "(WireEnum):\n    pass\n"
        for member in node.body:
            if not isinstance(member, ast.Assign) or len(member.targets) != 1:
                raise ValueError("SDK enum members must be integer declarations")
            name = member.targets[0].id
            value = ast.literal_eval(member.value)
            if type(value) is not int:
                raise ValueError("SDK enum values must be integers")
            result += f"{node.name}.{name} = {node.name}({value}, {name!r})\n"
    return result


class SourceGraph:
    """Resolve declarations and function references without importing Python."""

    def __init__(self, root=None):
        self.modules = {}
        self.enums = {}
        self.source = None
        self.root = Path(root or ROOT).resolve()

    def enum(self, path, node):
        path = Path(path).resolve()
        key = path, node.name
        if key not in self.enums:
            module = "contract" if path == self.source else path.relative_to(self.root).with_suffix("").as_posix().replace("/", ".")
            enum = casthon.WireEnum(node.name, enum_members(node), module=module)
            enum._cspr_source = path
            self.enums[key] = enum
        return self.enums[key]

    def module_path(self, name):
        if name != "contracts" and not name.startswith("contracts."):
            return None
        path = self.root / name.replace(".", "/")
        if path.with_suffix(".py").is_file():
            return path.with_suffix(".py").resolve()
        if (path / "__init__.py").is_file():
            return (path / "__init__.py").resolve()
        return None

    def module(self, path):
        path = Path(path).resolve()
        if self.source is None:
            self.source = path
        if path not in self.modules:
            tree = ast.parse(path.read_text())
            check_profile(tree)
            bindings = {}
            for node in tree.body:
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        bindings[alias.asname or alias.name.split(".")[0]] = (
                            alias.name if alias.asname else alias.name.split(".")[0]
                        )
                elif isinstance(node, ast.ImportFrom):
                    for alias in node.names:
                        if alias.name == "*":
                            raise ValueError("Use explicit contract imports")
                        bindings[alias.asname or alias.name] = node.module + "." + alias.name
                elif isinstance(node, (ast.FunctionDef, ast.ClassDef)):
                    bindings[node.name] = node
                elif isinstance(node, (ast.Assign, ast.AnnAssign)):
                    targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                    for target in targets:
                        if isinstance(target, ast.Name) and node.value is not None:
                            bindings[target.id] = node.value
            self.modules[path] = tree, bindings
        return self.modules[path]

    def resolve(self, path, value, seen=()):
        if isinstance(value, str):
            if self.module_path(value) is not None:
                return None, value
            if value.startswith("contracts."):
                module, name = value.rsplit(".", 1)
                imported = self.module_path(module)
                if imported is None:
                    raise ValueError("Missing local Python module: " + module)
                return self.resolve(imported, ast.Name(id=name), seen)
            return None, value
        if isinstance(value, ast.Name):
            key = path, value.id
            if key in seen:
                raise ValueError("Cyclic contract declaration: " + value.id)
            binding = self.module(path)[1].get(value.id)
            if binding is None:
                raise ValueError("Missing top-level contract binding: " + value.id)
            return self.resolve(path, binding, (*seen, key))
        if isinstance(value, ast.Attribute):
            _, parent = self.resolve(path, value.value, seen)
            if isinstance(parent, str):
                return self.resolve(path, parent + "." + value.attr, seen)
            raise ValueError("Expected a module-qualified contract declaration")
        return path, value

    def is_export(self, path, node):
        if not isinstance(node, (ast.Name, ast.Attribute)):
            return False
        try:
            _, symbol = self.resolve(path, node)
        except ValueError:
            return False
        return symbol == "casthon.export"

    def function(self, path, name):
        path, node = self.resolve(path, ast.Name(id=name))
        if isinstance(node, ast.Call) and self.is_export(path, node.func):
            if len(node.args) != 1 or node.keywords:
                raise ValueError("export() requires one function reference")
            path, node = self.resolve(path, node.args[0])
        if not isinstance(node, ast.FunctionDef):
            raise ValueError("Export must resolve to a top-level Python function: " + name)
        if (
            (any(self.is_export(path, decorator) for decorator in node.decorator_list)
             and not self.is_export(path, node.decorator_list[0]))
            or node.args.posonlyargs or node.args.vararg or node.args.kwarg
        ):
            raise ValueError("Exports require named parameters and outermost @export: " + name)
        return path, node


def frozen_annotation(annotation, module="_cspr", optional="_Optional", argument="_OptionalArg",
                      enum="_EnumRef", here=None):
    """Render a resolved annotation without depending on typing in Wasm."""
    presence = optional_arg_inner(annotation)
    if presence is not None:
        return argument + "(" + frozen_annotation(presence, module, optional, argument, enum, here) + ")"
    inner = optional_inner(annotation)
    if inner is not None:
        return optional + "(" + frozen_annotation(inner, module, optional, argument, enum, here) + ")"
    if isinstance(annotation, type) and issubclass(annotation, casthon.WireEnum):
        owner = "__name__" if here is not None and getattr(annotation, "_cspr_source", None) == here else repr(annotation.__module__)
        return enum + "(" + owner + ", " + repr(annotation.__name__) + ")"
    if isinstance(annotation, type) and issubclass(annotation, casthon.Key):
        return module + "." + annotation.__name__
    descriptor = casthon.cl_type_of(annotation)
    if descriptor.tag == 12 and descriptor.annotation is not None:
        return module + ".URef.of(" + frozen_annotation(descriptor.annotation.annotation, module, optional, argument, enum, here) + ")"
    if descriptor.children:
        children = ", ".join(frozen_annotation(child, module, optional, argument, enum, here) for child in descriptor.children)
        special = ", bytes" if descriptor.annotation is bytes else ""
        return module + ".CLType(" + str(descriptor.tag) + ", (" + children + ",)" + special + ")"
    if descriptor.annotation is not None and descriptor.annotation is not annotation:
        return frozen_annotation(descriptor.annotation, module, optional, argument, enum, here)
    return module + ".CLType(" + str(descriptor.tag) + ")"


def resolve_signature(graph, path, node, skip_self=False):
    resolver = Lower(graph=graph)

    def annotation(value, label):
        try:
            if isinstance(value, ast.Constant) and isinstance(value.value, str):
                try:
                    casthon.wire_type(value.value)
                except TypeError:
                    value = ast.parse(value.value, mode="eval").body
            return resolver.annotation_value(path, value)
        except (ValueError, TypeError, SyntaxError) as error:
            raise ValueError(f"Export {node.name}, {label}: {error}") from error

    if node.args.posonlyargs or node.args.vararg or node.args.kwarg:
        raise ValueError("Exports require named parameters without *args or **kwargs")
    parameters = []
    defaults = [False] * (len(node.args.args) - len(node.args.defaults)) + [True] * len(node.args.defaults)
    defaults += [value is not None for value in node.args.kw_defaults]
    arguments = [*node.args.args, *node.args.kwonlyargs]
    for parameter, has_default in list(zip(arguments, defaults))[int(skip_self):]:
        if parameter.annotation is None:
            raise ValueError(f"Export {node.name}, parameter {parameter.arg}: a wire annotation is required")
        parameters.append((parameter.arg, annotation(parameter.annotation, parameter.arg), has_default))
    returns = annotation(node.returns, "return") if node.returns is not None else None
    return normalize_signature(parameters, returns, node.returns is not None)


def event_planner(graph):
    from event_classes import EventPlanner
    if not hasattr(graph, "event_planner"):
        graph.event_planner = EventPlanner(graph, Lower(graph=graph).annotation_value)
    return graph.event_planner


def class_planner(graph):
    if not hasattr(graph, "_class_planner"):
        from contract_classes import ClassPlanner
        graph._class_planner = ClassPlanner(graph, Lower(graph=graph).annotation_value,
                                           lambda path, node, skip: resolve_signature(graph, path, node, skip))
    return graph._class_planner


def class_bindings(source, graph):
    bindings = {}
    for name, plan in class_planner(graph).selected(source):
        for method in plan.methods.values():
            if method.name in bindings:
                raise ValueError("Duplicate root export: " + method.name)
            bindings[method.name] = name, method
    return bindings


def export_signatures(source, exports, graph=None):
    graph = graph or SourceGraph()
    bindings = class_bindings(source, graph)
    signatures = {}
    for name in exports:
        if name in bindings:
            signatures[name] = bindings[name][1].signature
        else:
            path, node = graph.function(source, name)
            signatures[name] = resolve_signature(graph, path, node)
    return signatures


def render_signature(signature):
    parameters, typed, returns = signature
    args = ", ".join(f"({arg!r}, {frozen_annotation(annotation)}, {default!r})"
                     for arg, annotation, default in parameters)
    result = frozen_annotation(returns) if typed else "None"
    return f"([{args}], {typed!r}, {result})"


def generate_exports(source, exports, project_root=None):
    source = Path(source).resolve()
    graph = SourceGraph(project_root)
    bindings = class_bindings(source, graph)
    lines = ['"""Generated root exports and independent imported contract ABIs."""',
             'import casthon as _cspr', 'from casthon._wire_types import _Optional, _OptionalArg, _EnumRef', 'SIGNATURES = {']
    for name, signature in export_signatures(source, exports, graph).items():
        lines.append(f"    {name!r}: {render_signature(signature)},")
    lines.append("}")
    lines.append("BINDINGS = " + repr({name: (owner, method.attribute) for name, (owner, method) in bindings.items()}))
    lines.append("MODULE_SIGNATURES = {")
    schemas = []
    for filename, path in contract_modules(source, project_root).items():
        tree, _ = graph.module(path)
        # Class methods have their own references; this table is for ordinary functions.
        names = discover_exports(tree, lambda node: graph.is_export(path, node))
        module = filename.removesuffix(".py").removesuffix("/__init__").replace("/", ".")
        if names:
            lines.append(f"    {module!r}: ({{")
            signatures = export_signatures(path, names, graph)
            for name, signature in signatures.items():
                lines.append(f"        {name!r}: {render_signature(signature)},")
            lines.append("    }, {")
            for name in names:
                _, function = graph.function(path, name)
                lines.append(f"        {name!r}: {len(function.args.args)},")
            lines.append("    }),")
        for node in tree.body:
            if not isinstance(node, ast.ClassDef):
                continue
            plan = class_planner(graph).plan(path, node)
            if plan is None:
                continue
            entries = []
            for method in plan.methods.values():
                entries.append(f"({method.name!r}, {method.attribute!r}, {render_signature(method.signature)}, {method.positional!r}, " +
                               ", ".join(repr(value) for value in method.options) + ")")
            event_refs = [("contract" if event.path == source else event.path.relative_to(graph.root).with_suffix("").as_posix().replace("/", "."), event.node.name) for event in plan.events]
            schemas.append(f"    ({module!r}, {node.name!r}, {list(plan.fields)!r}, [" + ", ".join(entries) + f"], {event_refs!r}),")
    lines.extend(["}", "CLASS_SCHEMAS = [", *schemas, "]", ""])
    return "\n".join(lines)


def validate_name(name):
    if not re.fullmatch(r"[A-Za-z_]\w*", name, flags=re.ASCII):
        raise ValueError("Invalid Wasm export name: " + name)
    if name.startswith("__sf_"):
        raise ValueError("Wasm export prefix __sf_ is reserved for SoftFloat helpers: " + name)
    if name.startswith("asyncify_"):
        raise ValueError("Wasm export prefix asyncify_ is reserved for continuation controls: " + name)


def load_contract(path, project_root=None):
    source = Path(path).resolve()
    if source.suffix != ".py":
        raise ValueError("Contract source must be a Python file")
    graph = SourceGraph(project_root)
    tree, _ = graph.module(source)
    exports = discover_exports(tree, lambda node: graph.is_export(source, node))
    bindings = class_bindings(source, graph)
    if set(exports) & set(bindings):
        raise ValueError("Duplicate root export between a function and a contract class")
    exports.extend(bindings)
    if not exports:
        raise ValueError("Declare Wasm exports explicitly with @export or name = export(function)")
    for name in exports:
        validate_name(name)
    signatures = export_signatures(source, exports, graph)
    descriptions = {name: {"args": [{"name": arg, "type": casthon.wire_type(argument_type(annotation)), "hasDefault": default,
                                    **({"optionalArg": True} if optional_arg_inner(annotation) is not None else {})}
                                   for arg, annotation, default in parameters],
                           "returns": casthon.wire_type(returns) if typed else None}
                    for name, (parameters, typed, returns) in signatures.items()}
    return {"source": source.name, "exports": exports, "signatures": descriptions}, source


def contract_modules(source, project_root=None):
    """Bundle explicitly imported local helper modules without executing source."""
    source = Path(source).resolve()
    modules = {"contract.py": source}
    graph = SourceGraph(project_root)
    project_root = graph.root
    pending = [source]
    while pending:
        path = pending.pop()
        tree = ast.parse(path.read_text())
        check_profile(tree)
        imports = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imports.extend(a.name for a in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imports.append(node.module)
                if node.module == "contracts" or node.module.startswith("contracts."):
                    imports.extend(node.module + "." + alias.name for alias in node.names
                                   if graph.module_path(node.module + "." + alias.name))
        for module in imports:
            if module != "contracts" and not module.startswith("contracts."):
                continue
            dependency = graph.module_path(module)
            if dependency is None:
                raise ValueError("Missing local Python module: " + module)
            name = str(dependency.relative_to(project_root))
            if name not in modules:
                modules[name] = dependency
                pending.append(dependency)
            # Freeze package initializers too, including nested helper packages.
            for parent in dependency.parents:
                if parent == project_root:
                    break
                initializer = parent / "__init__.py"
                name = str(initializer.relative_to(project_root))
                if initializer.is_file() and name not in modules:
                    modules[name] = initializer
                    pending.append(initializer)
    if len(modules) > 1:
        modules["contracts/__init__.py"] = project_root / "contracts/__init__.py"
    return modules
