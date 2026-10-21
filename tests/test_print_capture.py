"""Print-FD stream framing, bounded storage and live-test error presentation."""

import io
import sys
import tempfile
import threading
import unittest

from cspr.testing import DevnetClient, DevnetNetwork, LiveNetworkTest
from cspr.testing.prints import _PrintCapture, _print_note


class PrintCaptureTests(unittest.TestCase):
    def test_capture_preserves_empty_lines_unicode_and_node_ids_with_bounds(self):
        capture = _PrintCapture(max_lines=3, max_chars=200)
        capture.feed("ordinary node log\n")
        capture.feed("node-1 casper_print: hello 🐍\n")
        cursor = capture.cursor
        capture.feed("node-2 casper_print: \n")
        capture.feed("node-1 casper_print: finally\n")
        self.assertEqual([(x.node_id, x.text) for x in capture.snapshot()], [(1, "hello 🐍"), (2, ""), (1, "finally")])
        self.assertEqual([x.text for x in capture.snapshot(cursor)], ["", "finally"])
        capture.feed("node-3 casper_print: newer\n")
        self.assertIn("1 earlier lines omitted", _print_note(capture.snapshot()))
        capture.feed("node-3 casper_print: " + "x" * 1000 + "\n")
        self.assertLessEqual(sum(len(x.text) for x in capture.snapshot()), 200)
        self.assertIn("truncated", capture.snapshot()[-1].text)

    def test_wait_for_print_filters_by_cursor_and_node_and_unblocks_on_close(self):
        capture = _PrintCapture()
        capture.feed("node-1 casper_print: old\n")
        cursor = capture.cursor
        thread = threading.Thread(target=lambda: capture.feed("node-2 casper_print: ready\n"))
        thread.start()
        self.assertEqual(capture.wait("ready", since=cursor, node_id=2).text, "ready")
        thread.join()
        with self.assertRaises(TimeoutError):
            capture.wait("ready", node_id=1, timeout=0.01)
        capture.close()
        with self.assertRaises(TimeoutError):
            capture.wait("missing", timeout=5)

    def test_real_stdio_client_collects_prints_without_polluting_json_rpc(self):
        server = '''import json, sys
for line in sys.stdin:
 r=json.loads(line)
 if "id" not in r: continue
 if r.get("method") == "tools/call":
  sys.stderr.write("node-2 casper_print: native 🐍\\nnode-1 casper_print: \\n")
  sys.stderr.flush()
 print(json.dumps({"id":r["id"],"result":{"structuredContent":{"ok":True}}}), flush=True)
'''
        with DevnetClient((sys.executable, "-u", "-c", server)) as client:
            client.call("echo", {})
            client._prints.wait("native", node_id=2)
        self.assertEqual([(x.node_id, x.text) for x in client.print_output], [(2, "native 🐍"), (1, "")])

    def test_test_errors_setup_teardown_and_subtest_failures_show_only_current_output(self):
        with tempfile.TemporaryDirectory() as directory:
            network = DevnetNetwork(diagnostics=directory)
            for phase in ("test", "setup", "teardown", "subtest"):
                network._prints.feed("node-1 casper_print: previous-test\n")
                class Example(LiveNetworkTest):
                    def setUp(self):
                        if phase == "setup":
                            self.network._prints.feed("node-1 casper_print: current-setup\n")
                            raise RuntimeError("setup failed")
                    def tearDown(self):
                        if phase == "teardown":
                            self.network._prints.feed("node-1 casper_print: current-teardown\n")
                            raise RuntimeError("teardown failed")
                    def test_failure(self):
                        self.network._prints.feed("node-2 casper_print: current-test\n")
                        if phase == "test": self.fail("failure")
                        if phase == "subtest":
                            with self.subTest(value=1): self.fail("subtest failure")
                Example.network = network
                output = io.StringIO()
                result = unittest.TextTestRunner(stream=output).run(Example("test_failure"))
                self.assertEqual(len(result.failures) + len(result.errors), 1)
                self.assertIn("Captured Casper prints", output.getvalue())
                self.assertIn("current-", output.getvalue())
                self.assertNotIn("previous-test", output.getvalue())
            network.stop()
