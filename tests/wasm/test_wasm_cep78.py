"""Exercise the NFT class in plain and Casper 500-slot metered MicroPython."""

from copy import deepcopy
from hashlib import blake2b
import json
import wasmtime

from test_wasm_basic import WasmTestCase
from wasm_harness import Harness, ROOT, build_file, envelope, payload, unwrap

FIXTURES = json.loads((ROOT / "reference/cep78/fixtures.json").read_text())
METADATA = '{"name":"First NFT","symbol":"MNFT","token_uri":"ipfs://first"}'


def key(byte):
    return b"\0" + bytes([byte]) * 32


def u64(value):
    return value.to_bytes(8, "little")


def cl_u64(value):
    return (8).to_bytes(4, "little") + u64(value) + b"\x05"


def option_key(value):
    data = b"\0" if value is None else b"\1" + value
    return len(data).to_bytes(4, "little") + data + b"\x0d\x0b"


class Cep78WasmTests(WasmTestCase):
    def hosts(self, **args):
        for suffix in (".wasm", ".metered.wasm"):
            with self.subTest(suffix=suffix):
                host = Harness(build_file("my_nft" + suffix))
                host.invoke("call", args)
                yield host

    def register(self, host, *owners):
        for owner in owners or (key(0x11),):
            result = host.invoke("register_owner", {"token_owner": owner})
            self.assertEqual(result[-3:], b"\x13\x0a\x0c")

    def mint(self, host, owner=None, metadata=METADATA, **args):
        return host.invoke("mint", {"token_owner": owner or key(0x11),
                                   "token_meta_data": payload("String", metadata), **args})

    def balance(self, host, owner, expected):
        self.assertEqual(host.invoke("balance_of", {"token_owner": owner}), cl_u64(expected))

    def test_exports_default_state_and_independent_ces_schema(self):
        for host in self.hosts():
            exports = {item.name for item in host.module.exports if isinstance(item.type, wasmtime.FuncType)}
            self.assertEqual(exports, {"call"} | {point["name"] for point in FIXTURES["abi"]})
            self.assertEqual(host.stored("__events_schema").hex(), FIXTURES["ces_schemas"])
            self.assertEqual(host.stored("collection_name"), envelope("String", "My NFT"))
            self.assertEqual(host.stored("number_of_minted_tokens"), cl_u64(0))
            self.assertEqual(set(host.account), {prefix + "My NFT" for prefix in
                ("cep78_contract_hash_", "cep78_contract_package_", "cep78_contract_package_access_", "cep78_contract_version_")})
            self.assert_reverts(host, "init", {}, 65536 + 58)
            self.assert_reverts(host, "init", {"cep78_package_key": b"bad"}, 3)

    def test_mint_receipts_and_binary_events_match_rust(self):
        fixture = next(event for event in FIXTURES["events"] if event["name"] == "Mint")
        for host in self.hosts():
            recipient = key(0x33)
            self.register(host, recipient)
            host.cells[host.contract["number_of_minted_tokens"][1:33].hex()] = cl_u64(42)
            result = self.mint(host, recipient, json.loads(fixture["json"])["data"])
            self.assertEqual(result[-4:], b"\x14\x0a\x0b\x0a")
            self.assertEqual(result[-10:-4], payload("String", "42"))
            seed = host.contract["__events"][1:33].hex()
            stored = unwrap(host.dictionaries[seed]["0"])
            self.assertEqual(stored[4:].hex(), fixture["ces"])
            self.assertEqual(host.invoke("owner_of", {"token_id": u64(42)}), envelope("Key", recipient))
            self.balance(host, recipient, 1)
            # The tuple's receipt address is the exact Casper dictionary address.
            page_seed = host.contract["page_0"][1:33]
            address = b"\x09" + blake2b(page_seed + ("33" * 32).encode(), digest_size=32).digest()
            self.assertIn(address, result)
            host.caller = recipient[1:]
            self.assertIn(address, host.invoke("updated_receipts"))

    def test_approve_revoke_transfer_self_transfer_burn_and_supply(self):
        alice, bob, carol = key(0x11), key(0x22), key(0x33)
        for host in self.hosts(total_token_supply=u64(1)):
            self.assert_reverts(host, "mint", {"token_owner": alice, "token_meta_data": payload("String", METADATA)}, 65536 + 127)
            self.register(host, alice, carol)
            self.mint(host)
            host.invoke("approve", {"spender": bob, "token_id": u64(0)})
            self.assertEqual(host.invoke("get_approved", {"token_id": u64(0)}), option_key(bob))
            host.invoke("revoke", {"token_id": u64(0)})
            self.assertEqual(host.invoke("get_approved", {"token_id": u64(0)}), option_key(None))
            host.invoke("approve", {"spender": bob, "token_id": u64(0)})
            args = {"source_key": alice, "target_key": carol, "token_id": u64(0)}
            host.caller = carol[1:]
            self.assert_reverts(host, "transfer", args, 65536 + 6)
            host.caller = bob[1:]
            self.assertEqual(host.invoke("transfer", args)[-3:], b"\x13\x0a\x0b")
            self.balance(host, alice, 0)
            self.balance(host, carol, 1)
            host.caller = carol[1:]
            host.invoke("transfer", {**args, "source_key": carol})
            self.balance(host, carol, 1)
            host.invoke("burn", {"token_id": u64(0)})
            self.balance(host, carol, 0)
            self.assertEqual(host.invoke("owner_of", {"token_id": u64(0)}), envelope("Key", carol))
            self.assert_reverts(host, "burn", {"token_id": u64(0)}, 65536 + 42)
            host.caller = alice[1:]
            self.assert_reverts(host, "mint", {"token_owner": alice, "token_meta_data": payload("String", METADATA)}, 65536 + 32)

    def test_hash_identifiers_are_raw_metadata_hashes_and_duplicates_roll_back(self):
        expected = blake2b(METADATA.encode(), digest_size=32).hexdigest()
        for host in self.hosts(identifier_mode=b"\1", metadata_mutability=b"\0"):
            self.register(host)
            self.assertIn(payload("String", expected), self.mint(host))
            before = deepcopy(host.dictionaries)
            self.assert_reverts(host, "mint", {"token_owner": key(0x11), "token_meta_data": payload("String", METADATA)}, 65536 + 170)
            self.assertEqual(host.dictionaries, before)
            self.assertEqual(host.stored("number_of_minted_tokens"), cl_u64(1))
            self.mint(host, token_hash=payload("String", "custom"))
            self.assertEqual(host.invoke("owner_of", {"token_hash": payload("String", "custom")}), envelope("Key", key(0x11)))
            self.assert_reverts(host, "set_token_metadata", {"token_hash": payload("String", "custom"),
                "token_meta_data": payload("String", METADATA)}, 65536 + 104)

    def test_metadata_validation_unicode_canonical_format_and_updates(self):
        fixture = FIXTURES["metadata"][0]
        for host in self.hosts():
            self.register(host)
            self.assert_reverts(host, "mint", {"token_owner": key(0x11), "token_meta_data": payload("String", "{}")}, 65536 + 89)
            self.mint(host, metadata=fixture["input"])
            self.assertEqual(host.invoke("metadata", {"token_id": u64(0)}), envelope("String", fixture["expected"]))
            updated = fixture["input"].replace("Token 🦀 é", "Changed")
            host.invoke("set_token_metadata", {"token_id": u64(0), "token_meta_data": payload("String", updated)})
            self.assertIn(b"Changed", host.invoke("metadata", {"token_id": u64(0)}))
            before = deepcopy(host.dictionaries)
            self.assert_reverts(host, "set_token_metadata", {"token_id": u64(0), "token_meta_data": payload("String", "{}")}, 65536 + 89)
            self.assertEqual(host.dictionaries, before)

    def test_operators_burn_opt_in_and_admin_pause(self):
        alice, bob = key(0x11), key(0x22)
        for host in self.hosts():
            self.register(host)
            self.mint(host)
            host.invoke("set_variables", {"allow_minting": b"\0"})
            self.assert_reverts(host, "mint", {"token_owner": alice, "token_meta_data": payload("String", METADATA)}, 65536 + 59)
            host.invoke("set_approval_for_all", {"approve_all": b"\1", "operator": bob})
            self.assertEqual(host.invoke("is_approved_for_all", {"token_owner": alice, "operator": bob}), envelope("Bool", True))
            host.caller = bob[1:]
            self.assert_reverts(host, "set_variables", {"allow_minting": b"\1"}, 65536 + 1)
            self.assert_reverts(host, "burn", {"token_id": u64(0)}, 65536 + 6)
            host.caller = alice[1:]
            host.invoke("set_variables", {"operator_burn_mode": b"\1"})
            host.caller = bob[1:]
            host.invoke("burn", {"token_id": u64(0)})
            self.balance(host, alice, 0)

    def test_event_modes_native_payloads_cep47_and_mode_switch_keeps_history(self):
        for mode in (0, 1, 3, 4):
            for host in self.hosts(events_mode=bytes([mode])):
                self.register(host)
                self.mint(host)
                if mode == 1:
                    history = host.dictionaries[host.contract["events"][1:33].hex()]
                    self.assertEqual(history["len"], cl_u64(1))
                    self.assertIn(payload("String", "Mint"), history["0"])
                elif mode in (3, 4):
                    self.assertEqual(host.messages[-1][1][0], mode - 3)
                    fields = json.loads(host.messages[-1][1][5:].decode())
                    self.assertEqual(fields["data"], METADATA)
        for host in self.hosts():
            self.register(host)
            self.mint(host)
            original = host.contract["events_mode"]
            host.invoke("migrate", {"events_mode": b"\3"})
            host.invoke("migrate", {"events_mode": b"\2"})
            self.assertEqual(host.contract["events_mode"], original)
            self.assertEqual(int.from_bytes(unwrap(host.stored("__events_length")), "little"), 2)

    def test_no_lookup_returns_unit_and_invalid_arguments_use_decoder_errors(self):
        for host in self.hosts(owner_reverse_lookup_mode=b"\0"):
            self.assertEqual(host.invoke("register_owner", {"token_owner": key(0x11)}), envelope("Unit"))
            self.assertEqual(self.mint(host), envelope("Unit"))
            self.assertEqual(host.invoke("transfer", {"source_key": key(0x11), "target_key": key(0x22), "token_id": u64(0)}), envelope("Unit"))
            self.assertEqual(host.invoke("updated_receipts"), envelope("Unit"))
            self.assert_reverts(host, "owner_of", {}, 65536 + 27)
            self.assert_reverts(host, "owner_of", {"token_id": b"bad"}, 3)
            self.assert_reverts(host, "migrate", {"events_mode": b"\xff"}, 65536 + 149)

    def test_custom_metadata_schema_and_page_boundary(self):
        schema = '{"properties":{"a":{"name":"A","description":"required","required":true}}}'
        for host in self.hosts(nft_metadata_kind=b"\3", json_schema=payload("String", schema), total_token_supply=u64(1001)):
            self.register(host)
            host.cells[host.contract["number_of_minted_tokens"][1:33].hex()] = cl_u64(999)
            self.assertIn(b"_p_0", self.mint(host, metadata='{"a":"\\ud83e\\udd80"}'))
            self.assertIn(b"_p_1", self.mint(host, metadata='{"a":"next"}'))
            self.assertIn("🦀".encode(), host.invoke("metadata", {"token_id": u64(999)}))
            self.assertIn("page_1", host.contract)
            self.assertIn(b"_p_1", host.invoke("updated_receipts"))
