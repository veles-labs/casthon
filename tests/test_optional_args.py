"""Missing arguments, nullable payloads, defaults and independent ABI metadata."""

import sys
import tempfile
import types
import unittest
from pathlib import Path
from typing import Optional
from unittest.mock import patch

from cspr import (
    ABIError, ApiError, AccountHash, CLValue, CLU32, CLString, ContractHash,
    EntryPoint, MISSING, MissingArgument, OptionalArg, U32, URef, wire_type,
)
from cspr.arguments import argument_type, optional_arg_inner
from cspr._wire_types import _Optional, _OptionalArg
from cspr.contract_api import runtime
from cspr.entry_points import serialize_entry_points
from cspr.testing import ContractHarness, MockHost, use_host
from contracts import typed_exports
from test_contract_calls import RecordingHost
from test_entry_point_factory import contract_pair
import test_typed_exports as typed_test_helpers

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from bundle import lower, load_contract


class OptionalArgTests(unittest.TestCase):
    def test_missing_none_zero_and_value_are_distinct_in_both_descriptors(self):
        host = MockHost()
        for annotation in (OptionalArg[Optional[U32]], _OptionalArg(_Optional("U32"))):
            with self.subTest(annotation=annotation), use_host(host):
                host.args.clear()
                self.assertIs(runtime.get_named_arg("value", annotation), MISSING)
                for value in (None, 0, 7):
                    host.args["value"] = CLValue(Optional[U32], value)._payload
                    self.assertEqual(runtime.get_named_arg("value", annotation), value)

    def test_missing_is_not_encoded_as_none_and_malformed_values_still_raise(self):
        host = MockHost()
        with use_host(host):
            self.assertIs(runtime.get_named_arg("value", OptionalArg[U32]), MISSING)
            with self.assertRaises(MissingArgument):
                runtime.get_named_arg("value", Optional[U32])
            for raw in (b"", b"\2", b"\0\0", b"\1\0"):
                host.args["value"] = raw
                with self.subTest(raw=raw), self.assertRaises(ABIError):
                    runtime.get_named_arg("value", OptionalArg[Optional[U32]])
            host.fail_next("get_named_arg", ApiError(17))
            with self.assertRaises(ApiError) as error:
                runtime.get_named_arg("value", OptionalArg[U32])
            self.assertEqual(error.exception.code, 17)
            with self.assertRaises(TypeError):
                runtime.try_get_named_arg("value", OptionalArg[U32])

    def test_optional_key_variants_and_unit_payloads(self):
        host = MockHost()
        owner = AccountHash(bytes(32))
        with use_host(host):
            host.args["key"] = b"\1" + bytes(owner)
            result = runtime.get_named_arg("key", OptionalArg[Optional[AccountHash]])
            self.assertIsInstance(result, AccountHash)
            host.args["key"] = b"\1" + bytes(ContractHash(bytes(32)))
            with self.assertRaises(ABIError):
                runtime.get_named_arg("key", OptionalArg[Optional[AccountHash]])
            self.assertIs(runtime.get_named_arg("unit", OptionalArg[None]), MISSING)
            host.args["unit"] = b""
            self.assertIsNone(runtime.get_named_arg("unit", OptionalArg[None]))

    def test_marker_is_not_a_storage_return_or_clvalue_type(self):
        self.assertEqual(wire_type(argument_type(OptionalArg[Optional[U32]])), "Option<U32>")
        self.assertIsNone(optional_arg_inner(Optional[U32]))
        for annotation in (OptionalArg[U32], _OptionalArg("U32"), Optional[OptionalArg[U32]]):
            with self.subTest(annotation=annotation), self.assertRaises(TypeError):
                wire_type(annotation)
        with self.assertRaises(TypeError):
            URef[OptionalArg[U32]]
        with self.assertRaises(ABIError):
            CLValue(Optional[U32], MISSING)

    def test_dispatch_and_python_defaults_have_separate_presence_rules(self):
        host = MockHost(strict_arguments=True)
        session = ContractHarness(typed_exports, host=host)
        session.invoke("call")
        harness = session.at(host.accounts[host.caller]["py_typed_exports"])
        for entry, missing in (("presence", "missing"), ("presence_default", "none"), ("presence_number", "7")):
            self.assertEqual(harness.invoke(entry).value, missing)
        for value in (None, 0, 7):
            args = {"value": CLValue(Optional[U32], value)}
            for entry in ("presence", "presence_default"):
                self.assertEqual(harness.invoke(entry, args).value, "none" if value is None else str(value))
        self.assertEqual(harness.invoke("presence_number", {"value": CLU32(0)}).value, "0")
        with self.assertRaises(ABIError):
            harness.invoke("presence_number", {"value": CLString("bad")})
        # Direct Python calls keep ordinary argument/default behavior.
        with self.assertRaises(TypeError):
            typed_exports.presence()
        self.assertEqual(typed_exports.presence(MISSING), "missing")
        self.assertEqual(typed_exports.presence_default(), "none")

    def test_outgoing_calls_omit_missing_but_encode_explicit_none(self):
        host = RecordingHost(CLString("response")._payload)
        contract = ContractHash(bytes(32))
        with use_host(host):
            contract.call(typed_exports.presence)
            contract.call(typed_exports.presence, MISSING)
            contract.call(typed_exports.presence, None)
            contract.call(typed_exports.presence, 0)
            contract.call(typed_exports.presence_number, MISSING)
        self.assertEqual([call[2] for call in host.calls[:2]], [{}, {}])
        self.assertEqual(host.calls[2][2]["value"].to_bytes(), CLValue(Optional[U32], None).to_bytes())
        self.assertEqual(host.calls[3][2]["value"].to_bytes(), CLValue(Optional[U32], 0).to_bytes())
        self.assertEqual(host.calls[4][2], {})

    def test_frozen_aliases_runtime_subscriptions_and_defaults_match_native(self):
        source = '''from cspr import OptionalArg as Arg, MISSING, U32, AccountHash, export
from typing import Optional as Maybe
Alias = Arg[Maybe[U32]]
_cspr_optional_arg = 12
@export
def value(amount: Alias = MISSING) -> str:
    if amount is MISSING: return "missing"
    return "none" if amount is None else str(amount)
def read():
    from cspr.contract_api.runtime import get_named_arg
    return get_named_arg("owner", Arg[Maybe[AccountHash]])
'''
        contract, signatures, invoke = typed_test_helpers.TypedExportTests().prepare(source)
        host = MockHost()
        with use_host(host):
            self.assertEqual(invoke(contract["value"], signatures["value"]), CLString("missing").to_bytes())
            host.args["amount"] = b"\0"
            self.assertEqual(invoke(contract["value"], signatures["value"]), CLString("none").to_bytes())
            self.assertIs(contract["read"](), MISSING)
        self.assertEqual(contract["_cspr_optional_arg"], 12)

    def test_factories_keep_optional_arguments_dynamic_and_preserve_required_order(self):
        source = '''from cspr import OptionalArg, MISSING, OptionalArg as Arg, U32, EntryPoint, export
@export
def read(owner: str, maybe: OptionalArg[U32], count: U32 = 7, *, note: Arg[str] = MISSING) -> str:
    return owner
ENTRY_POINTS = [EntryPoint.from_function(read)]
'''
        with contract_pair(source) as (author, frozen):
            expected = EntryPoint("read", [("owner", str), ("count", U32)], str)
            for module in (author, frozen):
                self.assertEqual(serialize_entry_points(module.ENTRY_POINTS), serialize_entry_points([expected]))
        # Classes use the same rule; the marker also participates in override checks.
        source = '''from cspr import OptionalArg, MISSING, U32
from cspr.contracts import Contract, entry_point, export_contract
@export_contract
class Example(Contract):
    @entry_point
    def read(self, amount: OptionalArg[U32] = MISSING) -> str:
        return str(amount)
'''
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "class_marker.py"
            path.write_text(source)
            declaration, _ = load_contract(path)
            self.assertTrue(declaration["signatures"]["read"]["args"][0]["optionalArg"])
            module = types.ModuleType("class_marker")
            exec(compile(source, str(path), "exec"), vars(module))
            self.assertEqual(module.Example.entry_points()[0].args, {})

    def test_invalid_marker_placements_fail_before_building(self):
        for argument, returns in (("OptionalArg[OptionalArg[U32]]", "str"),
                                  ("Optional[OptionalArg[U32]]", "str"), ("U32", "OptionalArg[U32]")):
            source = "from cspr import OptionalArg, U32, export\nfrom typing import Optional\n@export\ndef f(value: " + argument + ") -> " + returns + ": pass\n"
            with self.subTest(argument=argument, returns=returns), tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / "invalid.py"
                path.write_text(source)
                with self.assertRaises(ValueError):
                    load_contract(path)

    def test_frozen_sentinel_has_one_identity_and_does_not_compare_equal_to_values(self):
        scope = {"__package__": "cspr"}
        exec(lower(ROOT / "runtime/arguments.py", sdk=True), scope)
        missing = scope["MISSING"]
        self.assertIs(scope["MissingType"](0), missing)
        self.assertIs(scope["MissingType"].MISSING, missing)
        self.assertEqual((repr(missing), str(missing), missing.name, missing.value), ("MISSING", "MISSING", "MISSING", 0))
        self.assertNotEqual(missing, 0)
        self.assertIsNot(missing, None)
