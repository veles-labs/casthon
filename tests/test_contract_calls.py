"""Typed outbound ABIs, native routing and imported frozen signature lookup."""

from pathlib import Path
import sys
import types
import unittest
from typing import Optional
from unittest.mock import patch

from casthon import AccountHash, ContractHash, U32, CLValue, CLU32, CLKey, Revert, export
from casthon.bytesrepr import Reader
from casthon.codec import ABIError, encode
from casthon.testing import ContractHarness, MockHost, use_host
from contracts import counter, counter_session

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from bundle import generate_exports, load_contract, lower


@export
def nullable(amount: Optional[U32] = None, *, owner: Optional[AccountHash] = None) -> Optional[U32]:
    raise AssertionError("A remote call must not execute this local function")


@export
def identity(owner: AccountHash) -> AccountHash:
    raise AssertionError("A remote call must not execute this local function")


@export
def raw() -> CLValue:
    raise AssertionError("A remote call must not execute this local function")


@export
def argument_names(self: U32, function: U32) -> U32:
    raise AssertionError("A remote call must not execute this local function")


class RecordingHost:
    def __init__(self, returned=b""):
        self.returned, self.calls = returned, []

    def call_contract(self, contract, entry, data):
        reader = Reader(data)
        args = {}
        for _ in range(reader.count(9)):
            name = reader.take(reader.u32()).decode()
            args[name] = reader.cl_value()
        reader.finish()
        self.calls.append((contract, entry, args))
        return self.returned


class TypedCallTests(unittest.TestCase):
    def setUp(self):
        self.contract = ContractHash(bytes([3]) * 32)

    def test_python_arguments_and_return_values_use_the_declared_wire_types(self):
        host = RecordingHost(encode("U32", 7))
        with use_host(host):
            self.assertEqual(self.contract.call(counter.Counter.get), 7)
            host.returned = b""
            self.assertIsNone(self.contract.call(counter.Counter.increment_by, amount=5))
            self.assertIsNone(self.contract.call(counter.Counter.increment_by, 6))
        self.assertEqual([item[1] for item in host.calls], ["get", "increment_by", "increment_by"])
        self.assertEqual(host.calls[1][2]["amount"].to_bytes(), CLU32(5).to_bytes())
        self.assertEqual(host.calls[2][2]["amount"].to_bytes(), CLU32(6).to_bytes())
        self.assertEqual(host.calls[0][0], bytes(self.contract))

    def test_nullable_keys_keyword_only_arguments_and_omitted_defaults(self):
        owner = AccountHash(bytes([4]) * 32)
        host = RecordingHost(encode("Option<U32>", None))
        with use_host(host):
            self.assertIsNone(self.contract.call(nullable))
            self.assertIsNone(self.contract.call(nullable, None, owner=owner))
            host.returned = bytes(owner)
            returned = self.contract.call(identity, owner)
        self.assertIsInstance(returned, AccountHash)
        self.assertEqual(returned, owner)
        self.assertEqual(host.calls[0][2], {})
        self.assertEqual(host.calls[1][2]["amount"].to_bytes(), CLValue(Optional[U32], None).to_bytes())
        self.assertEqual(host.calls[1][2]["owner"].to_bytes(), CLValue(Optional[AccountHash], owner).to_bytes())

    def test_bad_bindings_and_wire_values_fail_before_calling_the_host(self):
        host = RecordingHost()
        with use_host(host):
            for args, kwargs in (((), {}), ((1, 2), {}), ((1,), {"amount": 2}), ((), {"typo": 1})):
                with self.subTest(args=args, kwargs=kwargs), self.assertRaises(TypeError):
                    self.contract.call(counter.Counter.increment_by, *args, **kwargs)
            with self.assertRaises(TypeError):
                self.contract.call(nullable, None, None)
            for value in ("bad", -1, 1 << 32):
                with self.subTest(value=value), self.assertRaises((TypeError, ABIError)):
                    self.contract.call(counter.Counter.increment_by, value)
            with self.assertRaises(TypeError):
                self.contract.call(identity, self.contract)
            with self.assertRaises(ValueError):
                self.contract.call(counter.Counter._increment_by, 1)
            with self.assertRaisesRegex(ValueError, "wire return annotation"):
                self.contract.call(raw)
        self.assertEqual(host.calls, [])

    def test_call_does_not_reserve_entrypoint_argument_names(self):
        host = RecordingHost(encode("U32", 3))
        with use_host(host):
            self.assertEqual(self.contract.call(argument_names, self=1, function=2), 3)
        self.assertEqual(set(host.calls[0][2]), {"self", "function"})

    def test_native_and_frozen_binding_agree_on_defaults_and_export_aliases(self):
        from test_entry_point_factory import contract_pair
        from casthon import _entry_point_signature as native_signature
        source = '''from typing import Optional
from casthon import U32, export
def implementation(amount: Optional[U32] = None, *, label: str = "default") -> Optional[U32]:
    raise AssertionError("Must not run locally")
query = export(implementation)
'''
        with contract_pair(source) as (author, frozen):
            for module in (author, frozen):
                provider = native_signature if module is author else sys.modules["casthon._entry_point_signature"]
                host = RecordingHost(encode("Option<U32>", None))
                with patch.dict(sys.modules, {"casthon._entry_point_signature": provider}), use_host(host):
                    self.assertIsNone(self.contract.call(module.query, label="hello"))
                    with self.assertRaises(TypeError):
                        self.contract.call(module.query, None, "hello")
                self.assertEqual(host.calls[0][1], "query")
                self.assertEqual(set(host.calls[0][2]), {"label"})
        with contract_pair(source + 'second = export(implementation)\n') as (author, frozen):
            for module in (author, frozen):
                provider = native_signature if module is author else sys.modules["casthon._entry_point_signature"]
                with patch.dict(sys.modules, {"casthon._entry_point_signature": provider}), self.assertRaisesRegex(ValueError, "multiple export names"):
                    self.contract.call(module.query)

    def test_imported_frozen_signatures_do_not_expand_session_exports(self):
        source = ROOT / "contracts/counter_session.py"
        declaration, _ = load_contract(source)
        self.assertEqual(declaration["exports"], ["call"])
        signatures = types.ModuleType("_cspr_exports")
        exec(generate_exports(source, declaration["exports"]), vars(signatures))
        self.assertEqual(list(signatures.SIGNATURES), ["call"])
        self.assertIn("increment_by", [method[0] for module, cls, fields, methods, events in signatures.CLASS_SCHEMAS if module == "contracts.counter" and cls == "Counter" for method in methods])
        metadata = types.ModuleType("casthon._entry_point_signature")
        exec(lower(ROOT / "runtime/entry_point_signature.py", sdk=True), vars(metadata))
        host = RecordingHost(encode("U32", 12))
        with patch.dict(sys.modules, {"_cspr_exports": signatures,
                                     "casthon._entry_point_signature": metadata}), use_host(host):
            self.assertEqual(self.contract.call(counter.Counter.get), 12)


class NativeSessionTests(unittest.TestCase):
    def setUp(self):
        self.host = MockHost(strict_arguments=True)
        ContractHarness(counter, host=self.host).invoke("call")
        self.contract = ContractHash(bytes(self.host.accounts[self.host.caller]["py_counter"]))
        self.session = ContractHarness(counter_session, host=self.host)

    def invoke(self, amount, expected):
        return self.session.invoke("call", {"contract": CLKey(self.contract),
                                           "amount": CLU32(amount), "expected": CLU32(expected)})

    def test_session_routes_calls_and_returns_an_ordinary_integer(self):
        self.assertEqual(self.invoke(5, 5).value, 5)
        self.assertEqual(self.invoke(2, 7).value, 7)
        self.assertEqual(set(self.host.accounts[self.host.caller]),
                         {"py_counter", "py_counter_package", "py_counter_access"})
        calls = [args[1] for name, args in self.host.calls if name == "call_contract"]
        self.assertEqual(calls, ["increment_by", "get", "increment_by", "get"])

    def test_session_failure_rolls_back_successful_remote_writes(self):
        self.invoke(5, 5)
        from casthon import UserError
        with self.assertRaises(UserError):
            self.invoke(2, 99)
        self.assertEqual(ContractHarness(counter, host=self.host).at(self.contract).invoke("get").value, 5)

    def test_callee_revert_aborts_the_session(self):
        self.invoke(0xffffffff, 0xffffffff)
        with self.assertRaises(Revert) as error:
            self.invoke(1, 0)
        self.assertEqual(error.exception.code, 3)
        self.assertEqual(ContractHarness(counter, host=self.host).at(self.contract).invoke("get").value, 0xffffffff)

    def test_catching_callee_failure_cannot_commit_partial_transaction_state(self):
        self.invoke(0xffffffff, 0xffffffff)
        with self.assertRaises(Revert), self.host.transaction(), use_host(self.host):
            try:
                self.contract.call(counter.Counter.increment_by, 1)
            except BaseException as error:
                self.assertIsInstance(error, Revert)
                # An engine revert remains fatal even if Python intercepts the
                # mock's transport signal. Account writes must also roll back.
                from casthon.contract_api.runtime import named_keys
                named_keys["should_rollback"] = self.contract
        self.assertNotIn("should_rollback", self.host.accounts[self.host.caller])
