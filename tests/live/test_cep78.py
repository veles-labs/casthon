"""Deploy the inherited NFT example to an automatically managed Casper network."""

import json
from hashlib import blake2b

from casthon import CLBool, CLKey, CLString, CLU8, CLU64
from casthon.testing import LiveNetworkTest
from contracts.cep78 import address_key


class TestCep78(LiveNetworkTest):
    def call_nft(self, contract, entry, **options):
        # Ownership receipts and paginated lookup exceed the generic helper's
        # 100 CSPR contract-call budget, including calls through stored clients.
        return self.network.call(contract, entry, payment=400_000_000_000, **options)

    def test_mint_transfer_returns_burn_and_upgrade(self):
        # This class owns its network; genesis users already have deploy funds.
        alice = self.network.accounts["user-1"]
        bob = self.network.accounts["user-2"]
        wasm = self.build("contracts/my_nft.py")
        self.network.deploy(wasm, signer=alice, args={"total_token_supply": CLU64(2)}).assert_success()
        contract = self.network.named_keys(alice)["cep78_contract_hash_My NFT"]
        for owner in (alice, bob):
            self.call_nft(contract, "register_owner", signer=owner,
                              args={"token_owner": CLKey(owner.account_hash)}).assert_success()
        metadata = '{"name":"Live NFT","symbol":"MNFT","token_uri":"ipfs://live"}'
        self.call_nft(contract, "mint", signer=alice, args={
            "token_owner": CLKey(alice.account_hash), "token_meta_data": CLString(metadata)}).assert_success()
        self.call_nft(contract, "approve", signer=alice,
            args={"spender": CLKey(bob.account_hash), "token_id": CLU64(0)}).assert_success()
        self.call_nft(contract, "transfer", signer=bob, args={
            "source_key": CLKey(alice.account_hash), "target_key": CLKey(bob.account_hash), "token_id": CLU64(0)}).assert_success()
        keys = self.network.named_keys(contract)
        self.assertEqual(self.network.dictionary(keys["balances"], address_key(bob.account_hash)).value, 1)
        self.network.deploy(self.build("tests/fixtures/cep78_session.py"), signer=bob, install=False, args={
            "token": CLKey(contract), "token_owner": CLKey(bob.account_hash), "token_id": CLU64(0),
            "expected_balance": CLU64(1), "expected_metadata": CLString(json.dumps(json.loads(metadata), indent=2, ensure_ascii=False)),
        }).assert_success()
        self.call_nft(contract, "set_variables", signer=bob,
                          args={"allow_minting": CLBool(False)}).assert_failure("User error: 1")
        self.call_nft(contract, "burn", signer=bob, args={"token_id": CLU64(0)}).assert_success()
        self.call_nft(contract, "burn", signer=bob, args={"token_id": CLU64(0)}).assert_failure("User error: 42")
        self.network.deploy(wasm, signer=alice, args={"events_mode": CLU8(3), "total_token_supply": CLU64(1)}).assert_success()
        upgraded = self.network.named_keys(alice)["cep78_contract_hash_My NFT"]
        self.assertNotEqual(upgraded, contract)
        self.assertEqual(self.network.query(upgraded, path=["number_of_minted_tokens"]).value, 1)
        self.assertEqual(self.network.query(upgraded, path=["total_token_supply"]).value, 1)
        self.assertEqual(self.network.query(upgraded, path=["events_mode"]).value, 3)

    def test_hash_identifiers_duplicates_immutable_metadata_and_native_bytes(self):
        alice = self.network.accounts["user-1"]
        name = "Hash NFTs"
        self.network.deploy(self.build("contracts/my_nft.py"), signer=alice, args={
            "collection_name": CLString(name), "total_token_supply": CLU64(2),
            "identifier_mode": CLU8(1), "metadata_mutability": CLU8(0), "events_mode": CLU8(4),
        }).assert_success()
        contract = self.network.named_keys(alice)["cep78_contract_hash_" + name]
        self.call_nft(contract, "register_owner", signer=alice,
                      args={"token_owner": CLKey(alice.account_hash)}).assert_success()
        metadata = '{"name":"Hashed NFT","symbol":"HASH","token_uri":"ipfs://hashed"}'
        args = {"token_owner": CLKey(alice.account_hash), "token_meta_data": CLString(metadata)}
        minted = self.call_nft(contract, "mint", signer=alice, args=args).assert_success()
        keys = self.network.named_keys(contract)
        identifier = blake2b(metadata.encode(), digest_size=32).hexdigest()
        self.assertEqual(self.network.dictionary(keys["hash_by_index"], "0").value, identifier)
        self.assertEqual(self.network.dictionary(keys["token_owners"], identifier).value, alice.account_hash)
        writes = [(effect["key"], effect["kind"]["Write"]["Message"])
                  for effect in minted.execution["effects"]
                  if isinstance(effect["kind"], dict) and "Message" in effect["kind"].get("Write", {})]
        self.assertEqual(len(writes), 1)
        self.assertEqual(self.network.query(writes[0][0]).stored_value, {"Message": writes[0][1]})
        self.call_nft(contract, "mint", signer=alice, args=args).assert_failure("User error: 170")
        self.assertEqual(self.network.query(contract, path=["number_of_minted_tokens"]).value, 1)
        self.call_nft(contract, "set_token_metadata", signer=alice, args={
            "token_hash": CLString(identifier), "token_meta_data": CLString(metadata),
        }).assert_failure("User error: 104")
        self.call_nft(contract, "mint", signer=alice,
                      args={**args, "token_hash": CLString("custom-1")}).assert_success()
        self.assertEqual(self.network.dictionary(keys["index_by_hash"], "custom-1").value, 1)

    def test_stored_caller_ownership_and_package_operator_permissions(self):
        alice, bob = self.network.accounts["user-1"], self.network.accounts["user-2"]
        name = "Caller NFTs"
        self.network.deploy(self.build("contracts/my_nft.py"), signer=alice, args={
            "collection_name": CLString(name), "total_token_supply": CLU64(3),
            "minting_mode": CLU8(1), "package_operator_mode": CLBool(True),
        }).assert_success()
        contract = self.network.named_keys(alice)["cep78_contract_hash_" + name]
        self.network.deploy(self.build("tests/fixtures/cep78_client.py"), signer=alice,
                            args={"token": CLKey(contract)}).assert_success()
        client_keys = self.network.named_keys(alice)
        client, package = client_keys["nft_client"], client_keys["nft_client_package"]
        for owner in (alice.account_hash, bob.account_hash, client):
            self.call_nft(contract, "register_owner", signer=alice,
                          args={"token_owner": CLKey(owner)}).assert_success()
        metadata = '{"name":"Contract-owned NFT","symbol":"CALL","token_uri":"ipfs://caller"}'
        self.call_nft(client, "mint", signer=alice, args={
            "token_owner": CLKey(client), "token_meta_data": CLString(metadata),
        }).assert_success()
        keys = self.network.named_keys(contract)
        self.assertEqual(self.network.dictionary(keys["token_owners"], "0").value, client)
        self.assertEqual(self.network.dictionary(keys["token_issuers"], "0").value, client)
        self.call_nft(client, "approve", signer=alice,
                      args={"spender": CLKey(bob.account_hash), "token_id": CLU64(0)}).assert_success()
        self.call_nft(contract, "transfer", signer=bob, args={
            "source_key": CLKey(client), "target_key": CLKey(bob.account_hash), "token_id": CLU64(0),
        }).assert_success()
        self.call_nft(contract, "mint", signer=alice, args={
            "token_owner": CLKey(alice.account_hash), "token_meta_data": CLString(metadata),
        }).assert_success()
        self.call_nft(contract, "set_approval_for_all", signer=alice,
                      args={"approve_all": CLBool(True), "operator": CLKey(package)}).assert_success()
        args = {"source_key": CLKey(alice.account_hash), "target_key": CLKey(bob.account_hash), "token_id": CLU64(1)}
        self.call_nft(contract, "set_variables", signer=alice,
                      args={"package_operator_mode": CLBool(False)}).assert_success()
        self.call_nft(client, "transfer", signer=alice, args=args).assert_failure("User error: 6")
        self.assertEqual(self.network.dictionary(keys["token_owners"], "1").value, alice.account_hash)
        self.call_nft(contract, "set_variables", signer=alice,
                      args={"package_operator_mode": CLBool(True)}).assert_success()
        self.call_nft(client, "transfer", signer=alice, args=args).assert_success()
        self.assertEqual(self.network.dictionary(keys["balances"], address_key(bob.account_hash)).value, 2)
