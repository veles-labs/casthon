"""Inherited CEP-18 deployed to an automatically managed Casper 2.2.0 network."""

import json
from pathlib import Path

from casthon import CLKey, CLKeyList, CLU8, CLU256
from casthon.testing import LiveNetworkTest
from contracts.cep18 import address_key


class TestCep18(LiveNetworkTest):
    def test_enum_state_and_remote_enum_arguments_and_returns(self):
        alice = self.funded_account("enum-owner")
        wasm = self.build("tests/fixtures/enum_contract.py")
        self.network.deploy(wasm, signer=alice).assert_success()
        contract = self.network.named_keys(alice)["py_modes"]
        self.network.deploy(wasm, signer=alice, install=False,
                            args={"contract": CLKey(contract)}).assert_success()
        self.assertEqual(self.network.query(contract, path=["mode"]).value, 2)
        self.network.call(contract, "set", signer=alice,
                          args={"mode": CLU8(4)}).assert_failure("60006")
        self.assertEqual(self.network.query(contract, path=["mode"]).value, 2)

    def install(self, alice, **args):
        self.network.deploy(self.build("contracts/my_token.py"), signer=alice, args=args).assert_success()
        return self.network.named_keys(alice)["cep18_contract_hash_My Token"]

    def balance(self, token, owner):
        seed = self.network.named_keys(token)["balances"]
        return self.network.dictionary(seed, address_key(owner)).value

    def allowance(self, token, owner, spender):
        # Native query construction should not require an active mock host.
        from hashlib import blake2b
        item = blake2b(bytes(owner) + bytes(spender), digest_size=32).hexdigest()
        seed = self.network.named_keys(token)["allowances"]
        return self.network.dictionary(seed, item).value

    def assert_returns(self, alice, token, owner, spender, balance, supply, allowance):
        self.assertEqual(self.network.simulate(token, "balance_of", caller=alice,
            args={"address": CLKey(owner)}).value, balance)
        self.assertEqual(self.network.simulate(token, "total_supply", caller=alice).value, supply)
        self.assertEqual(self.network.simulate(token, "allowance", caller=alice,
            args={"owner": CLKey(owner), "spender": CLKey(spender)}).value, allowance)
        self.network.deploy(self.build("tests/fixtures/cep18_session.py"), signer=alice, install=False, args={
            "token": CLKey(token), "owner": CLKey(owner), "spender": CLKey(spender),
            "balance": CLU256(balance), "supply": CLU256(supply), "allowance": CLU256(allowance),
        }).assert_success()

    def test_defaults_transfers_allowance_returns_and_reverts(self):
        alice = self.funded_account("owner")
        bob = self.funded_account("spender")
        token = self.install(alice)
        self.assertEqual(self.network.query(token, path=["name"]).value, "My Token")
        fixture = json.loads(Path("reference/cep18/fixtures.json").read_text())
        actual = self.network.query(token).stored_value["Contract"]["entry_points"]
        kinds = {"0b": "Key", "07": "U256", "09": "Unit", "03": "U8", "0a": "String"}
        expected = [{"name": point["name"],
                     "args": [{"name": arg["name"], "cl_type": kinds[arg["cl_type"]]} for arg in point["args"]],
                     "ret": kinds[point["returns"]],
                     "access": "Public", "entry_point_type": "Called"} for point in fixture["abi"]]
        self.assertEqual(actual, expected)
        self.assertEqual(self.balance(token, alice.account_hash), 10**24)
        keys = self.network.named_keys(token)
        self.assertEqual(self.network.query(token, path=["__events_length"]).value, 1)
        self.network.call(token, "transfer", signer=alice,
                          args={"recipient": CLKey(bob.account_hash), "amount": CLU256(10)}).assert_success()
        self.network.call(token, "approve", signer=alice,
                          args={"spender": CLKey(bob.account_hash), "amount": CLU256(7)}).assert_success()
        self.network.call(token, "transfer_from", signer=bob, args={
            "owner": CLKey(alice.account_hash), "recipient": CLKey(bob.account_hash), "amount": CLU256(3),
        }).assert_success()
        self.assert_returns(alice, token, bob.account_hash, alice.account_hash, 13, 10**24, 0)
        self.assertEqual(self.allowance(token, alice.account_hash, bob.account_hash), 4)
        self.network.call(token, "transfer", signer=bob,
                          args={"recipient": CLKey(alice.account_hash), "amount": CLU256(14)}).assert_failure("User error: 60001")
        self.network.call(token, "init", signer=alice).assert_failure("User error: 60015")
        self.network.call(token, "init", signer=alice, args={
            "package_hash": CLU8(255), "contract_hash": CLU8(255),
        }).assert_failure("InvalidArgument|invalid argument")
        self.assertEqual(self.balance(token, bob.account_hash), 13)
        self.assertEqual(self.network.query(token, path=["__events_length"]).value, 4)
        # The CES schema is stored as its compound CLType, not flattened bytes.
        schema = self.network.query(token, path=["__events_schema"])
        expected = json.loads(Path("reference/cep18/fixtures.json").read_text())["ces_schemas"]
        # QueryResult.value intentionally only decodes the common codec subset.
        stored = schema.stored_value["CLValue"]
        size = int.from_bytes(bytes.fromhex(expected)[:4], "little")
        self.assertEqual(stored["bytes"], expected[8:8 + size * 2])
        self.assertEqual(stored["cl_type"], {"Map": {"key": "String", "value": {"List": {"Tuple2": ["String", "Any"]}}}})
        self.assertIn("__events_ces_version", keys)

    def test_security_mint_burn_native_event_modes_and_upgrade(self):
        alice = self.funded_account("admin")
        bob = self.funded_account("minter")
        token = self.install(alice, total_supply=CLU256(100))
        # Undeclared ABI arguments still use the dispatcher's typed decoding.
        for argument, error in (("admin_list", 60011), ("minter_list", 60012), ("none_list", 60013)):
            args = {name: CLKeyList([]) for name in ("admin_list", "minter_list", "none_list")}
            del args[argument]
            self.network.call(token, "change_security", signer=alice,
                              args=args).assert_failure(f"User error: {error}")
            args[argument] = CLU8(255)
            self.network.call(token, "change_security", signer=alice,
                              args=args).assert_failure("InvalidArgument|invalid argument")
        self.network.call(token, "change_security", signer=bob,
                          args={"admin_list": CLU8(255)}).assert_failure("InvalidArgument|invalid argument")
        self.network.call(token, "change_security", signer=bob).assert_failure("User error: 60010")
        self.network.call(token, "change_security", signer=alice, args={
            "admin_list": CLKeyList([bob.account_hash]), "minter_list": CLKeyList([bob.account_hash]),
            "none_list": CLKeyList([alice.account_hash]),
        }).assert_success()
        self.network.call(token, "mint", signer=bob,
                          args={"owner": CLKey(bob.account_hash), "amount": CLU256(7)}).assert_success()
        self.network.call(token, "burn", signer=bob,
                          args={"owner": CLKey(bob.account_hash), "amount": CLU256(2)}).assert_success()
        self.network.call(token, "burn", signer=alice,
                          args={"owner": CLKey(bob.account_hash), "amount": CLU256(1)}).assert_failure("User error: 60018")
        events_mode_key = self.network.named_keys(token)["events_mode"]
        for mode in (2, 3, 0, 1):
            receipt = self.network.call(token, "change_events_mode", signer=alice, args={"events_mode": CLU8(mode)}).assert_success()
            self.assertEqual(self.network.named_keys(token)["events_mode"], events_mode_key)
            self.assertEqual(self.network.query(events_mode_key).value, mode)
            if mode in (2, 3):
                writes = [(effect["key"], effect["kind"]["Write"]["Message"])
                          for effect in receipt.execution["effects"]
                          if isinstance(effect["kind"], dict) and "Message" in effect["kind"].get("Write", {})]
                self.assertEqual(len(writes), 1)
                key, checksum = writes[0]
                self.assertEqual(self.network.query(key).stored_value, {"Message": checksum})
        self.network.call(token, "change_security", signer=alice,
                          args={"admin_list": CLKeyList([]), "minter_list": CLKeyList([]),
                                "none_list": CLKeyList([bob.account_hash])}).assert_success()
        self.network.call(token, "mint", signer=bob,
                          args={"owner": CLKey(bob.account_hash), "amount": CLU256(1)}).assert_failure("User error: 60010")
        upgraded = self.install(alice, events_mode=CLU8(2))
        self.assertNotEqual(token, upgraded)
        self.assertEqual(self.network.named_keys(upgraded)["events_mode"], events_mode_key)
        self.assertEqual(self.network.query(events_mode_key).value, 2)
        self.assertEqual(self.balance(upgraded, bob.account_hash), 5)
        self.assertEqual(self.network.query(upgraded, path=["total_supply"]).value, 105)
        self.network.call(token, "name", signer=alice).assert_failure("disabled|Disabled|InvalidContractVersion")
        self.assert_returns(alice, upgraded, bob.account_hash, alice.account_hash, 5, 105, 0)

    def test_stored_contract_identity_and_typed_imported_entrypoints(self):
        alice = self.funded_account("client-owner")
        bob = self.funded_account("recipient")
        token = self.install(alice, total_supply=CLU256(100))
        self.network.deploy(self.build("tests/fixtures/cep18_client.py"), signer=alice,
                            args={"token": CLKey(token)}).assert_success()
        keys = self.network.named_keys(alice)
        package, client = keys["py_token_client_package"], keys["py_token_client"]
        self.network.call(token, "transfer", signer=alice,
                          args={"recipient": CLKey(package), "amount": CLU256(10)}).assert_success()
        self.network.call(client, "transfer", signer=alice,
                          args={"recipient": CLKey(bob.account_hash), "amount": CLU256(3)}).assert_success()
        self.network.call(client, "approve", signer=alice,
                          args={"spender": CLKey(bob.account_hash), "amount": CLU256(5)}).assert_success()
        self.assertEqual(self.balance(token, package), 7)
        self.assertEqual(self.balance(token, alice.account_hash), 90)
        self.assertEqual(self.allowance(token, package, bob.account_hash), 5)
        self.network.call(token, "approve", signer=alice,
                          args={"spender": CLKey(package), "amount": CLU256(8)}).assert_success()
        self.network.call(client, "transfer_from", signer=alice, args={
            "owner": CLKey(alice.account_hash), "recipient": CLKey(bob.account_hash), "amount": CLU256(4),
        }).assert_success()
        self.assert_returns(alice, token, package, bob.account_hash, 7, 100, 5)
        self.assertEqual(self.allowance(token, alice.account_hash, package), 4)

