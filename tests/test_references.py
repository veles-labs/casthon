"""Typed state declarations, explicit allocation and keyed dictionary access."""

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import casthon
from casthon import (
    URef, U32, U256, Key, AccountHash, ContractHash, Dictionary,
    CLU32, CLU256, CLKey, CLUnit, SerializedCLValue,
)
from casthon.contract_api import runtime, storage
from casthon.testing import use_host
from test_contract_api import MemoryHost

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from bundle import lower


class ReferenceTests(unittest.TestCase):
    def setUp(self):
        self.host = MemoryHost()
        self.enterContext(use_host(self.host))
        self.keys = runtime.named_keys

    def test_declarations_do_not_call_the_host(self):
        with patch("casthon._ffi._host", side_effect=AssertionError("Unexpected host access")):
            count = self.keys.reference("count", URef[U32])
            ledger = self.keys.reference("ledger", Dictionary[AccountHash, U256](key=lambda k: bytes(k).hex()))
            contract = self.keys.reference("contract", ContractHash)
        self.assertEqual((count.name, ledger.name, contract.name), ("count", "ledger", "contract"))
        with self.assertRaises(AttributeError):
            count.name = "other"

    def test_allocation_and_initial_keys_are_explicit(self):
        count = self.keys.reference("count", URef[U32])
        ledger = self.keys.reference("ledger", Dictionary[str, U256]())
        initial = {count.name: count.create(0), ledger.name: ledger.create()}
        self.assertEqual(self.host.keys, {})
        self.assertTrue(all(isinstance(key, URef) for key in initial.values()))
        self.assertEqual(initial["count"].read(), 0)
        package, _ = storage.create_contract_package_at_hash()
        storage.add_contract_version(package, [], initial)
        self.assertEqual(self.host.keys, {})
        count.set(initial["count"])
        ledger.set(initial["ledger"])
        count.write(4)
        ledger["owner"] = 12
        self.assertEqual(count.read(), 4)
        self.assertEqual(ledger["owner"], 12)

    def test_references_resolve_current_binding_and_removal_does_not_revoke(self):
        count = self.keys.reference("count", URef[U32])
        with self.assertRaises(casthon.MissingKey):
            count.read()
        count.set(count.create(1))
        original = count.get()
        count.set(count.create(10))
        count.write(11)
        self.assertEqual(original.read(), 1)
        self.assertEqual(count.read(), 11)
        count.remove()
        count.remove()
        self.assertNotIn("count", self.keys)
        self.assertEqual(original.read(), 1)
        with self.assertRaises(casthon.MissingKey):
            count.read()

    def test_references_use_the_active_host_context(self):
        count = self.keys.reference("count", URef[U32])
        count.set(count.create(1))
        other = MemoryHost()
        with use_host(other):
            with self.assertRaises(casthon.MissingKey):
                count.read()
            count.set(count.create(20))
            self.assertEqual(count.read(), 20)
        self.assertEqual(count.read(), 1)

    def test_raw_key_references_validate_variants_and_preserve_key_subclasses(self):
        contract = self.keys.reference("contract", ContractHash)
        value = ContractHash(bytes([3]) * 32)
        contract.set(value)
        self.assertIsInstance(contract.get(), ContractHash)
        self.assertEqual(contract.get(), value)
        with self.assertRaises(TypeError):
            contract.set(self.host.owner)
        self.keys[contract.name] = self.host.owner
        with self.assertRaises(casthon.InvalidArgument):
            contract.get()
        any_key = self.keys.reference("any", Key)
        any_key.set(storage.new_uref(CLU32(0)))
        self.assertIsInstance(any_key.get(), URef)
        count = self.keys.reference("count", URef[U32])
        self.keys[count.name] = self.host.owner
        with self.assertRaises(casthon.InvalidArgument):
            count.read()
        with self.assertRaises(TypeError):
            count.set(self.host.owner)

    def test_typed_values_validate_before_allocation_or_write(self):
        count = self.keys.reference("count", URef[U32])
        for value in (-1, 1 << 32, True, "1"):
            with self.assertRaises(casthon.ABIError):
                count.create(value)
        for value in (CLU256(1), CLKey(self.host.owner)):
            with self.assertRaises(TypeError):
                count.create(value)
        self.assertEqual(self.host.next, 1)
        count.set(count.create(CLU32(7)))
        count.write(SerializedCLValue(CLU32(9).to_bytes()))
        self.assertEqual(count.read(), 9)
        with self.assertRaises(TypeError):
            count.write(CLU256(1))
        with self.assertRaises(casthon.ABIError):
            count.write(1 << 32)
        with self.assertRaises(casthon.InvalidArgument):
            count.write(SerializedCLValue(b"\4\0\0\0\1\0\0\0\xff"))
        self.assertEqual(count.read(), 9)

    def test_typed_urefs_use_existing_read_errors_and_support_unit(self):
        count = self.keys.reference("count", URef[U32])
        count.set(count.create(1))
        self.host.cells[bytes(count.get())] = casthon.CLString("bad").to_bytes()
        with self.assertRaises(casthon.Read):
            count.read()
        self.host.cells.clear()
        with self.assertRaises(casthon.ValueNotFound):
            count.read()
        unit = self.keys.reference("unit", URef[None])
        unit.set(unit.create(None))
        self.assertIsNone(unit.read())
        unit.write(CLUnit())
        self.assertIsNone(unit.get().read())
        raw = URef(bytes([255]) * 32)
        self.assertIsNone(raw.read(U32))
        with self.assertRaises(TypeError):
            raw.read()
        with self.assertRaises(TypeError):
            raw.write(7)

    def test_typed_key_values_check_the_expected_variant(self):
        target = self.keys.reference("target", URef[ContractHash])
        value = ContractHash(bytes(32))
        target.set(target.create(value))
        self.assertIsInstance(target.read(), ContractHash)
        for bad in (self.host.owner, CLKey(self.host.owner)):
            with self.assertRaises(TypeError):
                target.write(bad)
        self.assertEqual(target.read(), value)

    def test_typed_add_uses_host_add_and_rejects_unsupported_types(self):
        total = self.keys.reference("total", URef[U256])
        total.set(total.create(7))
        total.add(5)
        total.get().add(CLU256(3))
        self.assertEqual(total.read(), 15)
        count = self.keys.reference("count", URef[U32])
        count.set(count.create(1))
        with patch.object(self.host, "add", side_effect=AssertionError("Unexpected host add")):
            with self.assertRaises(TypeError):
                count.add(1)

    def test_dictionary_functor_and_value_type_are_shared_by_reads_and_writes(self):
        transformed = []

        def key(owner):
            transformed.append(owner)
            return bytes(owner)[1:].hex()

        ref = self.keys.reference("ledger", Dictionary[AccountHash, U256](key=key))
        ref.set(ref.create())
        ledger = ref
        owner = self.host.owner
        self.assertEqual(ledger.get(owner, 0), 0)
        ledger[owner] = 42
        self.assertEqual(ledger[owner], 42)
        self.assertIn(owner, ledger)
        self.assertEqual(transformed, [owner] * 4)
        self.assertEqual(self.host.dicts[bytes(ledger.seed)], {bytes(owner)[1:].hex(): CLU256(42).to_bytes()})
        ledger[owner] = CLU256(17)
        self.assertEqual(ledger.get(owner), 17)

    def test_dictionary_missing_items_are_distinct_from_stored_unit(self):
        ref = self.keys.reference("units", Dictionary[str, None]())
        ref.set(ref.create())
        ledger = ref
        self.assertIsNone(ledger.get("missing"))
        default = object()
        self.assertIs(ledger.get("missing", default), default)
        self.assertNotIn("missing", ledger)
        with self.assertRaises(KeyError):
            ledger["missing"]
        ledger["present"] = None
        self.assertIsNone(ledger["present"])
        self.assertIsNone(ledger.get("present", default))
        self.assertIn("present", ledger)

    def test_dictionary_key_and_value_failures_happen_before_host_calls(self):
        transform = lambda key: key
        ref = self.keys.reference("items", Dictionary[str, U32](key=transform))
        ref.set(ref.create())
        ledger = ref
        with patch.object(self.host, "dictionary_put", side_effect=AssertionError("Unexpected write")):
            for key, value, error in (
                (7, 1, TypeError), ("ż" * 33, 1, casthon.DictionaryItemKeyExceedsLength),
                ("a", 1 << 32, casthon.ABIError), ("a", CLU256(1), TypeError),
            ):
                with self.subTest(key=key), self.assertRaises(error):
                    ledger[key] = value
        for transform in (lambda key: 7, lambda key: "x" * 65):
            schema = Dictionary[str, U32](key=transform, seed=ledger.seed)
            with self.assertRaises((TypeError, casthon.DictionaryItemKeyExceedsLength)):
                schema["a"]

    def test_dictionary_resolution_and_capability_lifetimes(self):
        ref = self.keys.reference("items", Dictionary[str, U32])
        self.assertIsInstance(ref, Dictionary)
        with self.assertRaises(casthon.MissingKey):
            ref.get("a")
        ref.set(ref.create())
        original = Dictionary[str, U32](seed=ref.seed)
        original["a"] = 7
        ref.set(ref.create())
        self.assertNotIn("a", ref)
        ref["a"] = 11
        self.assertEqual(ref.get("a"), 11)
        self.assertEqual(original["a"], 7)
        with use_host(MemoryHost()):
            with self.assertRaises(casthon.MissingKey):
                ref.get("a", 0)
            ref.set(ref.create())
            ref["a"] = 99
            self.assertEqual(ref["a"], 99)
        self.assertEqual(ref["a"], 11)
        with self.assertRaises(TypeError):
            iter(original)
        ref.remove()
        self.assertEqual(original["a"], 7)
        with self.assertRaises(casthon.MissingKey):
            ref.get("a")
        self.keys[ref.name] = self.host.owner
        with self.assertRaises(casthon.InvalidArgument):
            ref.get("a")
        with self.assertRaises(TypeError):
            ref.set(self.host.owner)

    def test_key_functors_can_use_custom_python_key_classes(self):
        class Pair:
            def __init__(self, left, right):
                self.left, self.right = left, right

        ref = self.keys.reference("pairs", Dictionary[Pair, U32](key=lambda p: f"{p.left}:{p.right}"))
        ref.set(ref.create())
        ref[Pair("a", "b")] = 9
        self.assertEqual(ref[Pair("a", "b")], 9)

    def test_invalid_schema_declarations_fail_without_allocating(self):
        for operation in (
            lambda: self.keys.reference("bad", U32),
            lambda: self.keys.reference("bad", URef),
            lambda: self.keys.reference("", URef[U32]),
            lambda: Dictionary[AccountHash, U32](),
            lambda: Dictionary[str, U32](key=7),
        ):
            with self.assertRaises((TypeError, ValueError)):
                operation()
        schema = Dictionary[str, U32]()
        with self.assertRaises(ValueError):
            schema["unbound"]
        self.assertEqual(self.host.next, 1)

    def test_freezer_lowers_aliases_and_preserves_lazy_type_schemas(self):
        source = '''from casthon import URef as Ref, U32 as Number, AccountHash as Owner, Dictionary as Items
from casthon.contract_api.runtime import named_keys
Value = Number
Counter = Ref[Value]
count = named_keys.reference("count", Counter)
items = named_keys.reference("items", Items[Owner, Value](key=lambda owner: bytes(owner)[1:].hex()))
'''
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "schemas.py"
            path.write_text(source)
            code = lower(path)
            self.assertIn("Ref.of(Value)", code)
            self.assertIn("Items.of(Owner, Value)", code)
            namespace = {}
            exec(code, namespace)
        self.assertEqual(self.host.keys, {})
        count, items = namespace["count"], namespace["items"]
        count.set(count.create(3))
        items.set(items.create())
        items[self.host.owner] = 7
        self.assertEqual(count.read(), 3)
        self.assertEqual(items[self.host.owner], 7)

    def test_high_level_counter_tracks_each_caller_and_registers_both_fields(self):
        from contracts import counter

        self.host.keys = {name: bytes(key) for name, key in counter.Counter().named_keys.items()}
        local = counter.Counter.bind()
        local.increment()
        local.increment_by(5)
        self.assertEqual(local.get(), 6)
        self.assertEqual(local.get_increments(self.host.owner), 6)
        self.host.owner = AccountHash(bytes([22]) * 32)
        local.increment()
        self.assertEqual(local.get(), 7)
        self.assertEqual(local.get_increments(self.host.owner), 1)
