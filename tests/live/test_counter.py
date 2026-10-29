"""Run explicitly with make test-live; native discovery never starts a network."""

import hashlib
from typing import Optional

from casthon import U32, CLU32, CLKey, CLString, CLValue, SerializedCLValue, URef
from casthon.testing import LiveNetworkTest


class TestCounter(LiveNetworkTest):
    def install_counter(self, alice, initial=0):
        wasm = self.build("contracts/counter.py")
        self.network.deploy(wasm, signer=alice, args={"initial": CLU32(initial)}).assert_success()
        return self.network.named_keys(alice)["py_counter"]

    def test_constructor_initial_value_survives_later_entrypoint_calls(self):
        alice = self.funded_account("constructor")
        contract = self.install_counter(alice, initial=7)
        self.assertEqual(self.network.query(contract, path=["count"]).value, 7)
        self.network.call(contract, "increment", signer=alice).assert_success()
        self.network.call(contract, "increment_by", signer=alice,
                          args={"amount": CLU32(2)}).assert_success()
        self.assertEqual(self.network.query(contract, path=["count"]).value, 10)
        self.assertEqual(self.network.query(contract, path=["owner"]).value, alice.account_hash)
        self.assertIs(self.network.query(contract, path=["paused"]).value, False)

    def test_simulated_getters_return_values_without_changing_chain_state(self):
        alice = self.funded_account("simulated-getter")
        contract = self.install_counter(alice, initial=7)
        result = self.network.simulate(contract, "get", caller=alice).assert_success()
        self.assertEqual(result.value, 7)
        self.assertGreater(result.consumed, 0)
        self.network.simulate(contract, "increment_by", caller=alice,
                              args={"amount": CLU32(3)}).assert_success()
        self.assertEqual(self.network.simulate(contract, "get", caller=alice).value, 7)
        self.assertEqual(self.network.query(contract, path=["count"]).value, 7)
        self.network.call(contract, "increment_by", signer=alice,
                          args={"amount": CLU32(5)}).assert_success()
        self.assertEqual(self.network.simulate(contract, "get", caller=alice).value, 12)

    def test_simulated_debug_prints_preserve_json_and_discard_state_changes(self):
        alice = self.funded_account("simulated-print")
        self.network.deploy(self.build("contracts/hello.py"), signer=alice).assert_success()
        contract = self.network.named_keys(alice)["hello"]
        result = self.network.simulate(contract, "greet", caller=alice,
            args={"name": CLString("Casper")}).assert_success()
        self.assertEqual(result.value, "Hello, Casper!")
        self.assertEqual(self.network.query(contract, path=["calls"]).value, 0)

    def test_inherited_ownership_pause_and_transfer(self):
        alice = self.funded_account("owner")
        bob = self.funded_account("next-owner")
        contract = self.install_counter(alice)
        self.assertEqual(self.network.query(contract, path=["owner"]).value, alice.account_hash)
        self.assertIs(self.network.query(contract, path=["paused"]).value, False)
        self.network.call(contract, "pause", signer=bob).assert_failure("User error: 100")
        self.network.call(contract, "pause", signer=alice).assert_success()
        self.assertIs(self.network.query(contract, path=["paused"]).value, True)
        session = self.build("contracts/counter_session.py")
        self.network.deploy(session, signer=bob, install=False, args={
            "contract": CLKey(contract), "amount": CLU32(5), "expected": CLU32(5),
        }).assert_failure("User error: 101")
        self.assertEqual(self.network.query(contract, path=["count"]).value, 0)
        self.network.call(contract, "unpause", signer=alice).assert_success()
        self.network.call(contract, "increment", signer=bob).assert_success()
        self.network.call(contract, "transfer_ownership", signer=alice,
                          args={"new_owner": CLKey(bob.account_hash)}).assert_success()
        self.assertEqual(self.network.query(contract, path=["owner"]).value, bob.account_hash)
        self.network.call(contract, "pause", signer=alice).assert_failure("User error: 100")
        self.network.call(contract, "pause", signer=bob).assert_success()
        self.assertEqual(self.network.query(contract, path=["count"]).value, 1)

    def test_python_session_calls_a_deployed_counter_using_imported_signatures(self):
        alice = self.funded_account("session-caller")
        contract = self.install_counter(alice)
        session = self.build("contracts/counter_session.py")

        def invoke(amount, expected):
            return self.network.deploy(session, signer=alice, install=False, args={
                "contract": CLKey(contract), "amount": CLU32(amount), "expected": CLU32(expected)})

        invoke(5, 5).assert_success()
        invoke(2, 7).assert_success()
        invoke(3, 99).assert_failure("User error: 1")
        self.assertEqual(self.network.query(contract, path=["count"]).value, 7)
        self.assertEqual(set(self.network.named_keys(alice)),
                         {"py_counter", "py_counter_package", "py_counter_access"})
        seed = self.network.named_keys(contract)["increments"]
        self.assertEqual(self.network.dictionary(seed, bytes(alice.account_hash)[1:].hex()).value, 7)

    def test_increment_dictionary_and_real_return_value(self):
        alice = self.funded_account("alice")
        contract = self.install_counter(alice)
        self.network.call(contract, "increment_by", args={"amount": CLU32(5)}, signer=alice).assert_success()
        self.assertEqual(self.network.query(contract, path=["count"]).value, 5)
        seed = self.network.named_keys(contract)["increments"]
        self.assertIsInstance(seed, URef)
        item = bytes(alice.account_hash)[1:].hex()
        self.assertEqual(self.network.dictionary(seed, item).value, 5)

        # Execution receipts do not contain casper_ret bytes. A real session
        # wrapper calls get(), checks its U32 return and fails if it is wrong.
        address = bytes(contract)[1:]
        raw_hash = SerializedCLValue((32).to_bytes(4, "little") + address + b"\x0f\x20\0\0\0")
        readback = self.build("contracts/counter.py").parent / "readback.wasm"
        self.network.deploy(readback, signer=alice, install=False,
                            args={"contract_hash": raw_hash, "expected": CLU32(5)}).assert_success()
        self.assertTrue(alice.secret_key.startswith(b"-----BEGIN"))
        self.assertEqual(bytes(alice.account_hash)[1:], hashlib.blake2b(alice.public_key.account_hash_preimage, digest_size=32).digest())

    def test_new_method_gets_fresh_account_and_contract_state(self):
        alice = self.funded_account("alice")
        contract = self.install_counter(alice)
        self.assertEqual(self.network.query(contract, path=["count"]).value, 0)
        bob = self.funded_account("bob")
        before = self.network.balance(bob)
        self.network.transfer(alice, bob, motes=5 * 10**9).assert_success()
        self.assertEqual(self.network.balance(bob), before + 5 * 10**9)

    def test_failed_calls_preserve_state_and_have_execution_receipts(self):
        alice = self.funded_account("alice")
        contract = self.install_counter(alice)
        self.network.call(contract, "increment_by", args={"amount": CLU32(0xffffffff)}, signer=alice).assert_success()
        self.network.call(contract, "increment", signer=alice).assert_failure("InvalidArgument|invalid argument")
        self.assertEqual(self.network.query(contract, path=["count"]).value, 0xffffffff)
        self.network.call(contract, "increment_by", signer=alice).assert_failure("MissingArgument|missing argument")

    def test_optional_entrypoints_execute_on_a_real_node(self):
        alice = self.funded_account("alice")
        self.network.deploy(self.build("contracts/typed_exports.py"), signer=alice).assert_success()
        contract = self.network.named_keys(alice)["py_typed_exports"]
        for value in (None, 0, 7):
            self.network.call(contract, "nullable", args={"amount": CLValue(Optional[U32], value)}, signer=alice).assert_success()
        self.network.call(contract, "nullable", signer=alice).assert_failure("MissingArgument|missing argument")
