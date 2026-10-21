"""Execute inherited CEP-18 exports in plain and stock-500-stack metered Wasm."""

from copy import deepcopy
import json
import wasmtime

from test_wasm_basic import WasmTestCase
from wasm_harness import Harness, ROOT, build_file, envelope, payload, unwrap

FIXTURES = json.loads((ROOT / "reference/cep18/fixtures.json").read_text())


def key(number):
    return b"\0" + bytes([number]) * 32


def key_list(items):
    return len(items).to_bytes(4, "little") + b"".join(items)


class Cep18WasmTests(WasmTestCase):
    def hosts(self, **args):
        for suffix in (".wasm", ".metered.wasm"):
            host = Harness(build_file("my_token" + suffix))
            host.invoke("call", args)
            yield host

    def balance(self, host, owner, amount):
        self.assertEqual(host.invoke("balance_of", {"address": owner}), envelope("U256", amount))

    def allowance(self, host, owner, spender, amount):
        self.assertEqual(host.invoke("allowance", {"owner": owner, "spender": spender}), envelope("U256", amount))

    def event_count(self, host):
        return int.from_bytes(unwrap(host.stored("__events_length")), "little")

    def test_inherited_exports_abi_default_state_and_ces_schema(self):
        for host in self.hosts():
            exports = {item.name for item in host.module.exports if isinstance(item.type, wasmtime.FuncType)}
            self.assertEqual(exports, {"call"} | {point["name"] for point in FIXTURES["abi"]})
            self.assertEqual(host.entry_points.hex(), FIXTURES["entry_points"])
            self.assertEqual(host.stored("__events_schema").hex(), FIXTURES["ces_schemas"])
            self.assertEqual(host.invoke("name"), envelope("String", "My Token"))
            self.assertEqual(host.invoke("symbol"), envelope("String", "MYT"))
            self.assertEqual(host.invoke("decimals"), envelope("U8", 18))
            self.assertEqual(host.invoke("total_supply"), envelope("U256", 10**24))
            self.balance(host, key(0x11), 10**24)
            self.balance(host, key(0x22), 0)
            self.assertEqual(self.event_count(host), 1)
            self.assertEqual(set(host.account), {"cep18_contract_hash_My Token", "cep18_contract_package_My Token",
                "cep18_contract_package_access_My Token", "cep18_contract_version_My Token"})
            self.assert_reverts(host, "init", {}, 65536 + 60015)

    def test_transfers_delegation_zero_amounts_and_rollback(self):
        alice, bob, carol = key(0x11), key(0x22), key(0x33)
        for host in self.hosts(total_supply=payload("U256", 100)):
            host.invoke("transfer", {"recipient": bob, "amount": payload("U256", 20)})
            host.invoke("approve", {"spender": bob, "amount": payload("U256", 90)})
            host.caller = bob[1:]
            args = {"owner": alice, "recipient": carol, "amount": payload("U256", 81)}
            self.assert_reverts(host, "transfer_from", args, 65536 + 60001)
            self.allowance(host, alice, bob, 90)
            args["amount"] = payload("U256", 30)
            host.invoke("transfer_from", args)
            self.allowance(host, alice, bob, 60)
            self.balance(host, alice, 50)
            self.balance(host, carol, 30)
            host.caller = carol[1:]
            self.assert_reverts(host, "transfer_from", args, 65536 + 60002)
            count = self.event_count(host)
            args["amount"] = payload("U256", 0)
            host.invoke("transfer_from", args)
            self.assertEqual(self.event_count(host), count)
            host.invoke("transfer", {"recipient": bob, "amount": payload("U256", 0)})
            self.assertEqual(self.event_count(host), count + 1)
            self.assert_reverts(host, "transfer", {"recipient": carol, "amount": payload("U256", 0)}, 65536 + 60017)
            self.assertEqual(host.invoke("total_supply"), envelope("U256", 100))

    def test_saturation_mint_burn_permissions_and_u256_overflow(self):
        alice, bob = key(0x11), key(0x22)
        maximum = (1 << 256) - 1
        for host in self.hosts(total_supply=payload("U256", maximum)):
            host.invoke("approve", {"spender": bob, "amount": payload("U256", maximum - 1)})
            host.invoke("increase_allowance", {"spender": bob, "amount": payload("U256", 7)})
            self.allowance(host, alice, bob, maximum)
            host.invoke("decrease_allowance", {"spender": bob, "amount": payload("U256", maximum)})
            host.invoke("decrease_allowance", {"spender": bob, "amount": payload("U256", 1)})
            self.allowance(host, alice, bob, 0)
            self.assert_reverts(host, "mint", {"owner": bob, "amount": payload("U256", 1)}, 65536 + 60003)
            self.balance(host, bob, 0)
            host.invoke("burn", {"owner": alice, "amount": payload("U256", 10)})
            host.invoke("mint", {"owner": bob, "amount": payload("U256", 7)})
            self.assertEqual(host.invoke("total_supply"), envelope("U256", maximum - 3))
            host.caller = bob[1:]
            self.assert_reverts(host, "mint", {"owner": bob, "amount": payload("U256", 0)}, 65536 + 60010)
            self.assert_reverts(host, "burn", {"owner": alice, "amount": payload("U256", 0)}, 65536 + 60018)
            host.invoke("burn", {"owner": bob, "amount": payload("U256", 2)})
            self.balance(host, bob, 5)

    def test_dynamic_security_lists_precedence_and_error_codes(self):
        alice, bob, carol = key(0x11), key(0x22), key(0x33)
        for host in self.hosts():
            host.invoke("change_security", {"admin_list": key_list([bob]), "minter_list": key_list([bob, carol]),
                                            "none_list": key_list([alice, carol])})
            host.caller = bob[1:]
            host.invoke("change_events_mode", {"events_mode": payload("U8", 0)})
            host.caller = carol[1:]
            self.assert_reverts(host, "mint", {"owner": carol, "amount": payload("U256", 1)}, 65536 + 60010)
            host.caller = alice[1:]
            for index, argument in enumerate(("admin_list", "minter_list", "none_list")):
                args = {name: key_list([]) for name in ("admin_list", "minter_list", "none_list")}
                del args[argument]
                self.assert_reverts(host, "change_security", args, 65536 + 60011 + index)
                args[argument] = b"\xff"
                self.assert_reverts(host, "change_security", args, 3)
            host.invoke("change_security", {"admin_list": key_list([]), "minter_list": key_list([]),
                                            "none_list": key_list([bob])})
            host.caller = bob[1:]
            self.assert_reverts(host, "change_security", {}, 65536 + 60010)
            self.assert_reverts(host, "change_security", {"admin_list": b"bad"}, 3)

    def test_installer_argument_errors_and_required_dynamic_hashes(self):
        for suffix in (".wasm", ".metered.wasm"):
            for argument in ("events_mode", "enable_mint_burn", "admin_list", "minter_list"):
                with self.subTest(suffix=suffix, argument=argument):
                    host = Harness(build_file("my_token" + suffix))
                    self.assert_reverts(host, "call", {argument: b""}, 3)
                    self.assertEqual((host.account, host.contract, host.cells), ({}, {}, {}))
            host = Harness(build_file("my_token" + suffix))
            host.invoke("call", {"events_mode": payload("U8", 0)})
            self.assert_reverts(host, "init", {"package_hash": b"bad", "contract_hash": b"bad"}, 3)
            del host.contract["package_hash"]
            self.assert_reverts(host, "init", {}, 2)
            self.assert_reverts(host, "init", {"package_hash": b"bad"}, 3)
            host.caller = key(0x22)[1:]
            self.assert_reverts(host, "change_security", {"admin_list": b"bad"}, 3)

    def test_native_messages_mode_changes_and_ces_history(self):
        bob = key(0x22)
        for host in self.hosts():
            original = host.contract["events_mode"]
            allocated = host.next
            host.invoke("change_events_mode", {"events_mode": payload("U8", 2)})
            self.assertEqual(host.contract["events_mode"], original)
            self.assertEqual(host.stored("events_mode"), envelope("U8", 2))
            self.assertEqual(host.messages[-1], ("events", bytes.fromhex(next(f["native_string"] for f in FIXTURES["events"]
                if f["name"] == "ChangeEventsMode" and json.loads(f["json"])["events_mode"] == 2))))
            host.invoke("transfer", {"recipient": bob, "amount": payload("U256", 1)})
            text = '{"sender":"account-hash-' + host.caller.hex() + '","recipient":"account-hash-' + bob[1:].hex() + '","amount":"1"}'
            self.assertEqual(host.messages[-1], ("events", b"\0" + payload("String", text)))
            host.invoke("change_events_mode", {"events_mode": payload("U8", 3)})
            host.invoke("transfer", {"recipient": bob, "amount": payload("U256", 1)})
            self.assertEqual(host.messages[-1], ("events", b"\1" + payload("String", text)))
            host.invoke("change_events_mode", {"events_mode": payload("U8", 0)})
            count = len(host.messages)
            host.invoke("transfer", {"recipient": bob, "amount": payload("U256", 0)})
            self.assertEqual(len(host.messages), count)
            host.invoke("change_events_mode", {"events_mode": payload("U8", 1)})
            self.assertEqual(self.event_count(host), 2)
            self.assert_reverts(host, "change_events_mode", {"events_mode": payload("U8", 4)}, 65536 + 60006)
            self.assertEqual(host.contract["events_mode"], original)
            self.assertEqual(host.cells[original[1:33].hex()], envelope("U8", 1))
            self.assertEqual(host.next, allocated)

    def test_package_and_entity_callers_do_not_spend_initiator_balances(self):
        alice, bob = key(0x11), key(0x33)
        owners = (b"\x01" + bytes([0x22]) * 32, b"\x11\x02" + bytes([0x66]) * 32)
        for host in self.hosts():
            for info, owner in zip(FIXTURES["callers"][1:], owners):
                host.caller_information = bytes.fromhex(info)
                host.invoke("approve", {"spender": bob, "amount": payload("U256", 7)})
                self.allowance(host, owner, bob, 7)
                self.allowance(host, alice, bob, 0)
                self.assert_reverts(host, "transfer", {"recipient": bob, "amount": payload("U256", 1)}, 65536 + 60001)

    def test_failed_event_unwinds_and_rolls_back_prior_writes(self):
        for host in self.hosts():
            mode = host.contract["events_mode"][1:33].hex()
            host.cells[mode] = envelope("U8", 4)
            before = deepcopy(host.dictionaries)
            self.assert_reverts(host, "approve", {"spender": key(0x22), "amount": payload("U256", 7)}, 65536 + 60006)
            self.assertEqual(host.dictionaries, before)
            host.cells[mode] = envelope("U8", 1)
            self.allowance(host, key(0x11), key(0x22), 0)

    def test_ces_payloads_and_native_security_maps_match_rust_vectors(self):
        events = {event["name"]: event for event in FIXTURES["events"]}
        amount = int(json.loads(events["Mint"]["json"])["amount"])
        for host in self.hosts(total_supply=payload("U256", amount * 10)):
            seed = host.contract["__events"][1:33].hex()

            def last_event(name):
                raw = host.dictionaries[seed][str(self.event_count(host) - 1)]
                encoded_bytes = unwrap(raw)
                self.assertEqual(int.from_bytes(encoded_bytes[:4], "little"), len(encoded_bytes) - 4)
                self.assertEqual(encoded_bytes[4:].hex(), events[name]["ces"])

            host.invoke("mint", {"owner": key(0x33), "amount": payload("U256", amount)})
            last_event("Mint")
            burned = int(json.loads(events["Burn"]["json"])["amount"])
            host.invoke("burn", {"owner": key(0x11), "amount": payload("U256", burned)})
            last_event("Burn")
            spender = b"\1" + bytes([0x22]) * 32
            for name, entry, adjustment in (("SetAllowance", "approve", None),
                                            ("IncreaseAllowance", "increase_allowance", "inc_by"),
                                            ("DecreaseAllowance", "decrease_allowance", "decr_by")):
                fields = json.loads(events[name]["json"])
                desired = int(fields["allowance"])
                change = int(fields[adjustment]) if adjustment else desired
                if adjustment:
                    initial = desired - change if adjustment == "inc_by" else desired + change
                    host.invoke("approve", {"spender": spender, "amount": payload("U256", initial)})
                host.invoke(entry, {"spender": spender, "amount": payload("U256", change)})
                last_event(name)
            transferred = int(json.loads(events["Transfer"]["json"])["amount"])
            host.invoke("transfer", {"recipient": key(0x33), "amount": payload("U256", transferred)})
            last_event("Transfer")
            transferred = int(json.loads(events["TransferFrom"]["json"])["amount"])
            host.invoke("approve", {"spender": spender, "amount": payload("U256", transferred)})
            host.caller_information = bytes.fromhex(FIXTURES["callers"][1])
            host.invoke("transfer_from", {"owner": key(0x11), "recipient": key(0x33), "amount": payload("U256", transferred)})
            last_event("TransferFrom")
            host.caller_information = None
            # Multi-key native JSON must also preserve Rust Key ordering.
            fields = json.loads(events["ChangeSecurity"]["json"])
            # The serialization fixture includes its own caller. The actual
            # entrypoint protects that caller, so use a different account.
            changes = fields["sec_change_map"]
            changes["account-hash-" + bytes([0x33]).hex() * 32] = changes.pop(fields["admin"])
            fields["sec_change_map"] = dict(sorted(changes.items()))
            lists = {"Admin": [], "Minter": [], "None": []}
            for formatted, badge in fields["sec_change_map"].items():
                prefix, address = formatted.rsplit("-", 1)
                lists[badge].append((b"\0" if prefix == "account-hash" else b"\1") + bytes.fromhex(address))
            host.invoke("change_events_mode", {"events_mode": b"\2"})
            host.invoke("change_security", {"admin_list": key_list(lists["Admin"]),
                                            "minter_list": key_list(lists["Minter"]), "none_list": key_list(lists["None"])})
            expected = json.dumps(fields, separators=(",", ":"))
            self.assertEqual(host.messages[-1][1], b"\0" + payload("String", expected))

