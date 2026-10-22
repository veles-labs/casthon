"""Network/client behavior is tested without starting nodes in the native suite."""

import io
import json
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

from cspr import AccountHash, Hash, CLU32, CLValue, U32
from cspr.crypto import Ed25519PublicKey
from cspr.testing import DevnetClient, DevnetError, DevnetNetwork, LiveNetworkTest, build_contract
from cspr.testing.devnet import _PortLease


STDIO_SERVER = '''import json, sys
for line in sys.stdin:
    request = json.loads(line)
    if "id" not in request:
        continue
    identifier = request["id"]
    if request["method"] == "initialize":
        result = {"protocolVersion": "2024-11-05"}
    else:
        name = request["params"]["name"]
        if name == "timeout":
            continue
        if name == "crash":
            sys.exit(2)
        if name == "bad":
            result = {"isError": True, "content": [{"type":"text", "text":"rejected"}]}
        else:
            result = {"structuredContent": request["params"]["arguments"]}
    print(json.dumps({"jsonrpc":"2.0", "method":"notifications/progress", "params":{}}), flush=True)
    print(json.dumps({"jsonrpc":"2.0", "id":identifier, "result":result}), flush=True)
'''


class TransportTests(unittest.TestCase):
    def test_stdio_notifications_errors_timeouts_and_shutdown(self):
        with DevnetClient((sys.executable, "-u", "-c", STDIO_SERVER)) as client:
            self.assertEqual(client.call("echo", {"value": 7}), {"value": 7})
            with self.assertRaises(DevnetError):
                client.call("bad", {})
            with self.assertRaises(TimeoutError):
                client.call("timeout", {}, timeout=0.01)
            self.assertEqual(client.call("echo", {"after": True}), {"after": True})
        self.assertIsNotNone(client.process.poll())
        client.close()

    def test_child_exit_unblocks_pending_requests(self):
        with DevnetClient((sys.executable, "-u", "-c", STDIO_SERVER)) as client:
            with self.assertRaises(DevnetError):
                client.call("crash", {}, timeout=1)


class FakeDevnet:
    def __init__(self):
        self.calls = []
        self.failures = {}
        self.existing = []
        self.error = None

    def initialize(self):
        pass

    def close(self):
        pass

    def call(self, name, arguments, *, timeout=60):
        self.calls.append((name, arguments))
        if name in self.failures:
            raise self.failures[name]
        if name == "list_networks":
            return {"networks": self.existing}
        if name == "spawn_network":
            return {"already_running": False}
        if name == "wait_network_ready":
            return {"ready": True}
        if name == "list_derived_accounts":
            return [{"alias": "user-1", "path": "m/44'/506'/0'/0/1", "account_hash": "11" * 32,
                     "public_key": "01" + "22" * 32}]
        if name.startswith("make_transaction_"):
            return {"transaction": {"Version1": {}}}
        if name in ("send_transaction_signed", "transfer_tokens"):
            return {"transaction_hash": "transaction-1"}
        if name == "wait_transaction":
            return {"execution_info": {"block_hash": "block-1", "execution_result": {"Version2": {
                "error_message": self.error, "consumed": "7", "cost": "12", "effects": []}}}}
        if name == "rpc_query_global_state":
            if arguments["path"]:
                return {"stored_value": {"CLValue": {"cl_type": "U32", "bytes": "07000000"}}}
            return {"stored_value": {"Account": {"named_keys": [{"name": "token", "key": "hash-" + "33" * 32}]}}}
        if name == "rpc_query_balance":
            return {"available_balance": "10000000000000000"}
        if name == "rpc_query":
            if arguments["method"] == "state_get_dictionary_item":
                return {"result": {"stored_value": {"CLValue": {"cl_type": "U32", "bytes": "07000000"}}}}
            return {"result": {"state_root_hash": "root-1"}}
        if name in ("get_node_logs", "despawn_network"):
            return {}
        raise AssertionError(name)


class NetworkTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.client = FakeDevnet()
        self.network = DevnetNetwork(client=self.client, diagnostics=self.directory.name)
        self.addCleanup(self.network.stop)

    def test_typed_transactions_wait_for_execution_and_state_queries_decode_bytes(self):
        self.network.start()
        alice = self.network.accounts["user-1"]
        receipt = self.network.call(Hash(bytes(32)), "increment_by", args={"amount": CLU32(5)}, signer=alice)
        receipt.assert_success()
        self.assertEqual((receipt.consumed, receipt.cost, receipt.block_hash), (7, 12, "block-1"))
        arguments = next(args for name, args in self.client.calls if name == "make_transaction_contract_call")
        self.assertEqual(arguments["session_args"], [["amount", {"cl_type": "U32", "bytes": "05000000", "parsed": None}]])
        self.assertEqual(self.network.query(Hash(bytes(32)), path=["count"]).value, 7)
        self.assertEqual(str(self.network.named_keys(alice)["token"]), "hash-" + "33" * 32)
        self.assertEqual(self.network.balance(alice), 10**16)
        self.network.stop()
        report = json.loads((Path(self.directory.name) / "report.json").read_text())
        self.assertTrue(report["networkStopped"])
        self.assertEqual(len(report["transactions"]), 1)
        self.assertEqual(sum(name == "despawn_network" for name, args in self.client.calls), 1)
        stopped = next(args for name, args in self.client.calls if name == "despawn_network")
        self.assertFalse(stopped["purge"])

    def test_failed_execution_is_a_receipt_but_submission_failure_is_an_exception(self):
        self.network.start()
        alice = self.network.accounts["user-1"]
        self.client.error = "User error: 42"
        receipt = self.network.call(Hash(bytes(32)), "fail", signer=alice)
        receipt.assert_failure("User error: 42")
        with self.assertRaises(AssertionError):
            receipt.assert_success()
        self.client.failures["send_transaction_signed"] = DevnetError("admission rejected")
        with self.assertRaisesRegex(DevnetError, "admission rejected"):
            self.network.call(Hash(bytes(32)), "fail", signer=alice)

    def test_partial_startup_failure_still_attempts_cleanup_and_releases_ports(self):
        self.client.failures["spawn_network"] = DevnetError("startup failed")
        with self.assertRaisesRegex(DevnetError, "startup failed"):
            self.network.start()
        self.assertTrue(any(name == "despawn_network" for name, args in self.client.calls))
        self.assertEqual(self.network._lease.files, [])

    def test_existing_and_attached_networks_are_never_despawned(self):
        self.client.existing = [{"network_name": self.network.name}]
        with self.assertRaisesRegex(DevnetError, "existing network"):
            self.network.start()
        self.assertFalse(any(name in ("spawn_network", "despawn_network") for name, args in self.client.calls))
        attached = DevnetNetwork(name="existing", client=self.client, owned=False, diagnostics=self.directory.name)
        with attached:
            self.assertIn("user-1", attached.accounts)
        self.assertFalse(any(name == "despawn_network" for name, args in self.client.calls))

    def test_scoped_accounts_are_stable_order_independent_and_secrets_are_lazy(self):
        self.network.start()
        def derive(path, material):
            if material == "public-key":
                return "01" + "22" * 32
            if material == "account-hash":
                import hashlib
                return hashlib.sha256(path.encode()).hexdigest()
            return "PRIVATE TEST KEY"
        with patch.object(self.network, "_derive", side_effect=derive) as derived:
            alice = self.network.account("alice", scope="test_one")
            self.network.account("bob", scope="test_one")
            self.assertIs(self.network.account("alice", scope="test_one"), alice)
            self.assertNotEqual(self.network.account("alice", scope="test_two").path, alice.path)
            self.assertFalse(any(call.args[1] == "secret-key" for call in derived.call_args_list))
            self.assertEqual(alice.secret_key, b"PRIVATE TEST KEY")
            self.assertNotIn("PRIVATE TEST KEY", repr(alice))
            self.network.funded_account("alice", scope="test_one")
            self.network.funded_account("alice", scope="test_one")
            self.assertEqual(sum(name == "transfer_tokens" for name, args in self.client.calls), 1)

    def test_overlapping_port_offsets_cannot_be_leased_by_parallel_tests(self):
        with tempfile.TemporaryDirectory() as directory:
            first = _PortLease(None, 1, directory=Path(directory))
            try:
                with self.assertRaises(DevnetError):
                    _PortLease(first.offset + 1, 1, directory=Path(directory))
            finally:
                first.close()
            second = _PortLease(first.offset + 1, 1, directory=Path(directory))
            second.close()


class LiveLifecycleTests(unittest.TestCase):
    def test_class_lifetime_and_cleanup_even_if_subclass_setup_fails(self):
        events = []
        class Network:
            print_cursor = 0
            def __init__(self, **kwargs):
                events.append("new")
            def start(self):
                events.append("start")
            def stop(self):
                events.append("stop")
            def note_prints(self, error, *, since=0):
                pass
        class Example(LiveNetworkTest):
            def test_one(self):
                events.append("one")
            def test_two(self):
                events.append("two")
        class Broken(LiveNetworkTest):
            @classmethod
            def setUpClass(cls):
                super().setUpClass()
                raise RuntimeError("subclass setup failed")
            def test_unused(self):
                events.append("unreachable")
        with patch.dict("os.environ", {"CSPR_LIVE_TESTS": "1"}), patch("cspr.testing.live.DevnetNetwork", Network):
            result = unittest.TestResult()
            unittest.defaultTestLoader.loadTestsFromTestCase(Example).run(result)
            self.assertTrue(result.wasSuccessful())
            unittest.defaultTestLoader.loadTestsFromTestCase(Broken).run(result)
            self.assertEqual(len(result.errors), 1)
        self.assertEqual(events, ["new", "start", "one", "two", "stop", "new", "start", "stop"])

    def test_live_tests_are_opt_in(self):
        with patch.dict("os.environ", {}, clear=True):
            with self.assertRaises(unittest.SkipTest):
                LiveNetworkTest.setUpClass()

    def test_live_binary_can_be_selected_for_one_run(self):
        class Example(LiveNetworkTest):
            binary = "default-launcher"

        with patch.dict("os.environ", {"CSPR_LIVE_TESTS": "1", "CSPR_DEVNET_BIN": "/tmp/local-casper-devnet"}), \
                patch("cspr.testing.live.DevnetNetwork") as factory:
            Example.setUpClass()
            try:
                self.assertEqual(factory.call_args.kwargs["binary"], "/tmp/local-casper-devnet")
                factory.return_value.start.assert_called_once()
            finally:
                Example.doClassCleanups()
            factory.return_value.stop.assert_called_once()


class BuildCacheTests(unittest.TestCase):
    def test_cache_tracks_helpers_and_validates_artifacts(self):
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            (project / "contracts").mkdir()
            source = project / "contracts/token.py"
            source.write_text("def call(): pass\n")
            helper = project / "contracts/shared.py"
            helper.write_text("VALUE = 1\n")
            command = project / "builder.py"
            command.write_text('''import hashlib, json, pathlib, sys
output = pathlib.Path(sys.argv[sys.argv.index("--output-dir") + 1])
profile = sys.argv[sys.argv.index("--profile") + 1]
if profile == "release": output = output / "release"
output.mkdir(parents=True, exist_ok=True)
artifact = output / "token.wasm"
artifact.write_bytes(b"\\0asm")
(output / "token-build-report.json").write_text(json.dumps({"sha256":hashlib.sha256(artifact.read_bytes()).hexdigest()}))
count = pathlib.Path("count")
count.write_text(str(int(count.read_text()) + 1) if count.exists() else "1")
''')
            kwargs = {"project_root": project, "command": (sys.executable, str(command))}
            first = build_contract(source, **kwargs)
            self.assertEqual(build_contract(source, **kwargs), first)
            self.assertEqual((project / "count").read_text(), "1")
            first.write_bytes(b"corrupted")
            build_contract(source, **kwargs)
            self.assertEqual((project / "count").read_text(), "2")
            helper.write_text("VALUE = 2\n")
            self.assertNotEqual(build_contract(source, **kwargs), first)
            self.assertEqual((project / "count").read_text(), "3")
            release = build_contract(source, profile="release", **kwargs)
            self.assertEqual(release.parent.name, "release")
            self.assertNotEqual(release, first)
            self.assertTrue(first.is_file())
            self.assertEqual(build_contract(source, profile="release", **kwargs), release)
            build_contract(source, profile="debug", **kwargs)
            self.assertEqual((project / "count").read_text(), "4")
            with self.assertRaisesRegex(ValueError, "Unknown build profile"):
                build_contract(source, profile="unknown", **kwargs)


if __name__ == "__main__":
    unittest.main()
