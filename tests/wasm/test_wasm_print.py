"""Debug forwards built-in stdout; release has no casper_print dependency."""

import json
import sys

from test_wasm_basic import WasmTestCase, imported_signatures
from wasm_harness import Harness, ROOT, envelope, payload

sys.path.insert(0, str(ROOT / "src"))
from casthon.testing import build_contract


class PrintWasmTests(WasmTestCase):
    runtime = "asyncify"

    @classmethod
    def setUpClass(cls):
        cls.artifacts = {
            profile: build_contract("tests/fixtures/print_contract.py", project_root=ROOT,
                                    runtime=cls.runtime, profile=profile)
            for profile in ("debug", "release")
        }

    def test_profiles_have_exact_host_imports_and_separate_caches(self):
        expected = json.loads((ROOT / "reference/ext-ffi.json").read_text())["functions"]
        for profile, path in self.artifacts.items():
            with self.subTest(profile=profile):
                functions = expected if profile == "debug" else [f for f in expected if f["name"] != "casper_print"]
                self.assertEqual(imported_signatures(path.read_bytes()), functions)
                report = json.loads(path.with_name("print_contract-build-report.json").read_text())
                self.assertEqual(report["buildProfile"], profile)
                self.assertEqual(report["debugPrint"], profile == "debug")
                if profile == "release":
                    self.assertNotIn(b"C_DISPATCH_", path.read_bytes())
        debug, release = self.artifacts.values()
        self.assertNotEqual(debug, release)
        self.assertLess(release.stat().st_size, debug.stat().st_size)

    def test_builtin_print_formatting_unicode_and_conversion_side_effects(self):
        for profile, path in self.artifacts.items():
            for suffix in (".wasm", ".metered.wasm"):
                with self.subTest(profile=profile, suffix=suffix):
                    host = Harness(path.with_name("print_contract" + suffix))
                    self.assertEqual(host.invoke("call"), envelope("U32", 1))
                    expected = "count | 7 | object!\nZażółć 🐍\n" if profile == "debug" else ""
                    self.assertEqual("".join(host.prints), expected)

    def test_return_revert_errors_and_finally_keep_their_semantics(self):
        for profile, path in self.artifacts.items():
            for suffix in (".wasm", ".metered.wasm"):
                for mode, code in ((0, 17), (1, 65577), (2, 3), (3, 66146), (4, None), (5, 3), (6, 3)):
                    with self.subTest(profile=profile, suffix=suffix, mode=mode):
                        host = Harness(path.with_name("print_contract" + suffix))
                        args = {"mode": payload("U32", mode)}
                        if code is None:
                            self.assertEqual(host.invoke("fail", args), envelope("U32", 9))
                            self.assertIn("cleanup", host.contract)
                        else:
                            self.assert_reverts(host, "fail", args, code)
                            self.assertEqual((host.account, host.contract, host.cells), ({}, {}, {}))
                        if profile == "debug":
                            self.assertIn("finally\n", "".join(host.prints))
                            self.assertIn("C_DISPATCH_", "".join(host.prints))
                        else:
                            self.assertEqual(host.prints, [])

    def test_uncaught_errors_print_tracebacks_after_finally(self):
        for profile, path in self.artifacts.items():
            for suffix in (".wasm", ".metered.wasm"):
                for mode, code, message in ((0, 17, "ApiError: 17"),
                                            (1, 65577, "Revert: 65577"),
                                            (2, 3, "ABIError: invalid input"),
                                            (7, 66146, "ValueError: nested failure 🐍")):
                    with self.subTest(profile=profile, suffix=suffix, mode=mode):
                        host = Harness(path.with_name("print_contract" + suffix))
                        self.assert_reverts(host, "fail", {"mode": payload("U32", mode)}, code)
                        output = "".join(host.prints)
                        if profile == "debug":
                            self.assertIn("Traceback (most recent call last):\n", output)
                            self.assertIn(', in fail\n', output)
                            self.assertIn(message, output)
                            self.assertLess(output.index("finally\n"), output.index("Traceback"))
                            if mode == 7:
                                self.assertIn(', in nested_failure\n', output)
                                self.assertIn('File "contract.py"', output)
                            for chunk in host.prints:
                                if 'File "' in chunk:
                                    self.assertIn(', in ', chunk)
                        else:
                            self.assertEqual(output, "")

    def test_broken_exception_formatting_preserves_the_original_outcome(self):
        for profile, path in self.artifacts.items():
            for suffix in (".wasm", ".metered.wasm"):
                with self.subTest(profile=profile, suffix=suffix):
                    host = Harness(path.with_name("print_contract" + suffix))
                    self.assert_reverts(host, "fail", {"mode": payload("U32", 8)}, 17)
                    self.assertEqual((host.account, host.contract, host.cells), ({}, {}, {}))
                    if profile == "debug":
                        self.assertIn("finally\n", "".join(host.prints))
                        self.assertIn("UnprintableApiError:", "".join(host.prints))
                    else:
                        self.assertEqual(host.prints, [])

    def test_caught_exceptions_and_successful_ret_have_no_traceback(self):
        for profile, path in self.artifacts.items():
            for suffix in (".wasm", ".metered.wasm"):
                with self.subTest(profile=profile, suffix=suffix):
                    host = Harness(path.with_name("print_contract" + suffix))
                    self.assertEqual(host.invoke("caught"), envelope("U32", 42))
                    self.assertEqual(host.prints, [])
                    self.assertEqual(host.invoke("fail", {"mode": payload("U32", 4)}), envelope("U32", 9))
                    self.assertNotIn("Traceback", "".join(host.prints))

    def test_long_unicode_exception_messages_split_at_utf8_boundaries(self):
        for profile, path in self.artifacts.items():
            for suffix in (".wasm", ".metered.wasm"):
                with self.subTest(profile=profile, suffix=suffix):
                    host = Harness(path.with_name("print_contract" + suffix))
                    self.assert_reverts(host, "fail", {"mode": payload("U32", 9)}, 66146)
                    if profile == "debug":
                        self.assertIn("ValueError: " + "x" * 251 + "🐍" * 100 + " long failure end\n",
                                      "".join(host.prints))
                    else:
                        self.assertEqual(host.prints, [])


class PrintNativeWasmTests(PrintWasmTests):
    runtime = "native-errors"
