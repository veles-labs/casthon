"""Real constructor allocation, binding and cleanup in frozen MicroPython."""

import json

from cspr.testing import build_contract

from test_wasm_basic import WasmTestCase
from wasm_harness import Harness, ROOT, build_file, envelope, payload


class ClassConstructorWasmTests(WasmTestCase):
    runtime = None

    @classmethod
    def setUpClass(cls):
        report = json.loads(build_file("counter-build-report.json").read_text())
        cls.wasm = build_contract(ROOT / "tests/fixtures/constructor_contract.py",
            runtime=cls.runtime or ("asyncify" if report["asyncify"] else "native-errors"),
            minify=report.get("minification", {}).get("enabled", False))

    def hosts(self):
        for suffix in (".wasm", ".metered.wasm"):
            yield suffix, Harness(self.wasm.with_name("constructor_contract" + suffix))

    def test_required_constructor_runs_once_and_temporary_attributes_do_not_persist(self):
        for suffix, host in self.hosts():
            with self.subTest(suffix=suffix):
                host.invoke("call", {"initial": payload("U32", 7)})
                self.assertEqual(set(host.account), {"py_constructor"})
                self.assertEqual(set(host.contract), {"value", "items"})
                allocated = host.next
                self.assertEqual(host.invoke("get"), envelope("U32", 9))
                self.assertEqual(host.invoke("get"), envelope("U32", 9))
                self.assertEqual(host.next, allocated)

    def test_new_state_is_independent_from_the_current_contract(self):
        for suffix, host in self.hosts():
            with self.subTest(suffix=suffix):
                host.invoke("call", {"initial": payload("U32", 7)})
                keys = host.contract.copy()
                self.assertEqual(host.invoke("read_new", {"initial": payload("U32", 20)}), envelope("U32", 21))
                self.assertEqual(host.contract, keys)
                self.assertEqual(host.invoke("get"), envelope("U32", 9))
                seed = keys["items"][1:33].hex()
                self.assertEqual(host.dictionaries[seed], {"initial": envelope("U32", 7), "after": envelope("U32", 8)})

    def test_constructor_state_and_finally_writes_roll_back_on_failure(self):
        for suffix, host in self.hosts():
            with self.subTest(suffix=suffix):
                host.invoke("call", {"initial": payload("U32", 7)})
                cells, dictionaries, allocated = host.cells.copy(), {k: v.copy() for k, v in host.dictionaries.items()}, host.next
                self.assert_reverts(host, "fail", {}, 65536 + 79)
                self.assertIn("CONSTRUCTOR_FINALLY", "".join(host.prints))
                self.assertEqual(host.cells, cells)
                self.assertEqual(host.dictionaries, dictionaries)
                self.assertEqual(host.next, allocated)

    def test_field_write_preserves_bound_uref_without_allocating_a_new_cell(self):
        for suffix, host in self.hosts():
            with self.subTest(suffix=suffix):
                host.invoke("call", {"initial": payload("U32", 7)})
                original = host.contract["value"]
                allocated = host.next
                self.assertEqual(host.invoke("update", {"value": payload("U32", 20)}), envelope("U32", 8))
                self.assertEqual(host.contract["value"], original)
                self.assertEqual(host.cells[original[1:33].hex()], envelope("U32", 20))
                self.assertEqual(host.next, allocated)
                self.assertEqual(host.invoke("get"), envelope("U32", 21))

    def test_field_write_keeps_the_new_instances_state_isolated(self):
        for suffix, host in self.hosts():
            with self.subTest(suffix=suffix):
                host.invoke("call", {"initial": payload("U32", 7)})
                original = host.contract.copy()
                self.assertEqual(host.invoke("update_new", {"initial": payload("U32", 20)}), envelope("U32", 22))
                self.assertEqual(host.contract, original)
                self.assertEqual(host.invoke("get"), envelope("U32", 9))


class ClassConstructorNativeWasmTests(ClassConstructorWasmTests):
    runtime = "native-errors"
