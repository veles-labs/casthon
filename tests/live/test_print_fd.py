"""Opt-in checks for a launcher/node asset with inherited print-FD support."""

import io
import os
import re
import unittest

from casthon import CLString, CLU32
from casthon.testing import LiveNetworkTest, build_contract


@unittest.skipUnless(os.environ.get("CSPR_PRINT_FD_TESTS") == "1", "Requires print-FD capable launcher/assets")
class TestPrintFD(LiveNetworkTest):
    binary = os.environ.get("CSPR_DEVNET_BIN", "casper-devnet")
    custom_asset = os.environ.get("CSPR_DEVNET_CUSTOM_ASSET")

    def test_debug_stdout_is_captured_from_each_validator(self):
        alice = self.funded_account("printer")
        marker = self.id()
        cursor = self.network.print_cursor
        self.network.deploy(self.build("tests/fixtures/print_fd_session.py"), signer=alice, install=False,
                            args={"marker": CLString(marker)}).assert_success()
        for node in range(1, self.node_count + 1):
            line = self.network.wait_for_print(re.escape(marker) + r": before", since=cursor, node_id=node, timeout=15)
            self.assertIn("Zażółć 🐍", line.text)
            self.network.wait_for_print(re.escape(marker) + r": finally", since=cursor, node_id=node, timeout=15)

    def test_failed_live_test_displays_print_output(self):
        owner = self
        alice = self.funded_account("failing-printer")
        marker = self.id()
        wasm = self.build("tests/fixtures/print_fd_session.py")

        class DeliberateFailure(LiveNetworkTest):
            network = owner.network

            def test_failure(self):
                cursor = self.network.print_cursor
                self.network.deploy(wasm, signer=alice, install=False,
                                    args={"marker": CLString(marker), "mode": CLU32(1)}).assert_failure("User error: 77")
                self.network.wait_for_print(re.escape(marker) + r": finally", since=cursor, node_id=1, timeout=15)
                self.network.wait_for_print("C_DISPATCH_API:", since=cursor, node_id=1, timeout=15)
                self.network.wait_for_print("User: 77", since=cursor, node_id=1, timeout=15)
                self.fail("deliberate failure to verify captured diagnostics")

        output = io.StringIO()
        # Run the case directly: reuse this owned network, without class setup.
        result = unittest.TextTestRunner(stream=output).run(DeliberateFailure("test_failure"))
        self.assertEqual((len(result.failures), len(result.errors)), (1, 0), output.getvalue())
        self.assertIn("Captured Casper prints", output.getvalue())
        self.assertRegex(output.getvalue(), r"node-\d+:")
        self.assertIn("Traceback (most recent call last):", output.getvalue())
        self.assertIn("in call", output.getvalue())
        self.assertIn("User: 77", output.getvalue())
        captured = "\n".join(line.text for line in self.network.print_output)
        self.assertIn(marker + ": before", captured)
        self.assertIn(marker + ": finally", captured)
        (self.network.diagnostics / "failure-example.txt").parent.mkdir(parents=True, exist_ok=True)
        (self.network.diagnostics / "failure-example.txt").write_text(output.getvalue())
        with self.assertRaises(AssertionError) as caught:
            self.network.transactions[-1].assert_success()
        self.assertIn(marker, "\n".join(getattr(caught.exception, "__notes__", ())))

    def test_uncaught_exception_traceback_is_captured(self):
        alice = self.funded_account("traceback-printer")
        marker = self.id()
        wasm = self.build("tests/fixtures/print_fd_session.py")
        cursor = self.network.print_cursor
        self.network.deploy(wasm, signer=alice, install=False,
                            args={"marker": CLString(marker), "mode": CLU32(2)}).assert_failure("User error: 610")
        for node in range(1, self.node_count + 1):
            self.network.wait_for_print("uncaught live failure 🐍", since=cursor, node_id=node, timeout=15)
            output = "\n".join(line.text for line in self.network.prints_since(cursor) if line.node_id == node)
            self.assertIn(marker + ": finally", output)
            self.assertIn("Traceback (most recent call last):", output)
            self.assertIn("in call", output)
            self.assertIn("in nested_failure", output)
            self.assertIn("ValueError", output)

    def test_release_deploys_without_print_output(self):
        alice = self.funded_account("release-printer")
        marker = self.id()
        wasm = build_contract("tests/fixtures/print_fd_session.py", project_root=self.project_root, profile="release")
        cursor = self.network.print_cursor
        self.network.deploy(wasm, signer=alice, install=False,
                            args={"marker": CLString(marker)}).assert_success()
        self.network.deploy(wasm, signer=alice, install=False,
                            args={"marker": CLString(marker), "mode": CLU32(2)}).assert_failure("User error: 610")
        self.assertFalse(any(marker in line.text for line in self.network.prints_since(cursor)))
