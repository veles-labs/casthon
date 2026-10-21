"""Inspect event records and encoder mixins without executing application code."""

import ast
from dataclasses import dataclass, field
from cspr._contract_schema import annotation_key
from cspr import cl_type_of, Event, Json


@dataclass
class EncoderPlan:
    path: object
    name: str
    ancestors: tuple
    concrete: bool = True
    attributes: set = field(default_factory=set)
    node: object = None

    @property
    def key(self):
        return self.path, self.name


@dataclass
class EventPlan:
    path: object
    node: object
    name: str
    fields: dict
    encoders: list
    order: list
    bases: list
    attributes: set

    @property
    def key(self):
        return self.path, self.node.name


class EventPlanner:
    def __init__(self, graph, annotation):
        self.graph, self.annotation = graph, annotation
        self.plans, self.active = {}, set()
        self.encoder_plans, self.encoder_active = {}, set()

    def encoder(self, path, node):
        if isinstance(node, str):
            parts = node.split('.')
            if '.'.join(parts[:-1]) not in ('cspr', 'cspr.events'):
                return None
            name = parts[-1]
            root = (None, 'MessageEncoder')
            if name == 'MessageEncoder':
                return EncoderPlan(None, name, (), False, {'to_message'})
            if name in ('Bytesrepr', 'Json'):
                return EncoderPlan(None, name, (root,), attributes={'to_message', 'json_field'} if name == 'Json' else {'to_message'})
            if name == 'JsonBytes':
                return EncoderPlan(None, name, ((None, 'Json'), root), attributes={'to_message'})
            return None
        if not isinstance(node, ast.ClassDef):
            return None
        key = path, node.name
        if key in self.encoder_plans:
            return self.encoder_plans[key]
        if key in self.encoder_active:
            raise ValueError('Cyclic message encoder inheritance')
        self.encoder_active.add(key)
        parents = []
        for base in node.bases:
            owner, target = self.graph.resolve(path, base)
            parent = self.encoder(owner, target)
            if parent is None:
                self.encoder_active.remove(key)
                self.encoder_plans[key] = None
                return None
            parents.append(parent)
        if not parents:
            self.encoder_active.remove(key)
            self.encoder_plans[key] = None
            return None
        if len(parents) != 1 or node.decorator_list or node.keywords:
            raise ValueError('Message encoders use single inheritance without class options')
        concrete = parents[0].concrete
        for item in node.body:
            if isinstance(item, ast.AnnAssign) or isinstance(item, ast.FunctionDef) and item.name == '__init__':
                raise ValueError('Message encoder mixins must be stateless')
            if isinstance(item, ast.FunctionDef) and item.name == 'to_message':
                if item.decorator_list or len(item.args.args) != 1 or item.args.args[0].arg != 'self' or item.args.vararg or item.args.kwarg or item.args.kwonlyargs:
                    raise ValueError('Encoder to_message must be an ordinary instance method taking self')
                concrete = True
        parent = parents[0]
        attributes = self.own_attributes(node)
        result = EncoderPlan(path, node.name, (parent.key, *parent.ancestors), concrete, attributes, node)
        self.encoder_active.remove(key)
        self.encoder_plans[key] = result
        return result

    def plan(self, path, node):
        key = path, node.name
        if key in self.plans:
            return self.plans[key]
        if key in self.active:
            raise ValueError('Cyclic event inheritance')
        self.active.add(key)
        parents, codecs, record_positions = [], [], []
        for index, base in enumerate(node.bases):
            owner, target = self.graph.resolve(path, base)
            if owner is None and target in ('cspr.Event', 'cspr.events.Event'):
                parents.append(None)
                record_positions.append(index)
                continue
            codec = self.encoder(owner, target)
            if codec is not None:
                codecs.append(codec)
                continue
            parent = self.plan(owner, target) if owner is not None and isinstance(target, ast.ClassDef) else None
            if parent is not None:
                parents.append(parent)
                record_positions.append(index)
        if not parents:
            self.active.remove(key)
            self.plans[key] = None
            return None
        if len(parents) != 1 or record_positions != [0] or len(node.bases) != 1 + len(codecs) or node.decorator_list or node.keywords:
            raise ValueError('Events require one record parent first, followed by stateless encoder mixins')
        if any(not codec.concrete for codec in codecs):
            raise ValueError('A message encoder must implement to_message()')
        for index, codec in enumerate(codecs):
            if any(previous.key == codec.key or previous.key in codec.ancestors for previous in codecs[:index]):
                raise ValueError('Inconsistent event encoder method resolution order')
        parent = parents[0]
        candidates = (parent.encoders if parent else []) + codecs
        encoders = []
        for codec in candidates:
            if not any(codec.key in other.ancestors for other in candidates) and codec.key not in [known.key for known in encoders]:
                encoders.append(codec)
        fields = dict(parent.fields) if parent else {}
        name = node.name
        for item in node.body:
            if isinstance(item, ast.FunctionDef) and item.name == '__init__':
                raise ValueError('Event constructors are generated from their annotated fields')
            if isinstance(item, ast.AnnAssign) and isinstance(item.target, ast.Name):
                field = item.target.id
                if field == 'self' or field.startswith('_') or hasattr(Event, field) or hasattr(Json, field):
                    raise ValueError('Reserved event field: ' + field)
                if item.value is not None:
                    raise ValueError('Event fields require explicit values; defaults are unsupported')
                annotation = self.annotation(path, item.annotation)
                cl_type_of(annotation)
                if field in fields and annotation_key(fields[field]) != annotation_key(annotation):
                    raise ValueError('Inherited event field types cannot change: ' + field)
                fields[field] = annotation
            if isinstance(item, ast.Assign) and any(isinstance(t, ast.Name) and t.id == '__event_name__' for t in item.targets):
                name = ast.literal_eval(item.value)
        if type(name) is not str or not name:
            raise ValueError('An event requires a nonempty wire name')
        bases = [parent.key if parent else (None, 'Event')] + [codec.key for codec in codecs]
        sequences = [self.order(base)[:] for base in bases] + [bases[:]]
        order = [key]
        while any(sequences):
            sequences = [seq for seq in sequences if seq]
            candidate = next((seq[0] for seq in sequences if not any(seq[0] in other[1:] for other in sequences)), None)
            if candidate is None:
                raise ValueError('Inconsistent event encoder method resolution order')
            order.append(candidate)
            for sequence in sequences:
                if sequence[0] == candidate:
                    sequence.pop(0)
        result = EventPlan(path, node, name, fields, encoders, order, bases, self.own_attributes(node))
        self.active.remove(key)
        self.plans[key] = result
        self.validate_lookup(result)
        return result

    def own_attributes(self, node):
        attributes = {item.name for item in node.body if isinstance(item, ast.FunctionDef)}
        for item in node.body:
            if isinstance(item, ast.Assign):
                attributes.update(target.id for target in item.targets if isinstance(target, ast.Name))
        return attributes - {'__module__', '__doc__', '__qualname__', '_event_schema'}

    def encoder_key(self, key):
        if key[0] is None:
            return self.encoder(None, 'cspr.events.' + key[1])
        return self.encoder_plans.get(key)

    def order(self, key):
        if key == (None, 'Event'):
            return [key]
        record = self.plans.get(key)
        if record is not None:
            return record.order
        codec = self.encoder_key(key)
        return [key, *codec.ancestors]

    def namespace(self, key):
        if key == (None, 'Event'):
            return set(vars(Event)) - {'__dict__', '__weakref__', '__module__', '__doc__', '__qualname__', '__annotations__', '__annotate__', '__static_attributes__', '__firstlineno__', '_event_schema'}
        record = self.plans.get(key)
        return record.attributes if record is not None else self.encoder_key(key).attributes

    def bases(self, key):
        if key == (None, 'Event'):
            return []
        record = self.plans.get(key)
        if record is not None:
            return record.bases
        codec = self.encoder_key(key)
        return list(codec.ancestors[:1])

    def dfs(self, key):
        return [key] + [item for base in self.bases(key) for item in self.dfs(base)]

    def validate_lookup(self, record):
        micro = self.dfs(record.key)
        for name in set().union(*(self.namespace(key) for key in record.order)):
            normal = next((key for key in record.order if name in self.namespace(key)), None)
            actual = next((key for key in micro if name in self.namespace(key)), None)
            if normal != actual:
                raise ValueError('MicroPython event inheritance would resolve differently: ' + name)
        for key in record.order:
            if key[0] is None:
                continue
            owner = self.plans.get(key) or self.encoder_key(key)
            for part in ast.walk(owner.node):
                if isinstance(part, ast.Attribute) and isinstance(part.value, ast.Call) and isinstance(part.value.func, ast.Name) and part.value.func.id == 'super':
                    normal = next((base for base in record.order[record.order.index(key) + 1:] if part.attr in self.namespace(base)), None)
                    actual = next((base for parent in self.bases(key) for base in self.dfs(parent) if part.attr in self.namespace(base)), None)
                    if part.value.args or part.value.keywords or normal != actual:
                        raise ValueError('MicroPython event super() would resolve differently: ' + part.attr)

    def declaration(self, path, node):
        owner, target = self.graph.resolve(path, node)
        if not isinstance(target, ast.Tuple):
            raise ValueError('Contract events must be a tuple of Event classes')
        result = []
        for element in target.elts:
            event_path, event_node = self.graph.resolve(owner, element)
            plan = self.plan(event_path, event_node) if isinstance(event_node, ast.ClassDef) else None
            if plan is None:
                raise ValueError('Contract events must contain Event subclasses')
            result.append(plan)
        return result
