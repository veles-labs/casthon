"""Typed getter simulation uses an isolated unsigned CLI call and never submits."""

import json
from pathlib import Path
import subprocess
import tempfile
import tomllib
import unittest
from unittest.mock import Mock, patch

from casthon import AccountHash, CLBool, CLKey, CLString, CLU32, CLU256, CLValue, Hash, U32
from casthon.crypto import Ed25519PublicKey
from casthon.testing import DevnetError, DevnetNetwork, TestAccount
from casthon.testing.simulation import _arguments
from casthon.testing.values import runtime_args


class SimulationTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.network = DevnetNetwork(diagnostics=self.directory.name, port_offset=1000)
        self.network._started = True
        self.network.rpc = Mock(return_value={"chainspec_name": "casper-local"})
        self.secret = Mock(side_effect=AssertionError("Simulation must not request a private key"))
        self.account = TestAccount("alice", "path", AccountHash(bytes([1]) * 32),
                                   Ed25519PublicKey(bytes([2]) * 32), self.secret)

    def response(self, value=None, *, error=None, code=None):
        raw = {"schemaVersion": 1, "success": error is None, "error": error,
               "returnValue": None if value is None else runtime_args({"return": value})[0][1],
               "gasConsumed": "12345", "blockHeight": 7, "stateRootHash": "ab" * 32}
        return subprocess.CompletedProcess([], (0 if error is None else 1) if code is None else code,
                                           json.dumps(raw), "backend diagnostics")

    def test_getters_decode_bytes_and_use_an_unsigned_isolated_network_profile(self):
        config_paths = []
        def run(command, **options):
            self.assertIn("--simulate", command)
            self.assertIn("--raw", command)
            self.assertNotIn("--from", command)
            self.assertEqual(command[command.index("--initiator") + 1], str(self.account.account_hash))
            self.assertEqual(command[command.index("call") + 1], "03" * 32)
            self.assertEqual(options["stdin"], subprocess.DEVNULL)
            config_path = Path(command[command.index("--config-path") + 1])
            config_paths.append(config_path)
            config = tomllib.loads(config_path.read_text())
            self.assertEqual(config["networks"]["live"]["rpc"], "http://127.0.0.1:12101/rpc")
            self.assertEqual(config["networks"]["live"]["chain_name"], "casper-local")
            self.assertEqual(Path(config["storage"]["root_path"]).parent, Path(self.directory.name).resolve())
            response = self.response(CLU32(7))
            data = json.loads(response.stdout)
            data["returnValue"]["parsed"] = 999  # Bytes remain authoritative.
            response.stdout = json.dumps(data)
            return response
        with patch("casthon.testing.simulation.shutil.which", return_value="/fake/casper-cli"), \
                patch("casthon.testing.simulation.subprocess.run", side_effect=run):
            result = self.network.simulate(Hash(bytes([3]) * 32), "get", caller=self.account).assert_success()
        self.assertEqual(result.value, 7)
        self.assertEqual((result.consumed, result.block_height, result.state_root_hash), (12345, 7, "ab" * 32))
        self.assertEqual(len(self.network.simulations), 1)
        self.assertEqual(self.network.transactions, [])
        self.assertTrue(all(not path.exists() for path in config_paths))
        self.secret.assert_not_called()
        self.network.rpc.assert_called_once_with("info_get_status")

    def test_boolean_large_integer_and_optional_returns_are_decoded(self):
        for value, expected in [(CLBool(False), False), (CLU256(1 << 200), 1 << 200),
                                (CLString("Hello, Casper!"), "Hello, Casper!"),
                                (CLValue(U32 | None, None), None), (None, None)]:
            with self.subTest(value=value), \
                    patch("casthon.testing.simulation.shutil.which", return_value="/fake/casper-cli"), \
                    patch("casthon.testing.simulation.subprocess.run", return_value=self.response(value)):
                self.assertEqual(self.network.simulate("hash-" + "03" * 32, "get", caller=self.account).value, expected)

    def test_execution_failures_are_results_and_value_access_asserts_success(self):
        with patch("casthon.testing.simulation.shutil.which", return_value="/fake/casper-cli"), \
                patch("casthon.testing.simulation.subprocess.run", return_value=self.response(error="User error: 42")):
            result = self.network.simulate(Hash(bytes(32)), "fail", caller=self.account)
        result.assert_failure("User error: 42")
        with self.assertRaisesRegex(AssertionError, "User error: 42"):
            result.value

    def test_invalid_output_and_transport_failures_do_not_become_successful_results(self):
        responses = [subprocess.CompletedProcess([], 1, "", "RPC unavailable"),
                     subprocess.CompletedProcess([], 0, "{}", ""), self.response(CLU32(3), code=1),
                     subprocess.CompletedProcess([], 0, "[]", "")]
        for response in responses:
            with self.subTest(response=response), \
                    patch("casthon.testing.simulation.shutil.which", return_value="/fake/casper-cli"), \
                    patch("casthon.testing.simulation.subprocess.run", return_value=response), \
                    self.assertRaises(DevnetError):
                self.network.simulate(Hash(bytes(32)), "get", caller=self.account)
        with patch("casthon.testing.simulation.shutil.which", return_value="/fake/casper-cli"), \
                patch("casthon.testing.simulation.subprocess.run", side_effect=subprocess.TimeoutExpired("casper-cli", 1)), \
                self.assertRaisesRegex(DevnetError, "Could not run"):
            self.network.simulate(Hash(bytes(32)), "get", caller=self.account)
        self.assertEqual(self.network.simulations, [])

    def test_argument_types_names_and_string_whitespace_are_preserved(self):
        self.assertEqual(_arguments({"amount": CLU256(1 << 200), "who": CLKey(self.account.account_hash),
            "a:b=c\\d": CLString("  hello=世界  "), "maybe": CLValue(U32 | None, None)}), [
            "--arg", f"amount:U256={1 << 200}", "--arg", f"who:Key={self.account.account_hash}",
            "--arg", "a\\:b\\=c\\\\d:String=  hello=世界  ", "--arg", "maybe:Option<U32>=0x00"])

    def test_missing_backend_fails_before_rpc_or_secret_access(self):
        with patch("casthon.testing.simulation.shutil.which", return_value=None), \
                self.assertRaisesRegex(DevnetError, "requires Veles Labs casper-cli"):
            self.network.simulate(Hash(bytes(32)), "get", caller=self.account)
        self.network.rpc.assert_not_called()
        self.secret.assert_not_called()
