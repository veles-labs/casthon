"""Typed Wasm boundaries preserve ordinary Python calls and strict ABI rules."""

import sys
import tempfile
import types
import unittest
from pathlib import Path
from typing import Optional
from unittest.mock import patch

import casthon
from casthon._wire_types import _Optional
from casthon.codec import ABIError, cl_type, cl_value, decode, encode, valid_payload
from casthon.contract_api import runtime
from casthon.entry_points import EntryPoint
from casthon.return_value import serialize_typed_return
from casthon.testing import use_host
from test_contract_api import MemoryHost

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from bundle import generate_exports, load_contract, lower


class OptionalTests(unittest.TestCase):
    def test_optional_wire_fixtures_and_frozen_annotation_parity(self):
        for author, frozen, descriptor in (
            (Optional[casthon.U32], _Optional("U32"), "Option<U32>"),
            (str | None, _Optional(str), "Option<String>"),
            (Optional[casthon.AccountHash], _Optional(casthon.AccountHash), "Option<Key>"),
        ):
            self.assertEqual(casthon.wire_type(author), descriptor)
            self.assertEqual(casthon.wire_type(frozen), descriptor)
        self.assertEqual(cl_value("Option<U32>", None).hex(), "01000000000d04")
        self.assertEqual(cl_value("Option<U32>", 7).hex(), "0500000001070000000d04")
        for value in (None, 0, 0xffffffff):
            data = encode("Option<U32>", value)
            self.assertEqual(decode("Option<U32>", data), value)
            self.assertTrue(valid_payload("Option<U32>", data))
        for data in (b"", b"\2", b"\0\0", b"\1", b"\1\0\0\0", b"\1" + bytes(5)):
            with self.subTest(data=data), self.assertRaises(ABIError):
                decode("Option<U32>", data)
            self.assertFalse(valid_payload("Option<U32>", data))
        self.assertEqual(cl_type("Option<Bytes>"), b"\x0d\x0e\x03")
        for invalid in (casthon.U32 | str, Optional[int], "Option<Bogus>", "Option<" * 33 + "U32" + ">" * 33):
            with self.assertRaises(TypeError):
                casthon.wire_type(invalid)

    def test_optional_key_decoding_and_return_validation_keep_the_variant(self):
        host = MemoryHost()
        owner = casthon.AccountHash(bytes([11]) * 32)
        with use_host(host):
            for annotation in (Optional[casthon.AccountHash], _Optional(casthon.AccountHash)):
                host.args["owner"] = b"\1" + bytes(owner)
                self.assertIsInstance(runtime.get_named_arg("owner", annotation), casthon.AccountHash)
                self.assertEqual(runtime.get_named_arg("owner", annotation), owner)
                host.args["owner"] = b"\0"
                self.assertIsNone(runtime.get_named_arg("owner", annotation))
                host.args["owner"] = b"\1" + bytes(casthon.Hash(bytes(32)))
                with self.assertRaises(ABIError):
                    runtime.get_named_arg("owner", annotation)
                self.assertIsNone(runtime.try_get_named_arg("owner", annotation))
                with self.assertRaises(casthon.InvalidArgument):
                    serialize_typed_return(annotation, casthon.CLValue("Option<Key>", casthon.Hash(bytes(32))))
                self.assertEqual(serialize_typed_return(annotation, owner),
                                 cl_value("Option<Key>", owner))

    def test_optional_entrypoint_metadata_and_runtime_expressions_freeze(self):
        source = '''from casthon import EntryPoint, U32, AccountHash, wire_type
from typing import Optional as Maybe
Alias = Maybe[U32]
_cspr_optional = 1
_cspr_types = 2
READ = 1
WRITE = 2
ENTRY_POINTS = [EntryPoint("read", {"owner": Maybe[AccountHash]}, Alias)]
def describe():
    return wire_type(Alias), wire_type(U32 | None), ENTRY_POINTS[0].to_bytes(), READ | WRITE
'''
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "probe.py"
            path.write_text(source)
            author, frozen = {}, {}
            exec(source, author)
            exec(lower(path), frozen)
            self.assertEqual(author["describe"](), frozen["describe"]())
            self.assertEqual(frozen["_cspr_optional"], 1)
            self.assertEqual(frozen["_cspr_types"], 2)
            self.assertEqual(frozen["ENTRY_POINTS"][0].to_bytes(),
                             EntryPoint("read", {"owner": Optional[casthon.AccountHash]}, Optional[casthon.U32]).to_bytes())


class TypedExportTests(unittest.TestCase):
    def prepare(self, source):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "probe.py"
            path.write_text(source)
            declaration, _ = load_contract(path)
            contract, exports = {}, {}
            exec(lower(path), contract)
            exec(generate_exports(path, declaration["exports"]), exports)
        module = types.ModuleType("_cspr_exports")
        module.SIGNATURES = exports["SIGNATURES"]
        dispatcher = {}
        with patch.dict(sys.modules, {"_cspr_exports": module}):
            exec((ROOT / "runtime/dispatcher.py").read_text(), dispatcher)
        return contract, exports["SIGNATURES"], dispatcher["invoke"]

    def test_parameters_and_returns_do_not_change_direct_python_calls(self):
        contract, signatures, invoke = self.prepare('''from casthon import U32, export
@export
def calculate(amount: U32, label: str) -> U32:
    assert type(amount) is int
    return amount + len(label)
''')
        self.assertEqual(contract["calculate"](5, "abc"), 8)
        host = MemoryHost()
        host.args = {"amount": encode("U32", 5), "label": encode("String", "abc")}
        with use_host(host):
            self.assertEqual(invoke(contract["calculate"], signatures["calculate"]), cl_value("U32", 8))

    def test_decorated_reusable_function_can_be_selected_by_an_export_binding(self):
        contract, signatures, invoke = self.prepare('''from functools import wraps as preserve
from casthon import U32, export
def double(function):
    @preserve(function)
    def decorated(*args, **kwargs): return function(*args, **kwargs) * 2
    return decorated
@double
def reusable(value: U32) -> U32: return value
call = export(reusable)
''')
        self.assertEqual(contract["call"](7), 14)
        host = MemoryHost()
        host.args["value"] = encode("U32", 5)
        with use_host(host):
            self.assertEqual(invoke(contract["call"], signatures["call"]), cl_value("U32", 10))

    def test_defaults_apply_only_to_absent_arguments(self):
        contract, signatures, invoke = self.prepare('''from casthon import U32, export
from typing import Optional
default_label = "original"
@export
def calculate(amount: Optional[U32] = 7, *, label: str = default_label) -> str:
    return label + ":" + str(amount)
default_label = "changed"
@export
def required(amount: U32 | None) -> U32 | None:
    return amount
''')
        host = MemoryHost()
        with use_host(host):
            self.assertEqual(invoke(contract["calculate"], signatures["calculate"]), cl_value("String", "original:7"))
            host.args["amount"] = b"\0"
            self.assertEqual(invoke(contract["calculate"], signatures["calculate"]), cl_value("String", "original:None"))
            self.assertEqual(invoke(contract["required"], signatures["required"]), cl_value("Option<U32>", None))
            host.args["amount"] = b"\1" + encode("U32", 0)
            self.assertEqual(invoke(contract["required"], signatures["required"]), cl_value("Option<U32>", 0))
            host.args.clear()
            with self.assertRaises(casthon.MissingArgument):
                invoke(contract["required"], signatures["required"])
            host.args["amount"] = b"bad"
            with self.assertRaises(ABIError):
                invoke(contract["calculate"], signatures["calculate"])

    def test_typed_returns_validate_after_cleanup_and_legacy_returns_stay_explicit(self):
        events = []
        for value, expected in (
            (7, cl_value("U32", 7)), (casthon.CLU32(7), cl_value("U32", 7)),
            (True, None), (-1, None), (1 << 32, None), (None, None),
            (casthon.CLString("bad"), None),
            (casthon.SerializedCLValue(b"\1\0\0\0\7\4"), None),
        ):
            with self.subTest(value=value):
                def function():
                    try:
                        return value
                    finally:
                        events.append("finally")
                _, _, invoke = self.prepare("from casthon import export\n@export\ndef unused(): pass\n")
                if expected is None:
                    with self.assertRaises(casthon.InvalidArgument):
                        invoke(function, ([], True, "U32"))
                else:
                    self.assertEqual(invoke(function, ([], True, "U32")), expected)
                self.assertEqual(events.pop(), "finally")
        self.assertEqual(invoke(lambda: None, ([], True, "Unit")), cl_value("Unit", None))
        self.assertIsNone(invoke(lambda: None, ([], False, None)))
        self.assertEqual(invoke(lambda: casthon.CLU32(3), ([], False, None)), cl_value("U32", 3))
        with self.assertRaises(casthon.InvalidArgument):
            invoke(lambda: 3, ([], False, None))

    def test_shared_annotated_exports_resolve_without_executing_contract_code(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            package = root / "contracts"
            package.mkdir()
            (package / "__init__.py").write_text("")
            (package / "shared.py").write_text('''from __future__ import annotations
from casthon import U32 as Amount
from typing import Optional as Maybe
Nullable = Maybe[Amount]
def implementation(amount: "Nullable", *, label: str = "hello") -> "Amount":
    return (amount or 0) + len(label)
''')
            path = package / "root.py"
            path.write_text('''from casthon import export
from contracts.shared import implementation
raise RuntimeError("must not run during build")
ENTRY_POINTS = unknown_metadata_factory()
calculate = export(implementation)
''')
            with patch("bundle.ROOT", root):
                declaration, _ = load_contract(path)
                generated = generate_exports(path, declaration["exports"])
            self.assertEqual(declaration["signatures"]["calculate"], {
                "args": [{"name": "amount", "type": "Option<U32>", "hasDefault": False},
                         {"name": "label", "type": "String", "hasDefault": True}], "returns": "U32"})
            self.assertNotIn("unknown_metadata_factory", generated)

    def test_unsupported_signatures_fail_at_build_time(self):
        for signature in (
            "def example(amount): pass", "def example(amount: int): pass",
            "def example(amount: U32, /): pass", "def example(*amount: U32): pass",
            "def example(**amount: U32): pass", "def example(amount: U32 | str): pass",
            "def example() -> Ret: pass", "def example() -> int: pass",
            "def example(amount: factory()): pass",
        ):
            with self.subTest(signature=signature), tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / "probe.py"
                path.write_text("from casthon import U32, Ret, export\n@export\n" + signature + "\n")
                with self.assertRaises(ValueError):
                    load_contract(path)


if __name__ == "__main__":
    unittest.main()
