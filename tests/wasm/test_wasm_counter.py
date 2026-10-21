"""Typed named-key and dictionary references in frozen Python."""

import wasmtime

from test_wasm_basic import WasmTestCase
from wasm_harness import Harness, build_file, envelope, payload


def owner(host):
    return b"\0" + host.caller


class CounterWasmTests(WasmTestCase):
    def test_inherited_ownership_pause_controls_and_transfer(self):
        for suffix in (".wasm", ".metered.wasm"):
            with self.subTest(suffix=suffix):
                host = Harness(build_file("counter" + suffix))
                alice = owner(host)
                host.invoke("call", {"initial": payload("U32", 3)})
                self.assertEqual(host.invoke("get_owner"), envelope("Key", alice))
                self.assertEqual(host.invoke("is_paused"), envelope("Bool", False))
                host.caller = bytes([0x22]) * 32
                bob = owner(host)
                self.assert_reverts(host, "pause", {}, 65536 + 100)
                self.assert_reverts(host, "transfer_ownership", {"new_owner": bob}, 65536 + 100)
                host.caller = alice[1:]
                host.invoke("pause")
                self.assertEqual(host.invoke("is_paused"), envelope("Bool", True))
                self.assert_reverts(host, "increment", {}, 65536 + 101)
                self.assert_reverts(host, "increment_by", {"amount": payload("U32", 7)}, 65536 + 101)
                self.assertEqual(host.invoke("get"), envelope("U32", 3))
                host.caller = bob[1:]
                self.assert_reverts(host, "unpause", {}, 65536 + 100)
                host.caller = alice[1:]
                host.invoke("unpause")
                host.invoke("transfer_ownership", {"new_owner": bob})
                self.assertEqual(host.invoke("get_owner"), envelope("Key", bob))
                self.assert_reverts(host, "pause", {}, 65536 + 100)
                host.caller = bob[1:]
                host.invoke("increment")
                host.invoke("pause")
                self.assertEqual(host.invoke("get"), envelope("U32", 4))
                self.assertEqual(host.invoke("get_increments", {"owner": bob}), envelope("U32", 1))

    def test_explicit_installation_and_per_caller_dictionary_items(self):
        for suffix in (".wasm", ".metered.wasm"):
            with self.subTest(suffix=suffix):
                host = Harness(build_file("counter" + suffix))
                self.assertEqual(sorted(item.name for item in host.module.exports
                    if isinstance(item.type, wasmtime.FuncType)),
                    ["call", "get", "get_increments", "get_owner", "increment", "increment_by", "is_paused", "pause", "transfer_ownership", "unpause"])
                host.invoke("call")
                self.assertEqual(sorted(host.account), ["py_counter", "py_counter_access", "py_counter_package"])
                self.assertEqual(sorted(host.contract), ["count", "increments", "owner", "paused"])
                self.assertEqual(host.invoke("get"), envelope("U32", 0))
                first = owner(host)
                self.assertEqual(host.invoke("get_increments", {"owner": first}), envelope("U32", 0))
                host.invoke("increment")
                host.invoke("increment_by", {"amount": payload("U32", 5)})
                self.assertEqual(host.invoke("get"), envelope("U32", 6))
                self.assertEqual(host.invoke("get_increments", {"owner": first}), envelope("U32", 6))
                host.caller = bytes([0x22]) * 32
                second = owner(host)
                host.invoke("increment_by", {"amount": payload("U32", 3)})
                self.assertEqual(host.invoke("get"), envelope("U32", 9))
                self.assertEqual(host.invoke("get_increments", {"owner": first}), envelope("U32", 6))
                self.assertEqual(host.invoke("get_increments", {"owner": second}), envelope("U32", 3))
                seed = host.contract["increments"][1:33].hex()
                self.assertEqual(sorted(host.dictionaries[seed]), [first[1:].hex(), second[1:].hex()])
                self.assert_reverts(host, "call", {}, 3)
                if suffix == ".metered.wasm":
                    self.assertGreater(host.gas, 0)

    def test_reference_and_dictionary_failures_roll_back_partial_writes(self):
        for suffix in (".wasm", ".metered.wasm"):
            with self.subTest(suffix=suffix):
                host = Harness(build_file("counter" + suffix))
                self.assert_reverts(host, "get", {}, 24)
                host.invoke("call")
                self.assert_reverts(host, "increment_by", {}, 2)
                self.assert_reverts(host, "increment_by", {"amount": bytes(3)}, 3)
                host.invoke("increment_by", {"amount": payload("U32", 0xffffffff)})
                self.assert_reverts(host, "increment", {}, 3)
                self.assertEqual(host.invoke("get"), envelope("U32", 0xffffffff))
                self.assertEqual(host.invoke("get_increments", {"owner": owner(host)}), envelope("U32", 0xffffffff))
                fresh = Harness(build_file("counter" + suffix))
                fresh.invoke("call")
                seed = fresh.contract.pop("increments")
                self.assert_reverts(fresh, "increment", {}, 24)
                self.assertEqual(fresh.invoke("get"), envelope("U32", 0))
                fresh.contract["increments"] = b"\x01" + bytes(32)
                self.assert_reverts(fresh, "increment", {}, 3)
                self.assertEqual(fresh.invoke("get"), envelope("U32", 0))
                fresh.contract["increments"] = seed
                count = fresh.contract["count"][1:33].hex()
                fresh.cells[count] = envelope("String", "bad")
                self.assert_reverts(fresh, "get", {}, 5)
                del fresh.cells[count]
                self.assert_reverts(fresh, "get", {}, 6)
