"""Developer-facing native tests: real contract code and a scoped mock host."""

import ast
from pathlib import Path
import sys
import tempfile
import types
import unittest

from casthon import AccountHash, URef, U32, CLU32, CLString, User, Ret, InvalidArgument, MissingArgument, MissingKey, Read, ABIError
from casthon.contract_api import runtime, storage
from casthon.testing import MockHost, MockAccessError, UnsupportedHostCall, ContractHarness, use_host
from contracts import counter, typed_exports

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))


class NativeCounterTests(unittest.TestCase):
    def setUp(self):
        self.alice = AccountHash(bytes([1]) * 32)
        self.bob = AccountHash(bytes([2]) * 32)
        self.host = MockHost(caller=self.alice)
        self.harness = ContractHarness(counter, host=self.host)

    def install(self):
        self.harness.invoke("call", caller=self.alice)
        return self.harness.at(self.host.accounts[self.alice]["py_counter"])

    def test_direct_python_calls_need_no_compiler_or_dispatcher(self):
        with use_host(self.host):
            local = counter.Counter()
            local.increment_by(5)
            self.assertEqual(local.get(), 5)
            self.assertEqual(local.get_increments(self.alice), 5)
            self.assertIs(type(local.get()), int)
            self.assertEqual(self.host.accounts.get(self.alice, {}), {})

    def test_installation_contexts_and_per_caller_dictionary_values(self):
        contract = self.install()
        self.assertEqual(set(self.host.accounts[self.alice]), {"py_counter", "py_counter_package", "py_counter_access"})
        self.assertEqual(set(self.host.contracts[contract.contract]), {"owner", "paused", "count", "increments"})
        contract.invoke("increment_by", {"amount": CLU32(5)}, caller=self.alice)
        contract.invoke("increment_by", {"amount": CLU32(2)}, caller=self.bob)
        self.assertEqual(contract.invoke("get").value, 7)
        from casthon import CLKey
        self.assertEqual(contract.invoke("get_increments", {"owner": CLKey(self.alice)}).value, 5)
        self.assertEqual(contract.invoke("get_increments", {"owner": CLKey(self.bob)}).value, 2)
        with self.assertRaises(ValueError):
            contract.invoke("call")

    def test_argument_errors_and_failed_partial_writes_roll_back(self):
        contract = self.install()
        with self.assertRaises(MissingArgument):
            contract.invoke("increment_by")
        with self.assertRaises(ABIError):
            contract.invoke("increment_by", raw_args={"amount": b"bad"})
        self.host.fail_next("dictionary_put", Read())
        with self.assertRaises(Read):
            contract.invoke("increment_by", {"amount": CLU32(5)})
        self.assertEqual(contract.invoke("get").value, 0)
        self.assertTrue(any(name == "write" for name, args in self.host.calls))
        contract.invoke("increment_by", {"amount": CLU32(5)})
        self.assertEqual(contract.invoke("get").value, 5)
        with self.assertRaises(InvalidArgument):
            self.harness.invoke("call", caller=self.alice)

    def test_missing_binding_and_overflow_leave_existing_state_intact(self):
        contract = self.install()
        seed = self.host.contracts[contract.contract].pop("increments")
        with self.assertRaises(MissingKey):
            contract.invoke("increment")
        self.assertEqual(contract.invoke("get").value, 0)
        self.host.contracts[contract.contract]["increments"] = seed
        contract.invoke("increment_by", {"amount": CLU32(0xffffffff)})
        with self.assertRaises(ABIError):
            contract.invoke("increment")
        self.assertEqual(contract.invoke("get").value, 0xffffffff)

    def test_strict_registered_metadata_checks_cltypes_before_python(self):
        self.host.strict_arguments = True
        contract = self.install()
        with self.assertRaises(InvalidArgument):
            contract.invoke("increment_by", {"amount": CLString("")})
        with self.assertRaises(ValueError):
            contract.invoke("increment_by", raw_args={"amount": bytes(4)})
        self.assertEqual(contract.invoke("get").value, 0)

    def test_unknown_host_operations_and_capability_violations_fail_loudly(self):
        with use_host(self.host):
            key = storage.new_uref(CLU32(7))
            runtime.named_keys["read_only"] = URef(key.address, 1)
        with self.host.context(account=self.alice), use_host(self.host):
            self.assertEqual(runtime.named_keys["read_only"].read(U32), 7)
            with self.assertRaises(MockAccessError):
                key.write(CLU32(8))
        with self.host.context(account=self.bob), use_host(self.host):
            with self.assertRaises(MockAccessError):
                key.read(U32)
        with self.assertRaises(UnsupportedHostCall):
            self.host.verify_signature(b"", b"", b"")

    def test_arguments_cannot_grant_a_callers_stolen_uref(self):
        from casthon import CLKey
        with use_host(self.host):
            key = storage.new_uref(CLU32(7))
            runtime.named_keys["owned"] = key
        def consume(value: URef) -> U32:
            return storage.read_or_revert(value, U32)
        harness = ContractHarness(types.ModuleType("fixture"), host=self.host, exports={"consume": consume})
        self.assertEqual(harness.invoke("consume", {"value": CLKey(key)}, caller=self.alice).value, 7)
        with self.assertRaises(MockAccessError):
            harness.invoke("consume", {"value": CLKey(key)}, caller=self.bob)
        self.assertNotIn(self.bob, self.host.accounts)

    def test_dictionary_operations_accept_an_ordinary_seed_uref(self):
        with use_host(self.host):
            seed = storage.new_uref(CLU32(3))
            storage.dictionary_put(seed, "item", CLU32(9))
            self.assertEqual(storage.dictionary_get(seed, "item", U32), 9)

    def test_contract_exception_handlers_cannot_hide_missing_mock_support(self):
        def call() -> None:
            try:
                self.host.unimplemented_function()
            except Exception:
                pass
        harness = ContractHarness(types.ModuleType("fixture"), host=self.host, exports={"call": call})
        with self.assertRaises(UnsupportedHostCall):
            harness.invoke("call")


class NativeBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.host = MockHost()
        self.harness = ContractHarness(typed_exports, host=self.host)

    def test_optional_defaults_and_imported_exports(self):
        from casthon import CLValue
        from typing import Optional
        self.assertEqual(self.harness.invoke("calculate", {"amount": CLU32(5), "label": CLString("abc")}).value, 8)
        self.assertEqual(self.harness.invoke("defaults").value, "default:7")
        self.assertEqual(self.harness.invoke("defaults", {"amount": CLValue(Optional[U32], None)}).value, "default:None")
        with self.assertRaises(MissingArgument):
            self.harness.invoke("nullable")
        with self.assertRaises(ABIError):
            self.harness.invoke("defaults", raw_args={"amount": b"\2"})

    def test_return_validation_and_ret_commit_only_successful_cleanup(self):
        self.assertEqual(self.harness.invoke("checked_return", {"operation": CLString("plain")}).value, 7)
        key = self.host.accounts[self.host.caller]["typed_cleanup"]
        before = self.host.cells[key.address]
        for operation in ("overflow", "negative", "bool", "none", "wrong_cl_type", "bad_payload"):
            with self.subTest(operation=operation), self.assertRaises(InvalidArgument):
                self.harness.invoke("checked_return", {"operation": CLString(operation)})
            self.assertEqual(self.host.cells[key.address], before)
        self.assertEqual(self.harness.invoke("early_ret", {"amount": CLU32(13)}).value, 13)
        from casthon.testing.values import inspect_value
        self.assertEqual(inspect_value(self.host.cells[key.address])[1], 2)

    def test_caught_errors_commit_and_escaping_python_errors_keep_tracebacks(self):
        def write():
            runtime.named_keys["trace"] = storage.new_uref(CLU32(1))

        def caught() -> U32:
            write()
            try:
                raise User(7)
            except User:
                return 3

        def unexpected() -> None:
            write()
            raise ValueError("original Python bug")

        harness = ContractHarness(types.ModuleType("fixture"), host=self.host,
                                  exports={"caught": caught, "unexpected": unexpected})
        self.assertEqual(harness.invoke("caught").value, 3)
        before = self.host.accounts[self.host.caller]["trace"]
        with self.assertRaisesRegex(ValueError, "original Python bug"):
            harness.invoke("unexpected")
        self.assertEqual(self.host.accounts[self.host.caller]["trace"], before)

    def test_invalid_ret_payload_rolls_back_and_keyboard_interrupt_is_not_reclassified(self):
        def broken() -> None:
            runtime.named_keys["trace"] = storage.new_uref(CLU32(1))
            raise Ret(b"bad")

        def interrupted() -> None:
            runtime.named_keys["trace"] = storage.new_uref(CLU32(1))
            raise KeyboardInterrupt()

        harness = ContractHarness(types.ModuleType("fixture"), host=self.host,
                                  exports={"broken": broken, "interrupted": interrupted})
        with self.assertRaises(InvalidArgument):
            harness.invoke("broken")
        with self.assertRaises(KeyboardInterrupt):
            harness.invoke("interrupted")
        self.assertNotIn("trace", self.host.accounts.get(self.host.caller, {}))

    def test_discovery_does_not_expose_unmarked_helpers_and_testing_cannot_freeze(self):
        with self.assertRaises(ValueError):
            self.harness.invoke("_mark")
        from bundle import check_profile
        for code in ("from casthon.testing import MockHost", "from casthon import testing", "import casthon.testing.live"):
            with self.assertRaises(ValueError):
                check_profile(ast.parse(code))

    def test_native_and_builder_signatures_share_the_same_wire_policy(self):
        from bundle import export_signatures
        from casthon import wire_type
        from casthon.arguments import argument_type, optional_arg_inner
        compiled = export_signatures(Path(typed_exports.__file__).resolve(), list(self.harness.exports))
        def canonical(signature):
            arguments, typed, returns = signature
            return [(name, wire_type(argument_type(annotation)),
                     optional_arg_inner(annotation) is not None, default)
                    for name, annotation, default in arguments], typed, wire_type(returns) if typed else None
        self.assertEqual({name: canonical(value) for name, value in compiled.items()},
                         {name: canonical(value) for name, value in self.harness.signatures.items()})

    def test_external_project_root_resolves_reusable_contract_modules(self):
        from bundle import load_contract, generate_exports, contract_modules
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            contracts = root / "contracts"
            contracts.mkdir()
            (contracts / "__init__.py").write_text("")
            (contracts / "shared.py").write_text("from casthon import U32\ndef calculate(amount: U32) -> U32: return amount + 1\n")
            path = contracts / "token.py"
            path.write_text("from casthon import export\nfrom contracts.shared import calculate\nread = export(calculate)\n")
            declaration, _ = load_contract(path, project_root=root)
            self.assertEqual(declaration["signatures"]["read"]["args"][0]["type"], "U32")
            self.assertIn("'read'", generate_exports(path, declaration["exports"], project_root=root))
            self.assertIn("contracts/shared.py", contract_modules(path, project_root=root))
