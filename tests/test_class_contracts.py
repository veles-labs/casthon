"""Annotated state, inherited ABIs, local calls and ownership/pause policy."""

from contextlib import contextmanager
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

from casthon import ABIError, AccountHash, ContractHash, CLKey, CLU32, U32, URef, MissingKey, UserError
from casthon.contracts import Contract, _schema
from casthon._contract_schema import signature_key
from casthon._signatures import module_export_names
from casthon.contract_api.runtime import named_keys
from casthon.entry_points import serialize_entry_points
from casthon.testing import ContractHarness, MockHost, use_host
from contracts import counter
from contracts.counter import Counter
from contracts.ownable import Ownable, NotOwner
from contracts.pausable import Pausable, Paused

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from bundle import load_contract, generate_exports, lower


@contextmanager
def class_pair(source):
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / 'class_fixture.py'
        path.write_text(source)
        declaration, _ = load_contract(path)
        author = types.ModuleType('class_fixture')
        author.__file__ = str(path)
        with patch.dict(sys.modules, {'class_fixture': author}):
            exec(compile(source, str(path), 'exec'), vars(author))
            _schema(author.Example)
            frozen = types.ModuleType('contract')
            frozen.__file__ = str(path)
            exports = types.ModuleType('_cspr_exports')
            exec(generate_exports(path, declaration['exports']), vars(exports))
            provider = types.ModuleType('casthon._contract_schema')
            exec(lower(ROOT / 'runtime/contract_schema.py', sdk=True), vars(provider))
            lowered = lower(path)
            with patch.dict(sys.modules, {'contract': frozen, '_cspr_exports': exports,
                                         'casthon._contract_schema': provider}):
                exec(compile(lowered, str(path), 'exec'), vars(frozen))
                yield author, frozen, exports


class ClassContractTests(unittest.TestCase):
    def setUp(self):
        self.alice = AccountHash(bytes([1]) * 32)
        self.bob = AccountHash(bytes([2]) * 32)
        self.host = MockHost(caller=self.alice, strict_arguments=True)
        self.session = ContractHarness(counter, host=self.host)

    def install(self, initial=0):
        self.session.invoke('call', {'initial': CLU32(initial)})
        key = self.host.accounts[self.alice]['py_counter']
        return ContractHarness(Counter, host=self.host, contract=key)

    def test_export_contract_decorator_selects_inherited_methods_and_is_erased(self):
        for imports, marker in (
            ('from casthon.contracts import export_contract as publish', 'publish'),
            ('import casthon.contracts as contracts_api', 'contracts_api.export_contract'),
        ):
            source = '''from casthon import URef, U32
from casthon.contracts import Contract, entry_point
''' + imports + '''
class Base(Contract):
    count: URef[U32]
    @entry_point
    def get(self) -> U32: return self.count.read()
@''' + marker + '''
class Example(Base): pass
'''
            with self.subTest(marker=marker), class_pair(source) as (author, frozen, exports):
                self.assertEqual(module_export_names(author), ['get'])
                self.assertEqual(exports.BINDINGS, {'get': ('Example', 'get')})
                lowered = lower(Path(author.__file__))
                self.assertNotIn('@' + marker, lowered)
                for cls in (author.Example, frozen.Example):
                    with use_host(MockHost()):
                        self.assertEqual(cls(count=7).get(), 7)
                self.assertEqual(serialize_entry_points(author.Example.entry_points()), serialize_entry_points(frozen.Example.entry_points()))

    def test_explicit_marker_still_selects_an_imported_decorated_class(self):
        source = '''from contracts.counter import Counter as Token
from casthon.contracts import export_contract
export_contract(Token)
'''
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'imported.py'
            path.write_text(source)
            declaration, _ = load_contract(path)
            self.assertEqual(set(declaration['exports']), {point.name for point in Counter.entry_points()})
            metadata = {}
            exec(generate_exports(path, declaration['exports']), metadata)
            self.assertTrue(all(owner == 'Token' for owner, method in metadata['BINDINGS'].values()))
            module = types.ModuleType('imported')
            module.__file__ = str(path)
            with patch.dict(sys.modules, {'imported': module}):
                exec(compile(source, str(path), 'exec'), vars(module))
                self.assertEqual(module_export_names(module), declaration['exports'])

    def test_invalid_or_duplicate_class_export_decorators_are_rejected(self):
        definitions = (
            '@export_contract\nclass Example: pass\n',
            '@export_contract()\nclass Example(Contract): pass\n',
            '@export_contract\n@export_contract\nclass Example(Contract): pass\n',
            '@export_contract\nclass Example(Contract):\n    @entry_point\n    def get(self) -> U32: return 0\nexport_contract(Example)\n',
        )
        for definition in definitions:
            source = 'from casthon import U32\nfrom casthon.contracts import Contract, entry_point, export_contract\n' + definition
            with self.subTest(definition=definition), tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / 'invalid.py'
                path.write_text(source)
                with self.assertRaises(ValueError):
                    load_contract(path)
                if '@export_contract()' in definition:
                    continue  # Python itself rejects the missing decorator argument.
                module = types.ModuleType('invalid')
                module.__file__ = str(path)
                with patch.dict(sys.modules, {'invalid': module}):
                    exec(compile(source, str(path), 'exec'), vars(module))
                    with self.assertRaises(ValueError):
                        module_export_names(module)

    def test_declarations_and_binding_do_not_touch_the_host(self):
        Counter.bind()
        self.assertEqual(self.host.calls, [])
        self.assertEqual([field.name for field in _schema(Counter).fields], ['owner', 'paused', 'count', 'increments'])
        self.assertTrue(issubclass(Counter, Pausable))
        self.assertTrue(issubclass(Pausable, Ownable))

    def test_harness_binds_a_fresh_instance_without_repeating_the_constructor(self):
        source = '''from casthon import URef, U32
from casthon.contracts import Contract, entry_point, export_contract
class Example(Contract):
    count: URef[U32]
    def __init__(self, initial: U32):
        super().__init__(count=initial)
        self.count.write(self.count.read() + 1)
        self.temporary = 100
    @entry_point
    def get(self) -> U32:
        self.temporary = getattr(self, "temporary", 0) + 1
        return self.count.read() + self.temporary
export_contract(Example)
'''
        with class_pair(source) as (author, frozen, exports):
            for target in (author, author.Example):
                host = MockHost()
                with use_host(host):
                    created = author.Example(7)
                    self.assertEqual(created.count.read(), 8)
                    self.assertEqual(created.temporary, 100)
                    named_keys['count'] = created.named_keys['count']
                harness = ContractHarness(target, host=host)
                allocated = len(host.cells)
                self.assertEqual(harness.invoke('get').value, 9)
                self.assertEqual(harness.invoke('get').value, 9)
                self.assertEqual(len(host.cells), allocated)

    def test_initialization_allocates_state_without_account_bindings(self):
        with use_host(self.host):
            instance = Counter(7)
            keys = instance.named_keys
            self.assertEqual(instance.get(), 7)
            self.assertEqual(instance.get_owner(), self.alice)
            self.assertIs(instance.is_paused(), False)
        self.assertEqual(set(keys), {'owner', 'paused', 'count', 'increments'})
        self.assertEqual(self.host.accounts.get(self.alice, {}), {})
        self.assertTrue(all(isinstance(key, URef) for key in keys.values()))

    def test_new_instances_keep_independent_state_beside_existing_named_keys(self):
        from casthon.contract_api.storage import new_uref

        with use_host(self.host):
            named_keys['count'] = new_uref(CLU32(99))
            first, second = Counter(3), Counter(7, owner=self.bob, paused=True)
            first.increment_by(2)
            self.assertEqual(first.get(), 5)
            self.assertEqual(second.get(), 7)
            self.assertEqual(second.get_owner(), self.bob)
            self.assertIs(second.is_paused(), True)
            self.assertEqual(Counter.bind().get(), 99)
            self.assertEqual(first.get_increments(self.alice), 2)
            self.assertEqual(second.get_increments(self.alice), 0)
            self.assertEqual(set(named_keys), {'count'})

    def test_field_write_preserves_the_uref_and_updates_existing_capabilities(self):
        contract = self.install(3)
        with self.host.context(contract=contract.contract), use_host(self.host):
            instance = Counter.bind()
            original = instance.count
            addresses = set(self.host.cells)
            instance.count.write(11)
            self.assertIsInstance(original, URef)
            self.assertEqual(named_keys['count'], original)
            self.assertEqual(set(self.host.cells), addresses)
            self.assertEqual(original.read(), 11)
            self.assertEqual(instance.count.read(), 11)
            instance.count.write(12)
            self.assertEqual(original.read(), 12)
            self.assertEqual(set(self.host.cells), addresses)
        with self.host.context(contract=contract.contract), use_host(self.host):
            self.assertEqual(original.read(), 12)

    def test_field_write_keeps_constructor_state_isolated_and_validates_before_mutation(self):
        from casthon.contract_api.storage import new_uref

        with use_host(self.host):
            named_keys['count'] = new_uref(CLU32(99))
            first, second = Counter(3), Counter(7)
            original = first.count
            addresses = set(self.host.cells)
            first.count.write(11)
            self.assertEqual(first.named_keys['count'], original)
            self.assertEqual(set(self.host.cells), addresses)
            self.assertEqual(first.get(), 11)
            self.assertEqual(second.get(), 7)
            self.assertEqual(Counter.bind().get(), 99)
            self.assertEqual(original.read(), 11)
            cells = self.host.cells.copy()
            with self.assertRaises((TypeError, ABIError)):
                first.count.write('bad')
            self.assertEqual(self.host.cells, cells)
            self.assertEqual(first.get(), 11)

    def test_constructor_failure_runs_finally_then_rolls_back_the_invocation(self):
        cleanup = []

        class Failing(Counter):
            def __init__(self):
                super().__init__(7)
                try:
                    self.increment()
                    raise UserError(79)
                finally:
                    self.count.write(9)
                    cleanup.append(self.count.read())

        def install() -> None:
            Failing()

        session = ContractHarness(types.ModuleType('failure'), host=self.host, exports={'call': install})
        with self.assertRaises(UserError):
            session.invoke('call')
        self.assertEqual(cleanup, [9])
        self.assertEqual(self.host.cells, {})
        self.assertEqual(self.host.dictionaries, {})
        self.assertEqual(self.host.accounts.get(self.alice, {}), {})

    def test_missing_and_invalid_initial_values_fail_before_allocation(self):
        class Required(Contract):
            value: URef[U32]

        with use_host(self.host):
            cases = [(Required, {}), (Counter, {'initial': 'bad'}),
                     (Counter, {'typo': 1}), (Counter, {'paused': 1}),
                     (Counter, {'owner': ContractHash(bytes(32))})]
            for cls, values in cases:
                before = len(self.host.cells)
                with self.subTest(values=values), self.assertRaises((TypeError, ValueError)):
                    cls(**values)
                self.assertEqual(len(self.host.cells), before)

    def test_owner_pause_and_read_access(self):
        contract = self.install(3)
        self.assertEqual(contract.invoke('get_owner').value, self.alice)
        self.assertIs(contract.invoke('is_paused').value, False)
        with self.assertRaises(NotOwner):
            contract.invoke('pause', caller=self.bob)
        contract.invoke('pause', caller=self.alice)
        self.assertIs(contract.invoke('is_paused').value, True)
        with self.assertRaises(Paused):
            contract.invoke('increment_by', {'amount': CLU32(4)}, caller=self.bob)
        self.assertEqual(contract.invoke('get', caller=self.bob).value, 3)
        with self.assertRaises(NotOwner):
            contract.invoke('unpause', caller=self.bob)
        contract.invoke('unpause', caller=self.alice)
        contract.invoke('increment', caller=self.bob)
        self.assertEqual(contract.invoke('get').value, 4)

    def test_ownership_transfer_changes_authority(self):
        contract = self.install()
        with self.assertRaises(NotOwner):
            contract.invoke('transfer_ownership', {'new_owner': CLKey(self.bob)}, caller=self.bob)
        contract.invoke('transfer_ownership', {'new_owner': CLKey(self.bob)}, caller=self.alice)
        self.assertEqual(contract.invoke('get_owner').value, self.bob)
        with self.assertRaises(NotOwner):
            contract.invoke('pause', caller=self.alice)
        contract.invoke('pause', caller=self.bob)

    def test_local_calls_raise_normal_catchable_python_errors(self):
        contract = self.install()
        with self.host.context(contract=contract.contract, caller=self.alice), use_host(self.host):
            local = Counter.bind()
            self.assertIsInstance(local.paused, URef)
            self.assertIsInstance(local.owner.read(), AccountHash)
            local.pause()
            try:
                local.increment()
            except Paused as error:
                self.assertIsInstance(error, UserError)
            else:
                self.fail('Expected a normal Python error')
            local.unpause()
            local.increment_by(5)
            self.assertEqual(local.get(), 5)

    def test_increment_decorators_check_the_pause_guard_once_per_call(self):
        with use_host(self.host):
            instance = Counter()
            original = Pausable._require_unpaused
            with patch.object(Pausable, '_require_unpaused', autospec=True, side_effect=original) as guard:
                instance.increment()
                self.assertEqual(guard.call_count, 1)
                guard.reset_mock()
                instance.increment_by(amount=3)
                self.assertEqual(guard.call_count, 1)
                self.assertEqual(instance.get(), 4)
                instance.pause()
                for operation in (instance.increment, lambda: instance.increment_by(2)):
                    guard.reset_mock()
                    with self.assertRaises(Paused):
                        operation()
                    self.assertEqual(guard.call_count, 1)
                    self.assertEqual(instance.get(), 4)

    def test_owner_decorator_checks_before_mutation_and_keeps_local_errors_catchable(self):
        with use_host(self.host):
            instance = Counter(owner=self.bob)
            original = Ownable._require_owner
            with patch.object(Ownable, '_require_owner', autospec=True, side_effect=original) as guard:
                for operation in (instance.pause, instance.unpause,
                                  lambda: instance.transfer_ownership(self.alice)):
                    guard.reset_mock()
                    with self.assertRaises(NotOwner):
                        operation()
                    self.assertEqual(guard.call_count, 1)
                    self.assertEqual(instance.get_owner(), self.bob)
                    self.assertFalse(instance.is_paused())

    def test_fields_follow_rebinding_and_missing_fields_fail(self):
        with use_host(self.host):
            for name, key in Counter(1).named_keys.items():
                named_keys[name] = key
            local = Counter.bind()
            from casthon.contract_api.storage import new_uref
            named_keys['count'] = new_uref(CLU32(9))
            self.assertEqual(local.get(), 9)
            del named_keys['count']
            with self.assertRaises(MissingKey):
                local.get()

    def test_native_and_frozen_schemas_preserve_fields_aliases_and_overrides(self):
        source = '''from casthon import URef, U32
from casthon.contracts import Contract, entry_point, export_contract
from casthon.contract_api.runtime import named_keys
class Base(Contract):
    count: URef[U32] = named_keys.reference("legacy_count")
    @entry_point
    def get(self) -> U32:
        return self.count.read()
class Example(Base):
    def get(self) -> U32:
        return super().get() + 1
export_contract(Example)
'''
        with class_pair(source) as (author, frozen, exports):
            self.assertEqual(list(exports.SIGNATURES), ['get'])
            self.assertEqual(exports.BINDINGS, {'get': ('Example', 'get')})
            self.assertEqual(serialize_entry_points(author.Example.entry_points()), serialize_entry_points(frozen.Example.entry_points()))
            for module in (author, frozen):
                host = MockHost()
                with use_host(host):
                    instance = module.Example(count=3)
                    keys = instance.named_keys
                    self.assertEqual(set(keys), {'legacy_count'})
                    self.assertEqual(instance.get(), 4)
                    self.assertEqual(host.accounts.get(host.caller, {}), {})

    def test_builder_rejects_conflicting_state_and_incompatible_overrides(self):
        definitions = [
            'class Example(Base):\n    count: URef[bool]\n',
            'class Example(Base):\n    duplicate: URef[U32] = named_keys.reference("count")\n',
            'class Example(Base):\n    def get(self, amount: U32) -> U32: return amount\n',
            'class Example(Base):\n    count = 3\n',
            'class Example(Base):\n    get = 3\n',
            'class Example(Base):\n    count: int\n',
            'class Example(Base):\n    get: URef[U32]\n',
            'class Example(Base):\n    def count(self): return 3\n',
            'class Other(Contract):\n    count: URef[bool]\nclass Example(Base, Other): pass\n',
        ]
        prefix = '''from casthon import URef, U32
from casthon.contracts import Contract, entry_point, export_contract
from casthon.contract_api.runtime import named_keys
class Base(Contract):
    count: URef[U32]
    @entry_point
    def get(self) -> U32: return self.count.read()
'''
        for definition in definitions:
            with self.subTest(definition=definition), tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / 'bad.py'
                path.write_text(prefix + definition + '\nexport_contract(Example)\n')
                with self.assertRaises(ValueError):
                    load_contract(path)
                module = types.ModuleType('bad_class')
                module.__file__ = str(path)
                with patch.dict(sys.modules, {'bad_class': module}):
                    exec(compile(path.read_text(), str(path), 'exec'), vars(module))
                    with self.assertRaises((ValueError, TypeError)):
                        _schema(module.Example)

    def test_additive_mixins_share_the_inherited_abi(self):
        source = '''from casthon import URef, U32
from casthon.contracts import Contract, entry_point, export_contract
class Left(Contract):
    left: URef[U32]
    @entry_point
    def get_left(self) -> U32: return self.left.read()
class Right(Contract):
    right: URef[U32]
    @entry_point
    def get_right(self) -> U32: return self.right.read()
class Example(Left, Right): pass
export_contract(Example)
'''
        with class_pair(source) as (author, frozen, exports):
            for module in (author, frozen):
                with use_host(MockHost()):
                    instance = module.Example(left=3, right=7)
                    self.assertEqual(instance.get_left(), 3)
                    self.assertEqual(instance.get_right(), 7)
                    self.assertEqual({entry.name for entry in module.Example.entry_points()}, {'get_left', 'get_right'})

    def test_method_alias_options_optional_defaults_and_keyword_only_parameters(self):
        source = '''from typing import Optional
from casthon import URef, U32, EntryPointAccess
from casthon.contracts import Contract, entry_point, export_contract
class Example(Contract):
    count: URef[U32]
    @entry_point(name="adjust", access=EntryPointAccess.GROUPS, groups=("admins",))
    def change(self, amount: Optional[U32] = None, *, factor: U32 = 2) -> U32:
        self.count.write(self.count.read() + (1 if amount is None else amount) * factor)
        return self.count.read()
export_contract(Example)
'''
        with class_pair(source) as (author, frozen, exports):
            self.assertEqual(list(exports.SIGNATURES), ['adjust'])
            self.assertEqual(exports.BINDINGS, {'adjust': ('Example', 'change')})
            self.assertEqual(serialize_entry_points(author.Example.entry_points()), serialize_entry_points(frozen.Example.entry_points()))
            for module in (author, frozen):
                with use_host(MockHost()):
                    instance = module.Example(count=3)
                    self.assertEqual(instance.change(), 5)
                    self.assertEqual(instance.change(5, factor=3), 20)
            from casthon._entry_point_signature import describe_call
            provider = types.ModuleType('frozen_entry_signatures')
            exec(lower(ROOT / 'runtime/entry_point_signature.py', sdk=True), vars(provider))
            native = describe_call(author.Example.change)
            actual = provider.describe_call(frozen.Example.change)
            self.assertEqual(native[0], actual[0])
            self.assertEqual(signature_key(native[1:4]), signature_key(actual[1:4]))
            self.assertEqual(native[4], actual[4])

    def test_incompatible_diamond_and_cooperative_super_are_rejected(self):
        variants = [
            'class Left(Base): pass\nclass Right(Base):\n    def helper(self): return 2\n',
            'class Left(Base):\n    def helper(self): return super().helper()\nclass Right(Base):\n    def helper(self): return 2\n',
        ]
        for branches in variants:
            source = '''from casthon import U32
from casthon.contracts import Contract, entry_point, export_contract
class Base(Contract):
    def helper(self): return 1
    @entry_point
    def get(self) -> U32: return self.helper()
''' + branches + '\nclass Example(Left, Right): pass\nexport_contract(Example)\n'
            with self.subTest(branches=branches), tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / 'diamond.py'
                path.write_text(source)
                with self.assertRaisesRegex(ValueError, 'MicroPython'):
                    load_contract(path)
                module = types.ModuleType('diamond')
                module.__file__ = str(path)
                with patch.dict(sys.modules, {'diamond': module}):
                    exec(compile(source, str(path), 'exec'), vars(module))
                    with self.assertRaisesRegex(ValueError, 'MicroPython'):
                        _schema(module.Example)

    def test_session_imports_class_abi_without_reexporting_it(self):
        declaration, source = load_contract(ROOT / 'contracts/counter_session.py')
        self.assertEqual(declaration['exports'], ['call'])
        metadata = {}
        exec(generate_exports(source, ['call']), metadata)
        self.assertEqual(metadata['BINDINGS'], {})
        schema = next(row for row in metadata['CLASS_SCHEMAS'] if row[:2] == ('contracts.counter', 'Counter'))
        self.assertIn('pause', [entry[0] for entry in schema[3]])
        self.assertIn('owner', schema[2])

    def test_unknown_helpers_and_class_abi_references_are_not_local_calls(self):
        with self.assertRaises(TypeError):
            Counter.get()
        self.assertNotIn('_require_owner', [entry.name for entry in Counter.entry_points()])
        self.assertNotIn('_increment_by', [entry.name for entry in Counter.entry_points()])
