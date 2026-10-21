"""Explicit failure policy before contract dispatch, using isolated VM probes."""

import json
import subprocess
import sys
from pathlib import Path

from test_wasm_basic import WasmTestCase
from wasm_harness import Harness, ROOT, build_file, envelope


class BootstrapWasmTests(WasmTestCase):
    def test_bootstrap_failures_before_dispatch(self):
        result = subprocess.run([sys.executable, ROOT / "tests/build_bootstrap_probes.py",
            build_file("dispatch_smoke.wasm").parent], check=True, text=True, capture_output=True)
        report = json.loads(Path(result.stdout.strip()).read_text())
        for item in report["cases"]:
            for suffix in (".wasm", ".metered.wasm"):
                with self.subTest(case=item["name"], suffix=suffix):
                    host = Harness(Path(report["work"]) / (item["name"] + suffix))
                    if item["code"] is None:
                        self.assertEqual(host.invoke("call"), envelope("U32", 1))
                    else:
                        self.assert_reverts(host, "call", {}, item["code"])
                    self.assertIn(item["diagnostic"], "".join(host.prints))
                    self.assertEqual((host.account, host.cells), ({}, {}))
