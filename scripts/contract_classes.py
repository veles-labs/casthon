"""Static class-contract schemas and checks for upstream MicroPython inheritance."""

import ast
from dataclasses import dataclass

import casthon
from casthon.references import URefType, DictionaryType
from casthon._contract_schema import state_key, signature_key
from casthon.contracts import _property_annotation

ROOT = (None, "Contract")
ROOT_ATTRIBUTES = {"__init__", "bind", "named_keys", "entry_points", "_cspr_schema", "event_types"}


@dataclass
class Field:
    attribute: str
    name: str
    annotation: object
    configuration: object
    value_property: bool


@dataclass
class Method:
    attribute: str
    name: str
    path: object
    node: object
    signature: object
    positional: int
    options: tuple


@dataclass
class Plan:
    path: object
    node: object
    bases: list
    order: list
    fields: dict
    methods: dict
    attributes: set
    events: list
    own_events: list

    @property
    def key(self):
        return self.path, self.node.name


class ClassPlanner:
    def __init__(self, graph, annotation, signature):
        self.graph, self.annotation, self.signature = graph, annotation, signature
        self.plans, self.active = {}, set()

    def symbol(self, path, node):
        try:
            owner, value = self.graph.resolve(path, node)
        except ValueError:
            return None
        return value if owner is None else None

    def marker(self, path, node):
        return self.symbol(path, node.func if isinstance(node, ast.Call) else node) == "casthon.contracts.entry_point"

    def export_marker(self, path, node):
        return self.symbol(path, node.func if isinstance(node, ast.Call) else node) == "casthon.contracts.export_contract"

    def options(self, path, node):
        values = dict(name=None, access=casthon.EntryPointAccess.PUBLIC, groups=(),
                      entry_point_type=casthon.EntryPointType.CALLED, payment=casthon.EntryPointPayment.CALLER)
        if isinstance(node, ast.Call):
            if node.args:
                raise ValueError("@entry_point options must be keyword arguments")
            for keyword in node.keywords:
                if keyword.arg not in values:
                    raise ValueError("Unsupported entrypoint option: " + str(keyword.arg))
                try:
                    value = ast.literal_eval(keyword.value)
                except ValueError:
                    symbol = self.symbol(path, keyword.value)
                    parts = symbol.split(".") if isinstance(symbol, str) else []
                    if len(parts) < 3 or parts[-2] not in ("EntryPointAccess", "EntryPointType", "EntryPointPayment"):
                        raise ValueError("Entrypoint options must be literals or Casper enums")
                    value = getattr(getattr(casthon, parts[-2]), parts[-1])
                values[keyword.arg] = value
        if values["name"] is not None and not isinstance(values["name"], str):
            raise ValueError("An entrypoint name must be a string")
        if not isinstance(values["groups"], (list, tuple)) or not all(isinstance(x, str) for x in values["groups"]):
            raise ValueError("Entrypoint groups must be string literals")
        return values["name"], (int(values["access"]), tuple(values["groups"]),
                                int(values["entry_point_type"]), int(values["payment"]))

    def field(self, path, node):
        configuration = node.value
        is_property = (isinstance(configuration, ast.Call) and
                       self.symbol(path, configuration.func) == "casthon.contract_api.runtime.named_keys.property")
        try:
            annotation = self.annotation(path, node.annotation)
        except (ValueError, TypeError):
            # Non-storage annotations, including ClassVar, remain Python data.
            if is_property or (isinstance(node.annotation, ast.Subscript) and
                               self.symbol(path, node.annotation.value) in (
                                   "casthon.URef", "casthon.Dictionary", "casthon.key.URef", "casthon.references.Dictionary")):
                raise
            return None
        if not (is_property or isinstance(annotation, (URefType, DictionaryType)) or
                isinstance(annotation, type) and issubclass(annotation, casthon.Key)):
            return None
        if annotation is casthon.URef:
            raise ValueError("State URefs require a value type: URef[T]")
        name = node.target.id
        if configuration is not None:
            if not isinstance(configuration, ast.Call) or self.symbol(path, configuration.func) not in (
                    "casthon.contract_api.runtime.named_keys.reference",
                    "casthon.contract_api.runtime.named_keys.property"):
                raise ValueError("Annotated state requires named_keys.reference(...) or named_keys.property(...)")
            if len(configuration.args) > 1:
                raise ValueError("The state annotation already supplies its type")
            keywords = {kw.arg: kw.value for kw in configuration.keywords}
            if len(keywords) != len(configuration.keywords):
                raise ValueError("Duplicate state configuration option")
            if set(keywords) - ({"name", "key", "uref"} if is_property else {"name", "key"}):
                raise ValueError("Unsupported state reference configuration")
            if is_property:
                annotation = _property_annotation(annotation, ast.literal_eval(keywords["uref"]) if "uref" in keywords else False)
            if configuration.args and "name" in keywords:
                raise ValueError("Multiple storage names supplied")
            name_node = configuration.args[0] if configuration.args else keywords.get("name")
            if name_node is not None:
                configured_name = ast.literal_eval(name_node)
                if configured_name is not None:
                    name = configured_name
            key_node = keywords.get("key")
            has_key = key_node is not None and not (isinstance(key_node, ast.Constant) and key_node.value is None)
            if has_key and not isinstance(annotation, DictionaryType):
                raise ValueError("key= is only valid for dictionary state")
            if has_key and isinstance(key_node, ast.Constant):
                raise ValueError("Dictionary key transform must be callable")
        else:
            has_key = False
        if not isinstance(name, str) or not name:
            raise ValueError("State requires a nonempty storage name")
        if isinstance(annotation, DictionaryType) and annotation.key_type is not str and not has_key:
            raise ValueError("A non-string dictionary key requires key=callable")
        return Field(node.target.id, name, annotation, configuration, is_property)

    def plan(self, path, node):
        key = path, node.name
        if key in self.plans:
            return self.plans[key]
        if key in self.active:
            raise ValueError("Cyclic contract inheritance")
        self.active.add(key)
        bases = []
        for base in node.bases:
            owner, target = self.graph.resolve(path, base)
            if owner is None and target == "casthon.contracts.Contract":
                bases.append(ROOT)
            elif owner is not None and isinstance(target, ast.ClassDef):
                parent = self.plan(owner, target)
                if parent is None:
                    self.active.remove(key)
                    self.plans[key] = None
                    return None
                bases.append(parent.key)
            else:
                self.active.remove(key)
                self.plans[key] = None
                return None
        if not bases:
            self.active.remove(key)
            self.plans[key] = None
            return None
        sequences = [list(self.plans[base].order) if base != ROOT else [ROOT] for base in bases] + [list(bases)]
        mro = [key]
        while any(sequences):
            sequences = [seq for seq in sequences if seq]
            candidate = next((seq[0] for seq in sequences if not any(seq[0] in other[1:] for other in sequences)), None)
            if candidate is None:
                raise ValueError("Inconsistent contract method resolution order")
            mro.append(candidate)
            for seq in sequences:
                if seq and seq[0] == candidate:
                    seq.pop(0)
        fields, methods, attributes = {}, {}, set()
        for base in reversed(mro[1:]):
            if base == ROOT:
                continue
            for name, field in self.plans[base].fields.items():
                if name in fields and (field.name != fields[name].name or field.value_property != fields[name].value_property or state_key(field.annotation) != state_key(fields[name].annotation)):
                    raise ValueError("Inherited state schemas cannot be changed: " + name)
                fields[name] = field
            for name, method in self.plans[base].methods.items():
                if name in methods and (signature_key(method.signature) != signature_key(methods[name].signature) or method.positional != methods[name].positional):
                    raise ValueError("Inherited entrypoints have conflicting wire signatures: " + name)
                methods[name] = method
        for item in node.body:
            if isinstance(item, ast.AnnAssign) and isinstance(item.target, ast.Name):
                attributes.add(item.target.id)
                field = self.field(path, item)
                if field is not None:
                    if field.attribute in fields and (field.name != fields[field.attribute].name or field.value_property != fields[field.attribute].value_property or state_key(field.annotation) != state_key(fields[field.attribute].annotation)):
                        raise ValueError("Inherited state schemas cannot be changed: " + field.attribute)
                    fields[field.attribute] = field
                elif item.target.id in fields:
                    raise ValueError("An inherited state field cannot be hidden")
            elif isinstance(item, ast.FunctionDef):
                attributes.add(item.name)
                if item.name in fields:
                    raise ValueError("An inherited state field cannot be hidden")
                markers = [d for d in item.decorator_list if self.marker(path, d)]
                if len(markers) > 1:
                    raise ValueError("Duplicate @entry_point marker")
                inherited = methods.get(item.name)
                if markers or inherited:
                    if markers and item.decorator_list[0] is not markers[0]:
                        raise ValueError("@entry_point must be the outermost method decorator")
                    if not item.args.args or item.args.args[0].arg != "self":
                        raise ValueError("Entrypoint methods require self as their first parameter")
                    signature = self.signature(path, item, True)
                    positional = len(item.args.args) - 1
                    if not signature[1]:
                        raise ValueError("Class entrypoints require a wire return annotation, including -> None")
                    if inherited and (signature_key(signature) != signature_key(inherited.signature) or positional != inherited.positional):
                        raise ValueError("An inherited entrypoint cannot change its wire signature: " + item.name)
                    name, options = self.options(path, markers[0]) if markers else (inherited.name, inherited.options)
                    methods[item.name] = Method(item.name, name or item.name, path, item, signature, positional, options)
            elif isinstance(item, ast.Assign):
                if (isinstance(item.value, ast.Call) and
                        self.symbol(path, item.value.func) == "casthon.contract_api.runtime.named_keys.property"):
                    raise ValueError("State properties require a value annotation")
                attributes.update(target.id for target in item.targets if isinstance(target, ast.Name))
                if any(isinstance(target, ast.Name) and target.id in fields for target in item.targets):
                    raise ValueError("An inherited state field cannot be hidden")
                if any(isinstance(target, ast.Name) and target.id in methods for target in item.targets):
                    raise ValueError("An inherited entrypoint must remain an instance method")
        if set(fields) & set(methods):
            raise ValueError("State fields and entrypoints cannot share an attribute")
        if len({field.name for field in fields.values()}) != len(fields):
            raise ValueError("Different state fields use the same named key")
        if len({method.name for method in methods.values()}) != len(methods):
            raise ValueError("Duplicate class entrypoint name")
        from bundle import event_planner
        own_events = []
        for item in node.body:
            targets = item.targets if isinstance(item, ast.Assign) else [item.target] if isinstance(item, ast.AnnAssign) else []
            if any(isinstance(target, ast.Name) and target.id == "events" for target in targets):
                own_events = event_planner(self.graph).declaration(path, item.value)
        events, names = [], {}
        for declaration in [self.plans[base].own_events for base in reversed(mro[1:]) if base != ROOT] + [own_events]:
            for event in declaration:
                identity = event.path, event.node.name
                if event.name in names and names[event.name] != identity:
                    raise ValueError("Different event classes share a wire name: " + event.name)
                if event.name not in names:
                    names[event.name] = identity
                    events.append(event)
        attributes.discard("events")
        plan = Plan(path, node, bases, mro, fields, methods, attributes, events, own_events)
        self.plans[key] = plan
        self.active.remove(key)
        self.validate_lookup(plan)
        return plan

    def namespace(self, key):
        return ROOT_ATTRIBUTES if key == ROOT else self.plans[key].attributes

    def dfs(self, key):
        result = [key]
        if key != ROOT:
            for base in self.plans[key].bases:
                result.extend(self.dfs(base))
        return result

    def validate_lookup(self, plan):
        dfs = self.dfs(plan.key)
        attributes = set().union(*(self.namespace(key) for key in plan.order))
        for name in attributes:
            normal = next((key for key in plan.order if name in self.namespace(key)), None)
            micro = next((key for key in dfs if name in self.namespace(key)), None)
            if normal != micro:
                raise ValueError("MicroPython inheritance would resolve differently: " + name)
        for owner in plan.order:
            if owner == ROOT:
                continue
            node = self.plans[owner].node
            for part in ast.walk(node):
                if not (isinstance(part, ast.Attribute) and isinstance(part.value, ast.Call)
                        and isinstance(part.value.func, ast.Name) and part.value.func.id == "super"):
                    continue
                if part.value.args or part.value.keywords:
                    raise ValueError("Contract super calls must use super().method(...)")
                normal = next((key for key in plan.order[plan.order.index(owner) + 1:] if part.attr in self.namespace(key)), None)
                parent_dfs = [key for base in self.plans[owner].bases for key in self.dfs(base)]
                micro = next((key for key in parent_dfs if part.attr in self.namespace(key)), None)
                if normal != micro:
                    raise ValueError("MicroPython super() would resolve differently: " + part.attr)

    def selected(self, path):
        result = []
        for node in self.graph.module(path)[0].body:
            if isinstance(node, ast.ClassDef):
                markers = [decorator for decorator in node.decorator_list if self.export_marker(path, decorator)]
                if not markers:
                    continue
                if len(markers) != 1 or isinstance(markers[0], ast.Call):
                    raise ValueError("Use a single @export_contract without parentheses")
                name, owner, cls = node.name, path, node
            elif isinstance(node, ast.Expr) and isinstance(node.value, ast.Call) and self.export_marker(path, node.value.func):
                if len(node.value.args) != 1 or node.value.keywords:
                    raise ValueError("export_contract() requires one contract class")
                owner, cls = self.graph.resolve(path, node.value.args[0])
                # The selected class must have a root binding for dispatcher lookup.
                if not isinstance(node.value.args[0], ast.Name):
                    raise ValueError("Bind an imported contract class to a root name before exporting it")
                name = node.value.args[0].id
            else:
                continue
            if owner is None or not isinstance(cls, ast.ClassDef):
                raise ValueError("export_contract requires a Contract subclass")
            plan = self.plan(owner, cls)
            if plan is None:
                raise ValueError("export_contract requires a Contract subclass")
            result.append((name, plan))
        return result
