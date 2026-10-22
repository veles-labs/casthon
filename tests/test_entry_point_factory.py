"""Native inspection and frozen dispatcher metadata describe the same ABI."""

from contextlib import contextmanager
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

import casthon
from casthon import _entry_point_signature as native_signature
from casthon.entry_points import serialize_entry_points
from contracts import counter

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from bundle import generate_exports, load_contract, lower


@contextmanager
def contract_pair(source):
    """Execute source and its lowered version, including import-time metadata."""
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "factory_fixture.py"
        path.write_text(source)
        declaration, _ = load_contract(path)
        author = types.ModuleType("factory_fixture")
        author.__file__ = str(path)
        with patch.dict(sys.modules, {author.__name__: author}):
            exec(compile(source, str(path), "exec"), vars(author))

        frozen = types.ModuleType("contract")
        frozen.__file__ = str(path)
        signatures = types.ModuleType("_cspr_exports")
        exec(generate_exports(path, declaration["exports"]), vars(signatures))
        metadata = types.ModuleType("casthon._entry_point_signature")
        exec(lower(ROOT / "runtime/entry_point_signature.py", sdk=True), vars(metadata))
        with patch.dict(sys.modules, {author.__name__: author, "contract": frozen, "_cspr_exports": signatures,
                                     "casthon._entry_point_signature": metadata}):
            exec(compile(lower(path), str(path), "exec"), vars(frozen))
            yield author, frozen


class EntryPointFactoryTests(unittest.TestCase):
    def test_explicit_parameter_sequences_preserve_order_and_reject_duplicates(self):
        fields = [("owner", casthon.Key), ("recipient", casthon.Key), ("amount", casthon.U256)]
        point = casthon.EntryPoint("transfer_from", fields)
        expected = casthon.EntryPoint("transfer_from", dict(fields))
        self.assertEqual(point.to_bytes(), expected.to_bytes())
        self.assertEqual(list(point.args), ["owner", "recipient", "amount"])
        with self.assertRaises(casthon.ABIError):
            casthon.EntryPoint("bad", [("amount", casthon.U32), ("amount", casthon.U256)])

    def test_counter_metadata_matches_the_explicit_abi(self):
        expected = [casthon.EntryPoint("get_owner", {}, casthon.AccountHash),
                    casthon.EntryPoint("transfer_ownership", {"new_owner": casthon.AccountHash}),
                    casthon.EntryPoint("pause", {}), casthon.EntryPoint("unpause", {}),
                    casthon.EntryPoint("is_paused", {}, bool), casthon.EntryPoint("increment", {}),
                    casthon.EntryPoint("increment_by", {"amount": casthon.U32}),
                    casthon.EntryPoint("get", {}, casthon.U32),
                    casthon.EntryPoint("get_increments", {"owner": casthon.AccountHash}, casthon.U32)]
        self.assertEqual(serialize_entry_points(counter.Counter.entry_points()), serialize_entry_points(expected))
        self.assertEqual([point.name for point in counter.Counter.entry_points()],
                         ["get_owner", "transfer_ownership", "pause", "unpause", "is_paused", "increment", "increment_by", "get", "get_increments"])

    def test_import_time_factory_has_native_and_frozen_parity(self):
        with contract_pair('''from __future__ import annotations
from typing import Optional
from casthon import AccountHash, U32, EntryPoint, export
@export
def read(owner: Optional[AccountHash], *, amount: U32 = 7) -> Optional[U32]:
    return amount
@export
def change() -> None:
    pass
ENTRY_POINTS = [EntryPoint.from_function(read), EntryPoint.from_function(change)]
# The list may be evaluated before later exported definitions are bound.
@export
def call() -> None:
    pass
''') as (author, frozen):
            expected = [casthon.EntryPoint("read", {"owner": "Option<Key>", "amount": "U32"}, "Option<U32>"),
                        casthon.EntryPoint("change", {})]
            for module in (author, frozen):
                self.assertEqual(serialize_entry_points(module.ENTRY_POINTS), serialize_entry_points(expected))
            self.assertEqual(author.read(None), 7)
            self.assertEqual(frozen.read(None, amount=5), 5)

    def test_imported_function_uses_its_selected_root_name(self):
        with contract_pair('''from casthon import EntryPoint, export
from contracts.typed_exports_helpers import calculate
read = export(calculate)
ENTRY_POINTS = [EntryPoint.from_function(read)]
''') as (author, frozen):
            expected = casthon.EntryPoint("read", {"amount": casthon.U32, "label": str}, casthon.U32).to_bytes()
            for module in (author, frozen):
                self.assertEqual(module.ENTRY_POINTS[0].to_bytes(), expected)
                self.assertEqual(module.read(5, "abc"), 8)

    def test_multiple_aliases_require_an_explicit_metadata_name(self):
        with contract_pair('''from casthon import EntryPoint, U32, export
def implementation(amount: U32) -> U32:
    return amount
first = export(implementation)
second = export(implementation)
ENTRY_POINTS = [EntryPoint.from_function(first, name="first"),
                EntryPoint.from_function(second, name="second")]
def ambiguous():
    return EntryPoint.from_function(first)
''') as (author, frozen):
            for module in (author, frozen):
                self.assertEqual([point.name for point in module.ENTRY_POINTS], ["first", "second"])
                provider = native_signature if module is author else sys.modules["casthon._entry_point_signature"]
                with patch.dict(sys.modules, {"casthon._entry_point_signature": provider}), self.assertRaisesRegex(ValueError, "multiple export names"):
                    module.ambiguous()

    def test_registration_policies_stay_explicit(self):
        with contract_pair('''from casthon import EntryPoint, EntryPointAccess, EntryPointType, EntryPointPayment, U32, export
@export
def change(amount: U32) -> None:
    pass
ENTRY_POINTS = [EntryPoint.from_function(change, access=EntryPointAccess.GROUPS,
    groups=("operators",), entry_point_type=EntryPointType.CALLED,
    payment=EntryPointPayment.CALLER)]
''') as (author, frozen):
            expected = casthon.EntryPoint("change", {"amount": casthon.U32},
                access=casthon.EntryPointAccess.GROUPS, groups=("operators",)).to_bytes()
            for module in (author, frozen):
                self.assertEqual(module.ENTRY_POINTS[0].to_bytes(), expected)

    def test_raw_returns_require_explicit_cltypes_including_explicit_unit(self):
        with contract_pair('''from casthon import EntryPoint, CLValue, CLU32, U32, export
@export
def raw() -> CLValue:
    return CLU32(7)
@export
def unannotated():
    return None
ENTRY_POINTS = [EntryPoint.from_function(raw, returns=U32),
                EntryPoint.from_function(unannotated, returns=None)]
def missing_type():
    return EntryPoint.from_function(raw)
def missing_annotation():
    return EntryPoint.from_function(unannotated)
''') as (author, frozen):
            for module in (author, frozen):
                self.assertEqual(serialize_entry_points(module.ENTRY_POINTS), serialize_entry_points(
                    [casthon.EntryPoint("raw", {}, casthon.U32), casthon.EntryPoint("unannotated", {})]))
                for function in (module.missing_type, module.missing_annotation):
                    provider = native_signature if module is author else sys.modules["casthon._entry_point_signature"]
                    with patch.dict(sys.modules, {"casthon._entry_point_signature": provider}), self.assertRaisesRegex(ValueError, "Return CLType cannot be inferred"):
                        function()

    def test_missing_and_nullable_arguments_have_distinct_dispatch_semantics(self):
        from casthon.testing import ContractHarness, MockHost
        with contract_pair('''from typing import Optional
from casthon import EntryPoint, U32, export
@export
def nullable(amount: Optional[U32]) -> Optional[U32]:
    return amount
@export
def default_nullable(amount: Optional[U32] = None) -> Optional[U32]:
    return amount
@export
def default_plain(amount: U32 = 7) -> U32:
    return amount
ENTRY_POINTS = [EntryPoint.from_function(nullable), EntryPoint.from_function(default_nullable),
                EntryPoint.from_function(default_plain)]
''') as (author, frozen):
            for module in (author, frozen):
                kinds = {entry.name: casthon.wire_type(entry.args["amount"]) for entry in module.ENTRY_POINTS}
                self.assertEqual(kinds, {"nullable": "Option<U32>", "default_nullable": "Option<U32>", "default_plain": "U32"})
            harness = ContractHarness(author, host=MockHost())
            with self.assertRaises(casthon.MissingArgument):
                harness.invoke("nullable")
            self.assertIsNone(harness.invoke("default_nullable").value)
            self.assertEqual(harness.invoke("default_plain").value, 7)
            self.assertIsNone(harness.invoke("nullable", {"amount": casthon.CLValue("Option<U32>", None)}).value)
            with self.assertRaises(casthon.ABIError):
                harness.invoke("nullable", raw_args={"amount": bytes(4)})

    def test_unsupported_parameter_annotations_are_not_silently_ignored(self):
        def plain_integer(amount: int) -> None:
            pass
        def unannotated(amount) -> None:
            pass
        for function in (plain_integer, unannotated):
            with self.subTest(function=function), self.assertRaises(ValueError):
                casthon.EntryPoint.from_function(function)

    def test_unmarked_helpers_are_rejected_in_native_and_frozen_code(self):
        with contract_pair('''from casthon import EntryPoint, U32, export
@export
def public() -> None:
    pass
def helper(amount: U32) -> U32:
    return amount
def describe_helper():
    return EntryPoint.from_function(helper)
''') as (author, frozen):
            for module in (author, frozen):
                provider = native_signature if module is author else sys.modules["casthon._entry_point_signature"]
                with patch.dict(sys.modules, {"casthon._entry_point_signature": provider}), self.assertRaisesRegex(ValueError, "not been selected"):
                    module.describe_helper()
