"""Fold the explicit const_blake2b intrinsic without executing application code."""
import ast

import casthon

INTRINSIC = "casthon.const_blake2b"


class LocalNames(ast.NodeVisitor):
    """Bindings in one lexical scope, excluding nested function/class bodies."""
    def __init__(self):
        self.names = set()
        self.modules = {}

    def visit_Name(self, node):
        if isinstance(node.ctx, (ast.Store, ast.Del)):
            self.names.add(node.id)

    def visit_FunctionDef(self, node):
        self.names.add(node.name)

    visit_AsyncFunctionDef = visit_FunctionDef
    visit_ClassDef = visit_FunctionDef

    def visit_Lambda(self, node):
        pass

    def visit_Import(self, node):
        for alias in node.names:
            name = alias.asname or alias.name.split(".")[0]
            self.names.add(name)
            self.modules[name] = alias.name if alias.asname else alias.name.split(".")[0]

    def visit_ImportFrom(self, node):
        self.names.update(alias.asname or alias.name for alias in node.names)


class FoldConstantHashes(ast.NodeTransformer):
    def __init__(self, graph, path):
        self.graph, self.path = graph, path
        self.scopes = []
        self.local_modules = []

    def is_intrinsic(self, node):
        if not isinstance(node, (ast.Name, ast.Attribute)):
            return False
        try:
            _, symbol = self.graph.resolve(self.path, node)
        except ValueError:
            return False
        if symbol != INTRINSIC:
            return False
        root = node
        while isinstance(root, ast.Attribute):
            root = root.value
        if isinstance(root, ast.Name) and any(root.id in names for names in self.scopes):
            raise ValueError(f"Line {node.lineno}: const_blake2b imports cannot be shadowed")
        return True

    def visit_Call(self, node):
        if self.is_intrinsic(node.func):
            if (len(node.args) != 1 or node.keywords
                    or not isinstance(node.args[0], ast.Constant)
                    or type(node.args[0].value) not in (str, bytes)):
                raise ValueError(f"Line {node.lineno}: const_blake2b requires one literal str or bytes argument")
            return ast.copy_location(ast.Constant(value=casthon.const_blake2b(node.args[0].value)), node)
        return self.generic_visit(node)

    def visit_Name(self, node):
        if isinstance(node.ctx, ast.Load) and self.is_intrinsic(node):
            raise ValueError(f"Line {node.lineno}: const_blake2b must be called directly with a literal")
        return node

    def visit_Attribute(self, node):
        if isinstance(node.ctx, ast.Load) and self.is_intrinsic(node):
            raise ValueError(f"Line {node.lineno}: const_blake2b must be called directly with a literal")
        if (node.attr == "const_blake2b" and self.scopes
                and isinstance(node.value, ast.Name)
                and any(modules.get(node.value.id) == "casthon" for modules in self.local_modules)):
            raise ValueError(f"Line {node.lineno}: const_blake2b requires a module-level import")
        return self.generic_visit(node)

    def visit_ImportFrom(self, node):
        if node.module == "casthon":
            for alias in node.names:
                if alias.name == "const_blake2b":
                    _, symbol = self.graph.resolve(self.path, ast.Name(id=alias.asname or alias.name))
                    if symbol != INTRINSIC:
                        raise ValueError(f"Line {node.lineno}: const_blake2b imports cannot be rebound")
        if (self.scopes and node.module == "casthon"
                and any(alias.name == "const_blake2b" for alias in node.names)):
            raise ValueError(f"Line {node.lineno}: const_blake2b requires a module-level import")
        node.names = [alias for alias in node.names
                      if not self.is_intrinsic(ast.copy_location(
                          ast.Name(id=alias.asname or alias.name, ctx=ast.Load()), node))]
        return node if node.names else None

    def visit_FunctionDef(self, node):
        local = LocalNames()
        for statement in node.body:
            local.visit(statement)
        local.names.update(arg.arg for arg in (*node.args.posonlyargs, *node.args.args, *node.args.kwonlyargs))
        if node.args.vararg:
            local.names.add(node.args.vararg.arg)
        if node.args.kwarg:
            local.names.add(node.args.kwarg.arg)
        self.scopes.append(local.names)
        self.local_modules.append(local.modules)
        try:
            return self.generic_visit(node)
        finally:
            self.scopes.pop()
            self.local_modules.pop()

    def visit_Lambda(self, node):
        local = {arg.arg for arg in (*node.args.posonlyargs, *node.args.args, *node.args.kwonlyargs)}
        if node.args.vararg:
            local.add(node.args.vararg.arg)
        if node.args.kwarg:
            local.add(node.args.kwarg.arg)
        self.scopes.append(local)
        self.local_modules.append({})
        try:
            return self.generic_visit(node)
        finally:
            self.scopes.pop()
            self.local_modules.pop()

    def visit_ClassDef(self, node):
        local = LocalNames()
        for statement in node.body:
            local.visit(statement)
        self.scopes.append(local.names)
        self.local_modules.append(local.modules)
        try:
            return self.generic_visit(node)
        finally:
            self.scopes.pop()
            self.local_modules.pop()
