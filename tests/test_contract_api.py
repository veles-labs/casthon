"""Exercise the actual procedural Python SDK against a scoped host fixture."""

import hashlib
import json
import unittest
from pathlib import Path

import cspr
from cspr import (
    AccountHash,
    Key,
    URef,
    ContractHash,
    ContractPackageHash,
    CLU32,
    CLU256,
    CLKey,
    EntryPoint,
    U32,
    U256,
)
from cspr import api_error
from cspr.codec import ABIError, cl_value, encode, decode
from cspr.entry_points import serialize_entry_points
from cspr.contract_api import runtime, storage
from cspr.testing import use_host
from contracts import basic, api_smoke


class MemoryHost:
    def __init__(self):
        self.keys, self.cells, self.dicts, self.args = {}, {}, {}, {}
        self.next = 1
        self.version_calls = []
        self.owner = AccountHash(bytes([17]) * 32)

    def get_key(self, name):
        if name not in self.keys:
            raise cspr.MissingKey()
        return self.keys[name]

    def has_key(self, name):
        return name in self.keys

    def put_key(self, name, key):
        self.keys[name] = key

    def remove_key(self, name):
        self.keys.pop(name, None)

    def list_named_keys(self):
        return encode("U32", len(self.keys)) + b"".join(
            encode("String", name) + key for name, key in sorted(self.keys.items())
        )

    def get_caller(self):
        return bytes(self.owner)[1:]

    def get_protocol_version(self):
        return (2, 2, 0)

    def get_named_arg(self, name):
        if name not in self.args:
            raise cspr.MissingArgument()
        return self.args[name]

    def blake2b(self, data):
        return hashlib.blake2b(data, digest_size=32).digest()

    def new_uref(self, value):
        key = bytes(URef(self.next.to_bytes(32, "little")))
        self.next += 1
        self.cells[key] = value
        return key

    def read_value(self, key):
        value = self.cells.get(key)
        if value is None:
            raise cspr.ValueNotFound()
        return (
            None
            if value is None
            else value[4 : 4 + int.from_bytes(value[:4], "little")]
        )

    def write(self, key, value):
        self.cells[key] = value

    def add(self, key, value):
        if value[-1] != 7:
            raise ValueError("Host add requires an addable CLType; U32 is unsupported")
        self.cells[key] = cl_value(
            "U256", decode("U256", self.read_value(key)) + decode("U256", value[4:-1])
        )

    def new_dictionary(self):
        key = self.new_uref(cl_value("Unit", None))
        self.dicts[key] = {}
        return key

    def dictionary_get(self, key, item):
        value = self.dicts[key].get(item)
        if value is None:
            raise cspr.ValueNotFound()
        return (
            None
            if value is None
            else value[4 : 4 + int.from_bytes(value[:4], "little")]
        )

    def dictionary_put(self, key, item, value):
        self.dicts[key][item] = value

    def create_contract_package_at_hash(self, is_locked=False):
        return bytes(ContractPackageHash(bytes([11]) * 32)), bytes(
            URef(bytes([12]) * 32)
        )

    def add_contract_version(self, *args):
        self.version_calls.append(args)
        return bytes(ContractHash(bytes([13]) * 32)), len(self.version_calls)

    def disable_contract_version(self, *args):
        self.disabled = args


class ContractApiTests(unittest.TestCase):
    def setUp(self):
        self.host = MemoryHost()
        self.enterContext(use_host(self.host))

    def test_arguments_are_read_explicitly_and_optional_errors_match_rust(self):
        self.assertIsNone(runtime.try_get_named_arg("amount", U32))
        with self.assertRaises(cspr.MissingArgument) as error:
            runtime.get_named_arg("amount", U32)
        self.assertEqual(error.exception.code, 2)
        self.host.args["amount"] = b"bad"
        self.assertIsNone(runtime.try_get_named_arg("amount", U32))
        with self.assertRaises(ABIError):
            runtime.get_named_arg("amount", U32)
        self.host.args["amount"] = encode("U32", 5)
        self.assertEqual(runtime.get_named_arg("amount", U32), 5)

    def test_storage_and_named_keys_have_separate_explicit_operations(self):
        count = storage.new_uref(CLU256(7))
        self.assertEqual(self.host.keys, {})
        runtime.put_key("count", count)
        self.assertIsInstance(runtime.get_key("count"), URef)
        storage.add(count, CLU256(5))
        self.assertEqual(storage.read(count, U256), 12)
        storage.write(count, CLU256(9))
        self.assertEqual(storage.read_or_revert(count, U256), 9)
        self.assertEqual(runtime.list_named_keys(), {"count": count})
        runtime.remove_key("count")
        self.assertFalse(runtime.has_key("count"))
        self.assertIsNone(runtime.get_key("count"))
        self.assertIsNone(storage.read(URef(bytes([255]) * 32), U256))
        with self.assertRaises(cspr.ValueNotFound) as error:
            storage.read_or_revert(URef(bytes([255]) * 32), U256)
        self.assertEqual(error.exception.code, 6)
        self.host.cells[bytes(count)] = cl_value("String", "bad")
        with self.assertRaises(cspr.Read) as error:
            storage.read_or_revert(count, U256)
        self.assertEqual(error.exception.code, api_error.READ)
        self.host.args["amount"] = b"bad"
        with self.assertRaises(ABIError):
            runtime.get_named_arg("amount", U32)

    def test_unit_reads_and_optional_key_variant_failures(self):
        unit = storage.new_uref(cspr.CLUnit())
        self.assertIsNone(storage.read_or_revert(unit, None))
        self.host.args["address"] = bytes(self.host.owner)
        self.assertIsNone(runtime.try_get_named_arg("address", ContractHash))
        with self.assertRaises(ABIError):
            runtime.get_named_arg("address", ContractHash)
        self.host.args["unit"] = b""
        self.assertIsNone(runtime.get_named_arg("unit", None))

    def test_dictionary_uses_seed_urefs_and_byte_length_limits(self):
        seed = storage.new_dictionary("balances")
        self.assertEqual(runtime.get_key("balances"), seed)
        self.assertIsNone(storage.dictionary_get(seed, "missing", U256))
        storage.dictionary_put(seed, "holder", CLU256(42))
        self.assertEqual(storage.dictionary_get(seed, "holder", U256), 42)
        for item in ("x" * 65, "ż" * 33):
            with self.assertRaises(cspr.DictionaryItemKeyExceedsLength) as error:
                storage.dictionary_put(seed, item, CLU256(1))
            self.assertEqual(error.exception.code, 36)

    def test_storage_failures_are_catchable_and_run_finally(self):
        seed = storage.new_dictionary("balances")
        bad = storage.new_uref(cspr.CLString("bad"))
        missing = URef(bytes([255]) * 32)
        for operation, expected_type, code in (
            (lambda: storage.read_or_revert(missing, U32), cspr.ValueNotFound, 6),
            (lambda: storage.read_or_revert(bad, U32), cspr.Read, 5),
            (lambda: storage.dictionary_get(seed, "x" * 65, U32), cspr.DictionaryItemKeyExceedsLength, 36),
            (lambda: storage.dictionary_put(seed, "x" * 65, CLU32(1)), cspr.DictionaryItemKeyExceedsLength, 36),
        ):
            events = []
            try:
                operation()
            except Exception as error:
                self.assertIsInstance(error, expected_type)
                self.assertIsInstance(error, cspr.ApiError)
                events.append(error.code)
            finally:
                events.append("finally")
            self.assertEqual(events, [code, "finally"])

    def test_package_abi_is_supplied_by_python_and_does_not_bind_keys(self):
        package, access = storage.create_contract_package_at_hash()
        self.assertIsInstance(package, ContractPackageHash)
        self.assertEqual(self.host.keys, {})
        entries = [EntryPoint("get", {}, U32)]
        count = storage.new_uref(CLU32(0))
        contract, version = storage.add_contract_version(
            package, entries, {"count": count}, ("events",)
        )
        self.assertIsInstance(contract, ContractHash)
        self.assertEqual(version, 1)
        self.assertEqual(
            self.host.version_calls,
            [
                (
                    bytes(package),
                    serialize_entry_points(entries),
                    encode("U32", 1) + encode("String", "count") + bytes(count),
                    encode("U32", 1) + encode("String", "events") + b"\0",
                )
            ],
        )
        self.assertEqual(self.host.keys, {})
        storage.disable_contract_version(package, contract)
        self.assertEqual(self.host.disabled, (bytes(package), bytes(contract)))

    def test_explicit_contract_calls_decode_payloads_and_ret_serializes_clvalue(self):
        calls = []
        self.host.call_contract = lambda *args: calls.append(args) or encode("U32", 42)
        key = ContractHash(bytes(32))
        self.assertEqual(
            runtime.call_contract(
                key, "answer", {"owner": CLKey(self.host.owner)}, U32
            ),
            42,
        )
        self.assertEqual(
            calls[0],
            (
                bytes(key),
                "answer",
                encode("U32", 1)
                + encode("String", "owner")
                + cl_value("Key", self.host.owner),
            ),
        )
        with self.assertRaises(cspr.Ret) as returned:
            runtime.ret(CLU32(42))
        self.assertEqual(returned.exception.payload, cl_value("U32", 42))

    def test_procedural_basic_and_api_smoke_execute_under_cpython(self):
        basic.call()
        self.assertEqual(len(self.host.version_calls), 1)
        # Switch to the stored contract's named keys for direct Python calls.
        self.host.keys.update(
            {
                name: key
                for name, key in zip(("count", "total", "mode"), self.host.cells)
            }
        )
        basic.increment()
        self.host.args["amount"] = encode("U32", 5)
        basic.increment_by()
        self.assertEqual(basic.get().to_bytes(), cl_value("U32", 6))
        self.host.args["amount"] = encode("U32", 3)
        basic.add_fractional()
        self.assertEqual(basic.get().to_bytes(), cl_value("U32", 7))
        self.host.args = {}
        with self.assertRaises(cspr.Ret) as returned:
            api_smoke.call()
        self.assertEqual(returned.exception.payload, cl_value("U32", 12))
        self.assertEqual(runtime.get_caller(), self.host.owner)
        self.assertFalse(runtime.has_key("temporary"))

    def test_basic_errors_are_catchable_python_exceptions(self):
        with self.assertRaises(cspr.MissingKey) as error:
            basic.get()
        self.assertEqual(error.exception.code, api_error.MISSING_KEY)
        self.host.keys["mode"] = bytes(storage.new_uref(cspr.CLU8(0)))
        with self.assertRaises(cspr.User) as error:
            basic.increment()
        self.assertIsInstance(error.exception, cspr.ApiError)
        self.assertEqual(error.exception.code, api_error.user(100))
        self.host.args["mode"] = encode("U8", 2)
        with self.assertRaises(cspr.InvalidArgument):
            basic.set_mode()

    def test_revert_bypasses_exception_handlers_and_runs_finally(self):
        events = []
        with self.assertRaises(cspr.Revert) as error:
            try:
                runtime.revert(api_error.user(43))
            except Exception:
                events.append("caught")
            finally:
                events.append("finally")
        self.assertEqual(events, ["finally"])
        self.assertEqual(error.exception.code, api_error.user(43))
        self.assertEqual(str(error.exception), str(api_error.user(43)))

    def test_revert_can_be_caught_explicitly_and_finally_can_replace_it(self):
        events = []
        try:
            runtime.revert(api_error.READ)
        except cspr.Revert as error:
            events.append(error.code)
        finally:
            events.append("finally")
        self.assertEqual(events, [api_error.READ, "finally"])
        with self.assertRaises(cspr.Revert) as error:
            try:
                runtime.revert(api_error.READ)
            finally:
                runtime.revert(api_error.MISSING_KEY)
        self.assertEqual(error.exception.code, api_error.MISSING_KEY)

    def test_api_and_user_errors_are_caught_by_exception(self):
        for raised in (cspr.ApiError(api_error.READ), cspr.UserError(44)):
            try:
                raise raised
            except Exception as caught:
                self.assertIs(caught, raised)
                self.assertIsInstance(caught, cspr.ApiError)
            else:
                self.fail("API exception was not caught")
        self.assertIs(cspr.UserError, cspr.User)

    def test_no_contract_authoring_framework_and_export_is_an_identity(self):
        for name in (
            "Contract",
            "Stored",
            "entrypoint",
            "cl_enum",
        ):
            self.assertFalse(hasattr(cspr, name))
        self.assertIs(cspr.export(basic.call), basic.call)


class ReferenceTests(unittest.TestCase):
    def test_all_key_variants_and_explicit_abi_match_independent_rust_fixtures(self):
        fixture = json.loads(
            (
                Path(__file__).resolve().parents[1] / "reference/cep18/fixtures.json"
            ).read_text()
        )
        for f in fixture["keys"]:
            key = Key.from_bytes(bytes.fromhex(f["input"]))
            self.assertIsNot(type(key), Key)
            self.assertEqual(bytes(key).hex(), f["bytes"])
            self.assertEqual(str(key), f["formatted"])
        types = {"0b": Key, "07": U256, "03": cspr.U8, "0a": str, "09": None}
        entries = [
            EntryPoint(
                f["name"],
                {a["name"]: types[a["cl_type"]] for a in f["args"]},
                types[f["returns"]],
            )
            for f in fixture["abi"]
        ]
        self.assertEqual(serialize_entry_points(entries).hex(), fixture["entry_points"])
        self.assertEqual(serialize_entry_points(tuple(entries)).hex(), fixture["entry_points"])
        with self.assertRaises(ABIError):
            serialize_entry_points([EntryPoint("get", {}), EntryPoint("get", {})])
