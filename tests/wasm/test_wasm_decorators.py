"""Python decorator execution survives freezing, under both unwind backends."""

import sys

from test_wasm_basic import WasmTestCase
from wasm_harness import Harness, ROOT, envelope, payload

sys.path.insert(0, str(ROOT / "src"))
from cspr.testing import build_contract


class DecoratorWasmTests(WasmTestCase):
    runtime = "asyncify"

    @classmethod
    def setUpClass(cls):
        cls.path = build_contract("tests/fixtures/decorated_contract.py", project_root=ROOT,
                                  runtime=cls.runtime)

    def test_stacked_free_function_decorators_keep_order_arguments_and_returns(self):
        for suffix in (".wasm", ".metered.wasm"):
            with self.subTest(suffix=suffix):
                host = Harness(self.path.with_name("decorated_contract" + suffix))
                self.assertEqual(host.invoke("call"), envelope("U32", 12))
                self.assertEqual(host.invoke("call", {"value": payload("U32", 7)}), envelope("U32", 24))

    def test_class_decorator_runs_once_and_finally_unwinds_on_failure(self):
        for suffix in (".wasm", ".metered.wasm"):
            with self.subTest(suffix=suffix):
                host = Harness(self.path.with_name("decorated_contract" + suffix))
                self.assertEqual(host.invoke("read", {"value": payload("U32", 7)}), envelope("U32", 8))
                self.assertEqual("".join(host.prints), "decorator finally\n")
                host.prints.clear()
                self.assert_reverts(host, "read", {}, 65536 + 90)
                self.assertEqual("".join(host.prints).count("decorator finally\n"), 1)
                host.prints.clear()
                self.assert_reverts(host, "read", {"value": b"bad"}, 3)
                self.assertNotIn("decorator finally", "".join(host.prints))


class DecoratorNativeWasmTests(DecoratorWasmTests):
    runtime = "native-errors"
