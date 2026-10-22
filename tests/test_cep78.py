"""CEP-78 behavior, transaction boundaries and independent Rust wire fixtures."""

from copy import deepcopy
from hashlib import blake2b
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

from casthon import (
    ABIError, AccountHash, ApiError, CLBool, CLKey, CLKeyList, CLString,
    CLU8, CLU64, CLValue, ContractHash, DictionaryItemKeyExceedsLength,
    Key, Revert, U8, U64, URef, Bytesrepr, Json, JsonBytes,
)
from casthon.codec import cl_type, decode, encode
from casthon.caller import decode_caller_information
from casthon.events import event_schema, event_schemas
from casthon.testing import ContractHarness, MockHost, use_host
from casthon.testing.values import inspect_value, parse_key
from contracts import cep78_errors as errors, my_nft
from contracts.cep78 import Cep78, address_key, immediate_caller, operator_key
from contracts.cep78_metadata import validate_metadata, validate_schema
from contracts.cep78_modalities import EventsMode, NFTMetadataKind
from contracts.my_nft import MyNft

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from bundle import load_contract, lower
sys.path.insert(0, str(ROOT / "tests/fixtures"))
import cep78_client
import cep78_session

FIXTURES = json.loads((ROOT / "reference/cep78/fixtures.json").read_text())
METADATA = '{"name":"First NFT","symbol":"MNFT","token_uri":"ipfs://first"}'


class Cep78ReferenceTests(unittest.TestCase):
    def test_abi_matches_upstream_except_constructor_and_optional_configuration(self):
        expected = {point["name"]: point for point in FIXTURES["abi"]}
        for point in MyNft.entry_points():
            with self.subTest(entry=point.name):
                reference = expected.pop(point.name)
                self.assertEqual(cl_type(point.returns).hex(), reference["returns"])
                args = [{"name": name, "cl_type": cl_type(kind).hex()} for name, kind in point.args.items()]
                if point.name in ("init", "set_variables", "migrate"):
                    self.assertEqual(args, [])
                else:
                    self.assertEqual(args, reference["args"])
        self.assertEqual(expected, {})
        self.assertEqual(len(Cep78.entry_points()), 17)

    def test_all_event_schemas_binary_and_native_payloads_match_rust(self):
        self.assertEqual(event_schemas(Cep78.event_types()).to_bytes().hex(), FIXTURES["ces_schemas"])
        for fixture in FIXTURES["events"]:
            with self.subTest(event=fixture["name"], payload=fixture["json"]):
                fields = json.loads(fixture["json"])
                for name in ("recipient", "owner", "spender", "operator", "burner"):
                    if fields.get(name) is not None:
                        fields[name] = parse_key(fields[name])
                owner = next(event for event in Cep78.event_types() if event_schema(event).name == fixture["name"])
                event = owner(**fields)
                self.assertEqual((encode(str, "event_" + fixture["name"]) + Bytesrepr.to_message(event).value).hex(), fixture["ces"])
                self.assertEqual(Json.to_message(event).value, fixture["json"])
                self.assertEqual(Json.to_message(event).to_bytes().hex(), fixture["native_string"])
                self.assertEqual(JsonBytes.to_message(event).to_bytes().hex(), fixture["native_bytes"])

    def test_keys_metadata_and_receipt_values_match_rust(self):
        owner = AccountHash(bytes([0x11]) * 32)
        spender = ContractHash(bytes([0x22]) * 32)
        with use_host(MockHost()):
            self.assertEqual(address_key(owner), FIXTURES["dictionary"]["address"])
            self.assertEqual(address_key(spender), "22" * 32)
            self.assertEqual(operator_key(bytes(owner) + bytes(spender)), FIXTURES["dictionary"]["operator"])
        for fixture in FIXTURES["metadata"]:
            self.assertEqual(validate_metadata(NFTMetadataKind(fixture["kind"]), fixture["input"], '{"properties":{}}'), fixture["expected"])
        recipient = AccountHash(bytes([0x33]) * 32)
        values = (("register", tuple[str, URef[str]], ("My NFT", URef(bytes([0x44]) * 32))),
                  ("mint", tuple[str, Key, str], ("receipt", recipient, "42")),
                  ("receipts", list[tuple[str, Key]], [("receipt", recipient)]))
        for name, annotation, value in values:
            self.assertEqual(CLValue(annotation, value).to_bytes().hex(), FIXTURES["values"][name])
            self.assertEqual(decode(annotation, encode(annotation, value)), value)

    def test_tuple_and_uref_codecs_reject_wrong_shapes_and_truncated_values(self):
        for value in (["name", None], ("name",), ("name", 1, None)):
            with self.subTest(value=value), self.assertRaises(ABIError):
                encode(tuple[str, Key], value)
        for annotation in (tuple[()], tuple[str, ...], tuple[str, str, str, str]):
            with self.assertRaises(TypeError):
                cl_type(annotation)
        for annotation, data in ((tuple[U64, str], b"\0" * 8), (URef[str], b"\0" * 32),
                                 (URef[str], b"\0" * 32 + b"\xff")):
            with self.assertRaises(ABIError):
                decode(annotation, data)
        self.assertEqual(cl_type(URef[str]), b"\x0c")
        self.assertEqual(cl_type(URef), b"\x0b")

    def test_frozen_exports_select_only_the_concrete_root(self):
        declaration, _ = load_contract(ROOT / "contracts/my_nft.py")
        self.assertEqual(set(declaration["exports"]), {"call"} | {point.name for point in Cep78.entry_points()})
        declaration, _ = load_contract(ROOT / "tests/fixtures/cep78_client.py")
        self.assertEqual(set(declaration["exports"]), {"call", "mint", "approve", "transfer", "burn", "can_transfer"})
        self.assertNotIn("@entry_point", lower(ROOT / "contracts/cep78.py"))

    def test_caller_identity_is_a_version_with_a_separate_package(self):
        fixtures = json.loads((ROOT / "reference/cep18/fixtures.json").read_text())["callers"]
        for data, expected in zip(fixtures, ((0x00, 0x11), (0x01, 0x44), (0x11, 0x66))):
            info, = decode_caller_information(bytes.fromhex(data))
            with patch("casthon.contract_api.runtime.get_immediate_caller", return_value=info):
                caller, package = immediate_caller()
            self.assertEqual((bytes(caller)[0], bytes(caller)[-1]), expected)
            if expected[0] != 0:
                self.assertIsNotNone(package)


class Cep78Tests(unittest.TestCase):
    def setUp(self):
        self.alice, self.bob, self.carol = [AccountHash(bytes([n]) * 32) for n in (0x11, 0x22, 0x33)]
        self.host = MockHost(caller=self.alice, strict_arguments=True)
        self.session = ContractHarness(my_nft, host=self.host)

    def install(self, **args):
        self.session.invoke("call", args)
        name = args.get("collection_name", CLString("My NFT")).value
        contract = self.host.accounts[self.alice]["cep78_contract_hash_" + name]
        return ContractHarness(MyNft, host=self.host, contract=contract)

    def register(self, nft, *owners):
        for owner in owners or (self.alice,):
            result = nft.invoke("register_owner", {"token_owner": CLKey(owner)})
            self.assertEqual(result.value[0], "My NFT")

    def mint(self, nft, owner=None, metadata=METADATA, **args):
        return nft.invoke("mint", {"token_owner": CLKey(owner or self.alice), "token_meta_data": CLString(metadata), **args})

    def transfer(self, nft, source=None, target=None, caller=None, **args):
        return nft.invoke("transfer", {"source_key": CLKey(source or self.alice),
            "target_key": CLKey(target or self.bob), "token_id": CLU64(0), **args}, caller=caller)

    def balance(self, nft, owner):
        return nft.invoke("balance_of", {"token_owner": CLKey(owner)}).value

    def read(self, nft, field):
        key = self.host.contracts[nft.contract][field]
        return inspect_value(self.host.cells[key.address])[1]

    def client(self, nft):
        ContractHarness(cep78_client, host=self.host).invoke("call", {"token": CLKey(nft.contract)})
        keys = self.host.accounts[self.alice]
        return (ContractHarness(cep78_client.NftClient, host=self.host, contract=keys["nft_client"]),
                keys["nft_client_package"])

    def test_install_defaults_init_guard_and_state_isolation(self):
        nft = self.install()
        self.assertEqual(self.read(nft, "total_token_supply"), 1000)
        self.assertEqual(self.read(nft, "number_of_minted_tokens"), 0)
        self.assertEqual(self.read(nft, "__events_length"), 0)
        self.assertEqual(set(self.host.accounts[self.alice]), {prefix + "My NFT" for prefix in
            ("cep78_contract_package_", "cep78_contract_package_access_", "cep78_contract_hash_", "cep78_contract_version_")})
        with self.assertRaises(errors.ContractAlreadyInitialized):
            nft.invoke("init")
        with self.assertRaises(ABIError):
            nft.invoke("init", raw_args={"cep78_package_key": b"bad"})
        other = self.install(collection_name=CLString("Other"))
        self.assertNotEqual(nft.contract, other.contract)
        self.register(nft)
        self.mint(nft)
        self.assertEqual(self.balance(other, self.alice), 0)

    def test_constructor_rejects_conflicting_modalities_without_writes(self):
        invalid = (({"total_token_supply": CLU64(0)}, errors.CannotInstallWithZeroSupply),
            ({"total_token_supply": CLU64(1_000_001)}, errors.ExceededMaxTotalSupply),
            ({"identifier_mode": CLU8(1)}, errors.InvalidMetadataMutability),
            ({"ownership_mode": CLU8(1), "owner_reverse_lookup_mode": CLU8(2)}, errors.OwnerReverseLookupModeNotTransferable),
            ({"ownership_mode": CLU8(0)}, errors.InvalidReportingMode),
            ({"acl_whitelist": CLKeyList([self.alice])}, errors.InvalidMintingMode),
            ({"minting_mode": CLU8(2), "whitelist_mode": CLU8(1)}, errors.EmptyACLWhitelist))
        for args, error in invalid:
            with self.subTest(args=args), self.assertRaises(error):
                self.install(**args)
            self.assertEqual(self.host.cells, {})
        for argument, error in (("ownership_mode", errors.InvalidOwnershipMode),
                                ("events_mode", errors.InvalidEventsMode), ("holder_mode", errors.InvalidHolderMode)):
            with self.assertRaises(error):
                self.install(**{argument: CLU8(255)})

    def test_mint_owner_issuer_metadata_receipts_and_registration(self):
        nft = self.install()
        with self.assertRaises(errors.UnregisteredOwnerInMint):
            self.mint(nft)
        self.assertEqual(self.read(nft, "number_of_minted_tokens"), 0)
        self.register(nft)
        receipt, address, identifier = self.mint(nft).value
        self.assertEqual((receipt, identifier), ("cep78_My NFT_m_1000_p_0", "0"))
        self.assertEqual(nft.invoke("owner_of", {"token_id": CLU64(0)}).value, self.alice)
        self.assertEqual(json.loads(nft.invoke("metadata", {"token_id": CLU64(0)}).value), json.loads(METADATA))
        self.assertEqual(self.balance(nft, self.alice), 1)
        receipts = nft.invoke("updated_receipts").value
        self.assertEqual(receipts, [(receipt, address)])
        self.assertEqual(nft.invoke("register_owner", {"token_owner": CLKey(self.alice)}).value[0], "My NFT")
        with self.host.context(contract=nft.contract), use_host(self.host):
            state = MyNft.bind()
            self.assertTrue(state._page(0)[self.alice][0])
            self.assertEqual(state.token_issuers["0"], self.alice)

    def test_typed_session_reads_tuples_and_retains_the_returned_uref_schema(self):
        nft = self.install()
        self.register(nft)
        self.mint(nft)
        ContractHarness(cep78_session, host=self.host).invoke("call", {
            "token": CLKey(nft.contract), "token_owner": CLKey(self.alice),
            "token_id": CLU64(0), "expected_balance": CLU64(1),
            "expected_metadata": CLString(json.dumps(json.loads(METADATA), indent=2)),
        })

    def test_migration_requires_the_python_layout_marker(self):
        nft = self.install()
        del self.host.contracts[nft.contract]["cep78_python_layout"]
        with self.assertRaises(errors.InvalidMigrationFlag):
            nft.invoke("migrate")

    def test_mock_return_capabilities_allow_fresh_references_and_reject_forged_rights(self):
        from casthon.contract_api import storage
        from casthon.contracts import Contract, entry_point
        from casthon.testing.mock import MockAccessError

        with self.host.context(account=self.alice), use_host(self.host):
            secret = storage.new_uref(CLString("caller only"))

        class ReturnCapabilities(Contract):
            @entry_point
            def fresh(self) -> URef[str]:
                return storage.new_uref(CLString("returned"))

            @entry_point
            def forged(self) -> URef[str]:
                return secret

        contract = ContractHash(bytes([0xFA]) * 32)
        self.host.contract_modules[contract] = ReturnCapabilities
        self.host.entry_points[contract] = {point.name: point for point in ReturnCapabilities.entry_points()}
        with self.host.context(account=self.alice), use_host(self.host):
            self.assertEqual(contract.call(ReturnCapabilities.fresh).read(), "returned")
            with self.assertRaises(MockAccessError):
                contract.call(ReturnCapabilities.forged)

    def test_approval_transfer_self_transfer_and_new_owner_authority(self):
        nft = self.install()
        self.register(nft, self.alice, self.bob, self.carol)
        self.mint(nft)
        nft.invoke("approve", {"spender": CLKey(self.bob), "token_id": CLU64(0)})
        self.assertEqual(nft.invoke("get_approved", {"token_id": CLU64(0)}).value, self.bob)
        with self.assertRaises(errors.InvalidTokenOwner):
            self.transfer(nft, caller=self.carol)
        self.transfer(nft, target=self.carol, caller=self.bob)
        self.assertEqual((self.balance(nft, self.alice), self.balance(nft, self.carol)), (0, 1))
        self.assertIsNone(nft.invoke("get_approved", {"token_id": CLU64(0)}).value)
        with self.assertRaises(errors.InvalidTokenOwner):
            self.transfer(nft, source=self.carol, caller=self.bob)
        self.transfer(nft, source=self.carol, target=self.carol, caller=self.carol)
        self.assertEqual(self.balance(nft, self.carol), 1)
        with self.host.context(contract=nft.contract), use_host(self.host):
            page = MyNft.bind()._page(0)
            self.assertFalse(page[self.alice][0])
            self.assertTrue(page[self.carol][0])

    def test_operator_can_approve_revoke_and_transfer_but_spender_cannot_approve(self):
        nft = self.install()
        self.register(nft, self.alice, self.carol)
        self.mint(nft)
        args = {"spender": CLKey(self.carol), "token_id": CLU64(0)}
        with self.assertRaises(errors.InvalidAccount):
            nft.invoke("approve", {**args, "spender": CLKey(self.alice)})
        nft.invoke("approve", args)
        with self.assertRaises(errors.InvalidTokenOwner):
            nft.invoke("approve", {**args, "spender": CLKey(self.bob)}, caller=self.carol)
        nft.invoke("set_approval_for_all", {"approve_all": CLBool(True), "operator": CLKey(self.bob)})
        self.assertTrue(nft.invoke("is_approved_for_all", {"token_owner": CLKey(self.alice), "operator": CLKey(self.bob)}).value)
        nft.invoke("revoke", {"token_id": CLU64(0)}, caller=self.bob)
        self.assertIsNone(nft.invoke("get_approved", {"token_id": CLU64(0)}).value)
        nft.invoke("approve", args, caller=self.bob)
        nft.invoke("set_approval_for_all", {"approve_all": CLBool(False), "operator": CLKey(self.bob)})
        with self.assertRaises(errors.InvalidTokenOwner):
            nft.invoke("revoke", {"token_id": CLU64(0)}, caller=self.bob)
        self.transfer(nft, target=self.carol, caller=self.carol)

    def test_burn_preserves_owner_metadata_and_minted_supply(self):
        nft = self.install(total_token_supply=CLU64(1))
        self.register(nft)
        self.mint(nft)
        with self.assertRaises(errors.InvalidTokenOwner):
            nft.invoke("burn", {"token_id": CLU64(0)}, caller=self.bob)
        nft.invoke("burn", {"token_id": CLU64(0)})
        self.assertEqual(self.balance(nft, self.alice), 0)
        self.assertEqual(self.read(nft, "number_of_minted_tokens"), 1)
        self.assertEqual(nft.invoke("owner_of", {"token_id": CLU64(0)}).value, self.alice)
        self.assertTrue(nft.invoke("metadata", {"token_id": CLU64(0)}).value)
        for entry, args in (("burn", {}), ("get_approved", {}), ("approve", {"spender": CLKey(self.bob)}),
                            ("revoke", {}), ("transfer", {"source_key": CLKey(self.alice), "target_key": CLKey(self.bob)})):
            with self.subTest(entry=entry), self.assertRaises(errors.PreviouslyBurntToken):
                nft.invoke(entry, {"token_id": CLU64(0), **args})
        with self.assertRaises(errors.TokenSupplyDepleted):
            self.mint(nft)

    def test_operator_burning_requires_opt_in(self):
        nft = self.install()
        self.register(nft)
        self.mint(nft)
        nft.invoke("set_approval_for_all", {"approve_all": CLBool(True), "operator": CLKey(self.bob)})
        with self.assertRaises(errors.InvalidTokenOwner):
            nft.invoke("burn", {"token_id": CLU64(0)}, caller=self.bob)
        nft.invoke("set_variables", {"operator_burn_mode": CLBool(True)})
        nft.invoke("burn", {"token_id": CLU64(0)}, caller=self.bob)
        self.assertEqual(self.balance(nft, self.alice), 0)

    def test_minter_and_assigned_ownership_and_nonburnable_modes(self):
        for ownership in (0, 1):
            with self.subTest(ownership=ownership):
                nft = self.install(collection_name=CLString(str(ownership)), ownership_mode=CLU8(ownership),
                    owner_reverse_lookup_mode=CLU8(0), burn_mode=CLU8(1))
                self.assertIsNone(self.mint(nft, owner=self.bob).value)
                expected = self.alice if ownership == 0 else self.bob
                self.assertEqual(nft.invoke("owner_of", {"token_id": CLU64(0)}).value, expected)
                with self.assertRaises(errors.InvalidOwnershipMode):
                    self.transfer(nft)
                with self.assertRaises(errors.InvalidBurnMode):
                    nft.invoke("burn", {"token_id": CLU64(0)}, caller=expected)

    def test_mint_permissions_pause_acl_replacement_and_locked_list(self):
        nft = self.install(minting_mode=CLU8(2), acl_whitelist=CLKeyList([self.bob]))
        self.register(nft)
        with self.assertRaises(errors.InvalidMinter):
            self.mint(nft)
        args = {"token_owner": CLKey(self.alice), "token_meta_data": CLString(METADATA)}
        nft.invoke("mint", args, caller=self.bob)
        with self.assertRaises(errors.InvalidAccount):
            nft.invoke("set_variables", {"allow_minting": CLBool(False)}, caller=self.bob)
        nft.invoke("set_variables", {"allow_minting": CLBool(False)})
        with self.assertRaises(errors.MintingIsPaused):
            nft.invoke("mint", args, caller=self.bob)
        nft.invoke("set_variables", {"allow_minting": CLBool(True), "acl_whitelist": CLKeyList([self.carol])})
        with self.assertRaises(errors.InvalidMinter):
            nft.invoke("mint", args, caller=self.bob)
        nft.invoke("set_variables", {"acl_whitelist": CLKeyList([])})
        nft.invoke("mint", args, caller=self.carol)
        locked = self.install(collection_name=CLString("Locked"), minting_mode=CLU8(2),
                              whitelist_mode=CLU8(1), acl_whitelist=CLKeyList([self.alice]))
        with self.assertRaises(errors.InvalidWhitelistMode):
            locked.invoke("set_variables", {"allow_minting": CLBool(False), "acl_whitelist": CLKeyList([self.bob])})
        self.assertTrue(self.read(locked, "allow_minting"))

    def test_hash_ids_custom_ids_duplicate_rejection_and_dictionary_limit(self):
        nft = self.install(identifier_mode=CLU8(1), metadata_mutability=CLU8(0))
        self.register(nft)
        expected = blake2b(METADATA.encode(), digest_size=32).hexdigest()
        self.assertEqual(self.mint(nft).value[2], expected)
        with self.assertRaises(errors.DuplicateIdentifier):
            self.mint(nft)
        self.assertEqual(self.mint(nft, token_hash=CLString("custom-1")).value[2], "custom-1")
        self.assertEqual(nft.invoke("owner_of", {"token_hash": CLString(expected)}).value, self.alice)
        with self.assertRaises(errors.MissingTokenID):
            nft.invoke("owner_of", {"token_id": CLU64(0)})
        with self.assertRaises(DictionaryItemKeyExceedsLength):
            self.mint(nft, token_hash=CLString("é" * 33))
        self.assertEqual(self.read(nft, "number_of_minted_tokens"), 2)

    def test_metadata_update_requires_owner_and_required_schemas_are_atomic(self):
        nft = self.install(additional_required_metadata=CLValue(list[U8], [0]), optional_metadata=CLValue(list[U8], [3]),
                          json_schema=CLString('{"properties":{"extra":{"name":"extra","description":"","required":true}}}'))
        self.register(nft)
        with self.assertRaises(errors.FailedToParseCep99Metadata):
            self.mint(nft)
        text = METADATA[:-1] + ',"checksum":"abc"}'
        self.mint(nft, metadata=text)
        self.assertIn('"checksum"', nft.invoke("metadata", {"token_id": CLU64(0)}).value)
        args = {"token_id": CLU64(0), "token_meta_data": CLString(text.replace("First NFT", "New NFT"))}
        with self.assertRaises(errors.InvalidTokenOwner):
            nft.invoke("set_token_metadata", args, caller=self.bob)
        nft.invoke("set_token_metadata", args)
        before = deepcopy(self.host.dictionaries)
        with self.assertRaises(errors.InvalidCEP99Metadata):
            nft.invoke("set_token_metadata", {**args, "token_meta_data": CLString(text.replace('"abc"', '""'))})
        self.assertEqual(self.host.dictionaries, before)

    def test_custom_and_raw_metadata_and_json_validation(self):
        schema = '{"properties":{"a":{"name":"A","description":"required","required":true}}}'
        nft = self.install(nft_metadata_kind=CLU8(3), json_schema=CLString(schema))
        self.register(nft)
        for text, error in (("[]", errors.FailedToParseCustomMetadata), ('{"a":4}', errors.FailedToParseCustomMetadata),
                            ('{"b":"x"}', errors.InvalidCustomMetadata)):
            with self.assertRaises(error):
                self.mint(nft, metadata=text)
        self.mint(nft, metadata='{"a":"", "b":"extra"}')
        raw = self.install(collection_name=CLString("Raw"), nft_metadata_kind=CLU8(2), owner_reverse_lookup_mode=CLU8(0))
        self.mint(raw, metadata="not JSON")
        self.assertEqual(raw.invoke("metadata", {"token_id": CLU64(0)}).value, "not JSON")
        for text in ('{}', '{"properties":[]}', '{"properties":{"a":{"name":"A"}}}'):
            with self.assertRaises(errors.InvalidJsonSchema):
                validate_schema(text)
        for text in ('{"a":"\\ud800"}', '{"a":"x", "a":"y"}', '{"a":true}', '{"a":"x",}', '{"a":"x"} trailing'):
            with self.assertRaises(errors.FailedToParseCustomMetadata):
                validate_metadata(NFTMetadataKind.CUSTOM_VALIDATED, text, schema)
        self.assertIn("🦀", validate_metadata(NFTMetadataKind.CUSTOM_VALIDATED, '{"a":"\\ud83e\\udd80"}', schema))

    def test_no_lookup_and_transfers_only_return_unit_and_track_transfers(self):
        nft = self.install(owner_reverse_lookup_mode=CLU8(0))
        self.assertIsNone(nft.invoke("register_owner", {"token_owner": CLKey(self.alice)}).value)
        self.assertIsNone(self.mint(nft).value)
        self.assertIsNone(self.transfer(nft).value)
        self.assertIsNone(nft.invoke("updated_receipts").value)
        tracked = self.install(collection_name=CLString("Transfers"), owner_reverse_lookup_mode=CLU8(2))
        self.mint(tracked)
        with self.assertRaises(errors.UnregisteredOwnerInTransfer):
            self.transfer(tracked)
        for owner in (self.alice, self.bob):
            tracked.invoke("register_owner", {"token_owner": CLKey(owner)})
        self.assertEqual(self.transfer(tracked).value[0], "cep78_Transfers_m_1000_p_0")
        with self.host.context(contract=tracked.contract), use_host(self.host):
            self.assertFalse(MyNft.bind()._page(0)[self.alice][0])
            self.assertTrue(MyNft.bind()._page(0)[self.bob][0])

    def test_pagination_crosses_page_boundary_and_receipt_address_is_readable(self):
        nft = self.install(total_token_supply=CLU64(1001))
        self.register(nft)
        # Set up the count of a collection whose earlier mints are outside this
        # test, then exercise the two sides of the actual page boundary.
        with self.host.context(contract=nft.contract), use_host(self.host):
            MyNft.bind().number_of_minted_tokens.write(999)
        self.assertEqual(self.mint(nft).value[0], "cep78_My NFT_m_1000_p_0")
        self.assertEqual(self.mint(nft).value[0], "cep78_My NFT_m_1000_p_1")
        receipts = nft.invoke("updated_receipts").value
        self.assertEqual(len(receipts), 2)
        with self.host.context(contract=nft.contract), use_host(self.host):
            from casthon.contract_api import storage
            bits = storage.dictionary_read(receipts[1][1], list[bool])
            self.assertEqual((len(bits), bits[0], sum(bits)), (1000, True, 1))

    def test_stored_callers_own_by_version_and_can_act_as_package_operator(self):
        nft = self.install(minting_mode=CLU8(1), package_operator_mode=CLBool(True))
        client, package = self.client(nft)
        self.register(nft, self.alice, self.bob, client.contract)
        client.invoke("mint", {"token_owner": CLKey(client.contract), "token_meta_data": CLString(METADATA)})
        self.assertEqual(self.balance(nft, client.contract), 1)
        self.assertEqual(self.balance(nft, package), 0)
        client.invoke("approve", {"spender": CLKey(self.bob), "token_id": CLU64(0)})
        self.transfer(nft, source=client.contract, caller=self.bob)
        self.mint(nft)
        nft.invoke("set_approval_for_all", {"approve_all": CLBool(True), "operator": CLKey(package)})
        client.invoke("transfer", {"source_key": CLKey(self.alice), "target_key": CLKey(self.bob), "token_id": CLU64(1)})
        self.assertEqual(self.balance(nft, self.bob), 2)

    def test_acl_package_mode_uses_the_callers_package_and_holder_gate(self):
        nft = self.install(minting_mode=CLU8(2), acl_package_mode=CLBool(True), holder_mode=CLU8(1))
        client, package = self.client(nft)
        self.register(nft, client.contract)
        nft.invoke("set_variables", {"acl_whitelist": CLKeyList([package])})
        with self.assertRaises(errors.InvalidHolderMode):
            self.mint(nft)
        client.invoke("mint", {"token_owner": CLKey(client.contract), "token_meta_data": CLString(METADATA)})
        self.assertEqual(self.balance(nft, client.contract), 1)
        nft.invoke("set_variables", {"acl_package_mode": CLBool(False)})
        with self.assertRaises(Revert) as error:
            client.invoke("mint", {"token_owner": CLKey(client.contract), "token_meta_data": CLString(METADATA)})
        self.assertEqual(error.exception.code, 65536 + 81)

    def test_transfer_filter_receives_target_and_denial_rolls_back_every_contract(self):
        nft = self.install()
        client, _ = self.client(nft)
        self.register(nft, self.alice, self.bob)
        self.mint(nft)
        with self.host.context(contract=nft.contract), use_host(self.host):
            MyNft.bind().transfer_filter_contract.write(client.contract)
        with self.host.context(contract=client.contract), use_host(self.host):
            cep78_client.NftClient.bind().allowed.write(False)
        before = deepcopy(self.host.cells), deepcopy(self.host.dictionaries)
        with self.assertRaises(errors.TransferFilterContractDenied):
            self.transfer(nft)
        self.assertEqual((self.host.cells, self.host.dictionaries), before)
        with self.host.context(contract=client.contract), use_host(self.host):
            cep78_client.NftClient.bind().allowed.write(True)
        self.transfer(nft)
        self.assertEqual((self.read(client, "last_source"), self.read(client, "last_target")), (self.alice, self.bob))

    def test_events_modes_cep47_layout_and_native_failure_rollback(self):
        for mode in (0, 1, 2, 3, 4):
            nft = self.install(collection_name=CLString(str(mode)), owner_reverse_lookup_mode=CLU8(0), events_mode=CLU8(mode))
            self.mint(nft)
            if mode == 1:
                seed = self.host.contracts[nft.contract]["events"]
                self.assertEqual(inspect_value(self.host.dictionaries[seed.address]["len"])[1], 1)
                record = inspect_value(self.host.dictionaries[seed.address]["0"])[1]
                self.assertEqual(record["event_type"], "Mint")
                self.assertEqual(record["recipient"], str(self.alice))
                self.assertNotIn("data", record)
            elif mode in (3, 4):
                self.assertEqual(self.host.messages[-1][2][0], mode - 3)
                self.assertEqual(json.loads(self.host.messages[-1][2][5:].decode())["data"], METADATA)
        nft = self.install(events_mode=CLU8(3))
        self.register(nft)
        before = deepcopy(self.host.cells), deepcopy(self.host.dictionaries)
        self.host.fail_next("emit_message", ApiError(17))
        with self.assertRaises(ApiError):
            self.mint(nft)
        self.assertEqual((self.host.cells, self.host.dictionaries), before)

    def test_upgrades_preserve_metadata_pages_approvals_and_ces_history(self):
        nft = self.install(total_token_supply=CLU64(10))
        self.register(nft)
        self.mint(nft)
        nft.invoke("approve", {"spender": CLKey(self.bob), "token_id": CLU64(0)})
        original_keys = dict(self.host.contracts[nft.contract])
        upgraded = self.install(total_token_supply=CLU64(5), events_mode=CLU8(3))
        self.assertIn(nft.contract, self.host.disabled)
        self.assertEqual(self.balance(upgraded, self.alice), 1)
        self.assertEqual(self.read(upgraded, "total_token_supply"), 5)
        self.assertEqual(upgraded.invoke("get_approved", {"token_id": CLU64(0)}).value, self.bob)
        self.assertEqual(self.host.contracts[upgraded.contract], original_keys)
        upgraded = self.install(events_mode=CLU8(2))
        self.assertEqual(self.read(upgraded, "__events_length"), 3)
        for cap, error in ((0, errors.CannotUpgradeWithZeroSupply), (6, errors.CannotUpgradeToMoreSupply)):
            with self.assertRaises(Revert) as raised:
                self.install(total_token_supply=CLU64(cap))
            self.assertEqual(raised.exception.code, error().code)
        self.assertNotIn(upgraded.contract, self.host.disabled)
        with self.assertRaises(errors.InvalidAccount):
            upgraded.invoke("migrate", {"events_mode": CLU8(0)}, caller=self.bob)
