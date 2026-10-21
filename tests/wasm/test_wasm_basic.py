"""Compiled contract ABI, storage, integer and software-float regression tests."""

import json
import unittest
import wasmtime

from wasm_harness import Harness, Revert, ROOT, build_file, envelope, load_module, payload, text, u32


class WasmTestCase(unittest.TestCase):
    def assert_reverts(self, host, entry, args, code):
        with self.assertRaises(Revert) as error:
            host.invoke(entry, args)
        self.assertEqual(error.exception.code, code)


def installed():
    host = Harness(build_file("basic.metered.wasm"))
    host.invoke("call")
    return host


def imported_signatures(data):
    """Read actual Wasm type/import sections independently of native/casper.h."""
    offset = 8

    def byte():
        nonlocal offset
        value = data[offset]
        offset += 1
        return value

    def uint():
        value = shift = 0
        while True:
            part = byte()
            value |= (part & 127) << shift
            if not part & 128:
                return value
            shift += 7

    def string():
        nonlocal offset
        size = uint()
        value = data[offset:offset + size].decode()
        offset += size
        return value

    def vector(read):
        return [read() for _ in range(uint())]

    def value_type():
        return {0x7f: "i32", 0x7e: "i64", 0x7d: "f32", 0x7c: "f64"}[byte()]

    def function_type():
        assert byte() == 0x60
        return {"parameters": vector(value_type), "results": vector(value_type)}

    def function_import():
        assert string() == "env"
        name = string()
        assert byte() == 0, "Only function imports are supported"
        return {"name": name, **types[uint()]}

    types, imports = [], []
    assert data[:8] == b"\0asm\x01\0\0\0"
    while offset < len(data):
        section, size = byte(), uint()
        end = offset + size
        if section == 1:
            types = vector(function_type)
        if section == 2:
            imports = vector(function_import)
        offset = end
    return sorted(imports, key=lambda item: item["name"])


class BasicWasmTests(WasmTestCase):
    def test_function_exports_match_selected_python_exports(self):
        for target in ("basic", "counter", "counter_session", "my_token", "api_smoke", "ffi_smoke", "dispatch_smoke", "native_unwind", "typed_exports"):
            expected = set(json.loads(build_file(target + ".json").read_text())["exports"])
            for suffix in (".wasm", ".metered.wasm"):
                with self.subTest(target=target, suffix=suffix):
                    module = load_module(build_file(target + suffix))
                    self.assertEqual({item.name for item in module.exports
                                      if isinstance(item.type, wasmtime.FuncType)}, expected)
        with self.subTest(target="readback"):
            module = load_module(build_file("readback.wasm"))
            self.assertEqual({item.name for item in module.exports
                              if isinstance(item.type, wasmtime.FuncType)}, {"call"})

    def test_c_readback_helper_calls_a_counter_without_external_initialization(self):
        for suffix in (".wasm", ".metered.wasm"):
            with self.subTest(suffix=suffix):
                host = Harness(build_file("counter" + suffix))
                host.invoke("call", {"initial": payload("U32", 7)})
                host.contract_module = host.module
                host.module = load_module(build_file("readback.wasm"))
                args = {"contract_hash": bytes([13]) * 32, "expected": payload("U32", 7)}
                self.assertIsNone(host.invoke("call", args))
                self.assert_reverts(host, "call", {**args, "expected": payload("U32", 8)}, 65542)

    def test_all_58_upstream_ext_ffi_signatures(self):
        expected = json.loads((ROOT / "reference/ext-ffi.json").read_text())["functions"]
        self.assertEqual(len(expected), 58)
        for target in ("basic", "counter", "counter_session", "my_token", "api_smoke", "ffi_smoke", "dispatch_smoke", "native_unwind", "typed_exports"):
            with self.subTest(target=target):
                self.assertEqual(imported_signatures(build_file(target + ".wasm").read_bytes()), expected)

    def test_integer_only_casper_imports_and_explicit_exports(self):
        host = Harness(build_file("basic.metered.wasm"))
        self.assertTrue(all(item.module == "env" and
            (item.name.startswith("casper_") or item.name == "gas") for item in host.module.imports))
        names = {item.name for item in host.module.exports}
        self.assertTrue({"call", "get", "get_big", "get_mode", "set_mode", "increment", "increment_by"} <= names)
        self.assertNotIn("_check_active", names)
        self.assertFalse(any(name.startswith("asyncify_") for name in names))

    def test_exports_and_entry_points_are_separate_interfaces(self):
        host = installed()
        expected = [
            ("add_big", [("amount", 7)], 9), ("add_fractional", [("amount", 4)], 9),
            ("fail_after_write", [], 9), ("get", [], 4), ("get_big", [], 7),
            ("get_mode", [], 3), ("increment", [], 9), ("increment_by", [("amount", 4)], 9),
            ("mode_name", [], 10), ("set_mode", [("mode", 3)], 9),
        ]
        serialized = u32(10) + b"".join(text(name) + text(name) + u32(len(args)) +
            b"".join(text(label) + bytes([kind]) for label, kind in args) + bytes([returns, 1, 1, 0])
            for name, args, returns in expected)
        self.assertEqual(host.entry_points, serialized)
        self.assertNotIn("_increment_by", [item.name for item in host.module.exports])
        self.assertNotIn(b"call", host.entry_points)

    def test_frozen_storage_persists_across_fresh_instances(self):
        host = installed()
        self.assertTrue({"py_basic", "py_basic_package", "py_basic_access"} <= host.account.keys())
        for name, kind, value in (("count", "U32", 0), ("mode", "U8", 1), ("total", "U256", 0)):
            self.assertEqual(host.stored(name), envelope(kind, value))
        host.invoke("increment")
        host.invoke("increment_by", {"amount": payload("U32", 5)})
        self.assertEqual(host.invoke("get"), envelope("U32", 6))
        self.assert_reverts(host, "call", {}, 3)
        self.assertEqual(host.invoke("get"), envelope("U32", 6))

    def test_modes_raise_typed_errors_and_return_explicit_clvalues(self):
        host = installed()
        self.assertEqual(host.invoke("mode_name"), envelope("String", "ACTIVE"))
        host.invoke("set_mode", {"mode": payload("U8", 0)})
        self.assertEqual(host.invoke("get_mode"), envelope("U8", 0))
        self.assertEqual(host.invoke("mode_name"), envelope("String", "PAUSED"))
        self.assert_reverts(host, "increment", {}, 65536 + 100)
        self.assert_reverts(host, "set_mode", {"mode": payload("U8", 2)}, 3)
        self.assertEqual(host.stored("mode"), envelope("U8", 0))
        host.invoke("set_mode", {"mode": payload("U8", 1)})
        host.invoke("increment")
        self.assertEqual(host.invoke("get"), envelope("U32", 1))

    def test_arbitrary_precision_u256_boundaries(self):
        host = installed()
        value = (1 << 200) + (1 << 64) + 123
        host.invoke("add_big", {"amount": payload("U256", value)})
        self.assertEqual(host.invoke("get_big"), envelope("U256", value))
        maximum = (1 << 256) - 1
        host.invoke("add_big", {"amount": payload("U256", maximum - value)})
        self.assertEqual(host.invoke("get_big"), envelope("U256", maximum))
        self.assert_reverts(host, "add_big", {"amount": payload("U256", 1)}, 3)
        self.assertEqual(host.invoke("get_big"), envelope("U256", maximum))

    def test_binary64_fractional_addition_truncation_and_u32_boundaries(self):
        for suffix in (".wasm", ".metered.wasm"):
            for current, amount, expected in (
                (0, 0, 0), (0, 1, 0), (0, 3, 1), (6, 3, 7), (6, 4, 8),
                (0, 0xffffffff, 0x7fffffff), (0x80000000, 1, 0x80000000),
                (0xffffffff, 1, 0xffffffff), (0xfffffffe, 3, 0xffffffff),
            ):
                with self.subTest(suffix=suffix, current=current, amount=amount):
                    host = Harness(build_file("basic" + suffix))
                    host.invoke("call")
                    host.invoke("increment_by", {"amount": payload("U32", current)})
                    host.invoke("add_fractional", {"amount": payload("U32", amount)})
                    self.assertEqual(host.invoke("get"), envelope("U32", expected))
            host = Harness(build_file("basic" + suffix))
            host.invoke("call")
            self.assert_reverts(host, "add_fractional", {}, 2)
            self.assert_reverts(host, "add_fractional", {"amount": bytes(3)}, 3)
            host.invoke("increment_by", {"amount": payload("U32", 0xffffffff)})
            self.assert_reverts(host, "add_fractional", {"amount": payload("U32", 2)}, 3)
            self.assertEqual(host.invoke("get"), envelope("U32", 0xffffffff))
            host.invoke("set_mode", {"mode": payload("U8", 0)})
            self.assert_reverts(host, "add_fractional", {"amount": payload("U32", 3)}, 65636)

    def test_invalid_arguments_and_overflow_do_not_change_state(self):
        host = installed()
        self.assert_reverts(host, "increment_by", {}, 2)
        for data in (b"", bytes(3), bytes(5)):
            self.assert_reverts(host, "increment_by", {"amount": data}, 3)
        for data in (b"", bytes([33]) + bytes(33), b"\x01", b"\0\0"):
            self.assert_reverts(host, "add_big", {"amount": data}, 3)
        host.invoke("increment_by", {"amount": payload("U32", 0xffffffff)})
        self.assert_reverts(host, "increment", {}, 3)
        self.assertEqual(host.invoke("get"), envelope("U32", 0xffffffff))

    def test_user_error_rolls_back_host_write(self):
        host = installed()
        self.assert_reverts(host, "fail_after_write", {}, 65637)
        self.assertEqual(host.invoke("get"), envelope("U32", 0))
        self.assertGreater(host.gas, 0)

    def test_procedural_host_api_smoke(self):
        import wasmtime
        host = Harness(build_file("api_smoke.metered.wasm"))
        self.assertEqual(sorted(item.name for item in host.module.exports
            if isinstance(item.type, wasmtime.FuncType)),
            ["call", "call_counter", "read_count"])
        self.assertEqual(host.invoke("call"), envelope("U32", 12))
        self.assertIn("api_smoke_dictionary", host.account)
        self.assertEqual(host.account["api_smoke_caller"], b"\0" + bytes([0x11]) * 32)
        self.assertNotIn("temporary", host.account)
        self.assertEqual(host.invoke("read_count"), envelope("U32", 12))
        self.assert_reverts(host, "call", {}, 3)
        self.assertEqual(host.invoke("read_count"), envelope("U32", 12))

    def test_call_contract_passes_explicit_runtime_args_and_decodes_returns(self):
        host = Harness(build_file("counter.metered.wasm"))
        host.invoke("call")
        host.module = load_module(build_file("api_smoke.metered.wasm"))
        self.assertEqual(host.invoke("call_counter", {"amount": payload("U32", 7)}), envelope("U32", 7))
        host.module = load_module(build_file("counter.metered.wasm"))
        self.assertEqual(host.invoke("get"), envelope("U32", 7))

    def test_missing_state_reverts_at_outer_c_boundary(self):
        host = Harness(build_file("basic.metered.wasm"))
        self.assert_reverts(host, "get", {}, 24)
        self.assertIn("C_DISPATCH_API:MissingKey", "".join(host.prints))
