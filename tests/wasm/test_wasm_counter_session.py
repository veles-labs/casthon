"""A session imports the counter ABI and calls a separate deployed Wasm module."""

import wasmtime

from test_wasm_basic import WasmTestCase
from wasm_harness import Harness, build_file, envelope, load_module, payload


def installed(suffix):
    host = Harness(build_file("counter" + suffix))
    host.invoke("call")
    host.contract_module = host.module
    host.module = load_module(build_file("counter_session" + suffix))
    return host


def arguments(amount, expected):
    return {"contract": b"\x01" + bytes([13]) * 32,
            "amount": payload("U32", amount), "expected": payload("U32", expected)}


class CounterSessionWasmTests(WasmTestCase):
    def test_only_call_is_exported_and_remote_results_are_ordinary_python_values(self):
        for suffix in (".wasm", ".metered.wasm"):
            with self.subTest(suffix=suffix):
                host = installed(suffix)
                self.assertEqual(sorted(item.name for item in host.module.exports
                    if isinstance(item.type, wasmtime.FuncType)), ["call"])
                self.assertEqual(host.invoke("call", arguments(5, 5)), envelope("U32", 5))
                self.assertEqual(host.invoke("call", arguments(2, 7)), envelope("U32", 7))
                self.assertEqual(host.stored("count"), envelope("U32", 7))
                self.assertEqual(set(host.account), {"py_counter", "py_counter_package", "py_counter_access"})
                seed = host.contract["increments"][1:33].hex()
                self.assertEqual(host.dictionaries[seed][host.caller.hex()], envelope("U32", 7))

    def test_session_revert_rolls_back_successful_contract_calls(self):
        for suffix in (".wasm", ".metered.wasm"):
            with self.subTest(suffix=suffix):
                host = installed(suffix)
                self.assert_reverts(host, "call", arguments(5, 99), 65537)
                self.assertEqual(host.stored("count"), envelope("U32", 0))
                self.assertNotIn("count", host.account)
                self.assertEqual(host.invoke("call", arguments(3, 3)), envelope("U32", 3))

    def test_callee_failure_aborts_the_session(self):
        for suffix in (".wasm", ".metered.wasm"):
            with self.subTest(suffix=suffix):
                host = installed(suffix)
                host.invoke("call", arguments(0xffffffff, 0xffffffff))
                self.assert_reverts(host, "call", arguments(1, 0), 3)
                self.assertEqual(host.stored("count"), envelope("U32", 0xffffffff))
