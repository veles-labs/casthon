"""Behavioral port tests and independent upstream Rust serialization vectors."""

from copy import deepcopy
import json
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

from casthon import (
    AccountHash, ApiError, CLKey, CLKeyList, CLString, CLU8, CLU256,
    ContractHash, ContractPackageHash, Key, InvalidArgument, MessageBytes, MessageString, UserError,
    ABIError, MissingArgument, URef,
)
from casthon.contract_api import runtime
from casthon.caller import decode_caller_information
from casthon.entry_points import serialize_entry_points
from casthon.testing import ContractHarness, MockHost, use_host
from casthon.testing.values import inspect_value, parse_key
from contracts import my_token
from contracts.cep18 import Cep18, MAX_U256, address_key, allowance_key, immediate_caller
from contracts.cep18_errors import (
    AlreadyInitialized, CannotTargetSelfUser, Cep18Error, InsufficientAllowance,
    InsufficientBalance, InsufficientRights, InvalidAdminList, InvalidBurnTarget,
    InvalidEventsMode, InvalidMinterList, InvalidNoneList, InvalidEnableMBFlag, MintBurnDisabled, Overflow,
)
from contracts.cep18_events import EventsMode, Transfer
from casthon import Bytesrepr, Json, JsonBytes
from casthon.codec import encode
from casthon.events import event_schemas, event_schema
from contracts.my_token import MyToken

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = json.loads((ROOT / "reference/cep18/fixtures.json").read_text())
sys.path.insert(0, str(ROOT / "scripts"))
from bundle import load_contract, generate_exports, lower, lower_enums
sys.path.insert(0, str(ROOT / "tests/fixtures"))
import cep18_client


class Cep18ReferenceTests(unittest.TestCase):
    def test_inherited_abi_matches_all_sixteen_rust_entrypoints(self):
        expected = FIXTURES["entry_points"]
        self.assertEqual(serialize_entry_points(Cep18.entry_points()).hex(), expected)
        self.assertEqual(serialize_entry_points(MyToken.entry_points()).hex(), expected)
        self.assertNotIn("call", [point.name for point in MyToken.entry_points()])

    def test_dictionary_keys_match_upstream(self):
        owner = AccountHash(bytes([0x11]) * 32)
        spender = ContractHash(bytes([0x22]) * 32)
        with use_host(MockHost()):
            self.assertEqual(address_key(owner), FIXTURES["dictionary"]["balance"])
            self.assertEqual(allowance_key(bytes(owner) + bytes(spender)), FIXTURES["dictionary"]["allowance"])

    def test_ces_schema_and_every_event_encoding_match_rust(self):
        self.assertEqual(event_schemas(Cep18.event_types()).to_bytes().hex(), FIXTURES["ces_schemas"])
        for fixture in FIXTURES["events"]:
            with self.subTest(event=fixture["name"]):
                values = json.loads(fixture["json"])
                for field, value in values.items():
                    if isinstance(value, dict):
                        values[field] = {parse_key(key): ("Admin", "Minter", "None").index(badge)
                                         for key, badge in value.items()}
                    elif isinstance(value, str):
                        values[field] = int(value) if value.isdigit() else parse_key(value)
                event_class = next(owner for owner in Cep18.event_types() if event_schema(owner).name == fixture["name"])
                if fixture["name"] == "ChangeEventsMode":
                    values["events_mode"] = EventsMode.from_value(values["events_mode"])
                event = event_class(**values)
                binary = Bytesrepr.to_message(event)
                self.assertIsInstance(binary, MessageBytes)
                self.assertEqual((encode(str, "event_" + fixture["name"]) + binary.value).hex(), fixture["ces"])
                string = Json.to_message(event)
                self.assertIsInstance(string, MessageString)
                text = string.value
                self.assertEqual(text, fixture["json"])
                self.assertEqual(MessageString(text).to_bytes().hex(), fixture["native_string"])
                self.assertEqual(JsonBytes.to_message(event).to_bytes().hex(), fixture["native_bytes"])

    def test_account_legacy_contract_and_entity_caller_identities(self):
        expected = (AccountHash(bytes([0x11]) * 32), ContractPackageHash(bytes([0x22]) * 32),
                    Key.from_bytes(b"\x11\x02" + bytes([0x66]) * 32))
        for data, key in zip(FIXTURES["callers"], expected):
            info, = decode_caller_information(bytes.fromhex(data))
            with patch("casthon.contract_api.runtime.get_immediate_caller", return_value=info):
                self.assertEqual(immediate_caller(), key)

    def test_frozen_inherited_schemas_and_enum_members_match_authoring(self):
        path = ROOT / "contracts/my_token.py"
        declaration, _ = load_contract(path)
        self.assertEqual(set(declaration["exports"]), {"call"} | {p.name for p in MyToken.entry_points()})
        exports = types.ModuleType("_cspr_exports")
        exec(generate_exports(path, declaration["exports"]), vars(exports))
        self.assertTrue(all(value[0] == "MyToken" for value in exports.BINDINGS.values() if len(value) > 1))
        self.assertNotIn("@entry_point", lower(ROOT / "contracts/cep18.py"))
        self.assertNotIn("@export_contract", lower(path))
        frozen_enums = types.ModuleType("frozen_enums")
        sdk_enums = types.ModuleType("casthon.enums")
        exec(lower_enums(ROOT / "src/casthon/enums.py"), vars(sdk_enums))
        with patch.dict(sys.modules, {"casthon.enums": sdk_enums}):
            exec(lower(ROOT / "contracts/cep18_events.py"), vars(frozen_enums))
        mode = frozen_enums.EventsMode
        self.assertEqual((mode.CES.name, int(mode.CES), mode.from_value(1)), ("CES", 1, mode.CES))
        with self.assertRaises(InvalidEventsMode):
            mode.from_value(4)
        self.assertIs(mode(1), mode.CES)

    def test_frozen_enum_profile_rejects_aliases_methods_and_noninteger_values(self):
        for body in ("    A = 1\n    B = 1", "    A = 1\n    A = 2", "    A = 'one'",
                     "    def method(self): pass"):
            with self.subTest(body=body), tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / "enum_fixture.py"
                path.write_text("from casthon.enums import WireEnum\nclass Mode(WireEnum):\n" + body + "\n")
                with self.assertRaises(ValueError):
                    lower(path)


class Cep18Tests(unittest.TestCase):
    def setUp(self):
        self.alice, self.bob, self.carol = [AccountHash(bytes([n]) * 32) for n in (0x11, 0x22, 0x33)]
        self.host = MockHost(caller=self.alice, strict_arguments=True)
        self.session = ContractHarness(my_token, host=self.host)

    def install(self, **args):
        self.session.invoke("call", args)
        name = args.get("name", CLString("My Token")).value
        key = self.host.accounts[self.alice]["cep18_contract_hash_" + name]
        return ContractHarness(MyToken, host=self.host, contract=key)

    def balance(self, token, owner):
        return token.invoke("balance_of", {"address": CLKey(owner)}).value

    def allowance(self, token, owner, spender):
        return token.invoke("allowance", {"owner": CLKey(owner), "spender": CLKey(spender)}).value

    def events(self, token):
        seed = self.host.contracts[token.contract]["__events"]
        return [inspect_value(value)[1] for value in self.host.dictionaries[seed.address].values()]

    def test_default_constructor_and_explicit_installer(self):
        token = self.install()
        self.assertEqual(token.invoke("name").value, "My Token")
        self.assertEqual(token.invoke("symbol").value, "MYT")
        self.assertEqual(token.invoke("decimals").value, 18)
        self.assertEqual(token.invoke("total_supply").value, 10**24)
        self.assertEqual(self.balance(token, self.alice), 10**24)
        self.assertEqual(self.balance(token, self.bob), 0)
        self.assertEqual(self.allowance(token, self.alice, self.bob), 0)
        self.assertEqual(set(self.host.accounts[self.alice]), {
            "cep18_contract_package_My Token", "cep18_contract_package_access_My Token",
            "cep18_contract_hash_My Token", "cep18_contract_version_My Token"})
        self.assertEqual(len(self.events(token)), 1)
        with self.assertRaises(AlreadyInitialized):
            token.invoke("init")  # No deployment arguments are required to reject replay.

    def test_init_decorator_runs_after_argument_decoding(self):
        token = self.install(events_mode=CLU8(0))
        before = len(self.host.calls)
        with self.assertRaises(ABIError):
            token.invoke("init", raw_args={"package_hash": b"bad", "contract_hash": b"bad"})
        self.assertTrue(any(name == "get_named_arg" for name, args in self.host.calls[before:]))
        del self.host.contracts[token.contract]["package_hash"]
        with self.assertRaises(MissingArgument):
            token.invoke("init")
        with self.assertRaises(ABIError):
            token.invoke("init", raw_args={"package_hash": b"bad"})

    def test_constructor_supports_local_calls_catchable_errors_and_finally(self):
        with use_host(self.host):
            created = MyToken(total_supply=10, events_mode=EventsMode.NO_EVENTS)
            self.assertEqual(created.balance_of(self.alice), 10)
            self.assertFalse(any(self.host.accounts.values()))
        installed = self.install(total_supply=CLU256(10), events_mode=CLU8(0))
        with self.host.context(contract=installed.contract), use_host(self.host):
            token = MyToken.bind()
            try:
                token.transfer(self.bob, 11)
            except InsufficientBalance as error:
                self.assertIsInstance(error, UserError)
                self.assertIsInstance(error, ApiError)
                self.assertEqual(error.code, 65536 + 60001)
            else:
                self.fail("Expected an ordinary catchable contract exception")
            finally:
                token.token_symbol = "CLEANUP"
            self.assertEqual(token.symbol(), "CLEANUP")
            self.assertEqual(token.balance_of(self.alice), 10)

    def test_immediate_caller_is_absent_in_session_code(self):
        with use_host(self.host), self.assertRaises(ApiError) as error:
            immediate_caller()
        self.assertEqual(error.exception.code, 31)

    def test_dispatch_validates_u256_arguments_before_any_write(self):
        token = self.install(total_supply=CLU256(100), events_mode=CLU8(0))
        self.host.strict_arguments = False
        before = deepcopy((self.host.cells, self.host.dictionaries))
        entries = (("approve", {"spender": bytes(self.bob)}),
                   ("increase_allowance", {"spender": bytes(self.bob)}),
                   ("decrease_allowance", {"spender": bytes(self.bob)}),
                   ("transfer", {"recipient": bytes(self.bob)}),
                   ("transfer_from", {"owner": bytes(self.alice), "recipient": bytes(self.bob)}),
                   ("mint", {"owner": bytes(self.alice)}), ("burn", {"owner": bytes(self.alice)}))
        from casthon import ABIError
        for entry, args in entries:
            for invalid in (b"", b"\x21" + bytes(33), b"\x01", b"\x00\x01"):
                with self.subTest(entry=entry, invalid=invalid), self.assertRaises(ABIError):
                    token.invoke(entry, raw_args={**args, "amount": invalid})
        self.assertEqual((self.host.cells, self.host.dictionaries), before)

    def test_transfers_preserve_supply_and_revert_insufficient_balance(self):
        token = self.install(total_supply=CLU256(100))
        token.invoke("transfer", {"recipient": CLKey(self.bob), "amount": CLU256(40)})
        self.assertEqual((self.balance(token, self.alice), self.balance(token, self.bob)), (60, 40))
        self.assertEqual(token.invoke("total_supply").value, 100)
        before = deepcopy((self.host.cells, self.host.dictionaries))
        with self.assertRaises(InsufficientBalance):
            token.invoke("transfer", {"recipient": CLKey(self.bob), "amount": CLU256(61)})
        self.assertEqual((self.host.cells, self.host.dictionaries), before)
        token.invoke("transfer", {"recipient": CLKey(self.carol), "amount": CLU256(0)})
        self.assertEqual(len(self.events(token)), 3)  # A zero direct transfer emits an event.
        with self.assertRaises(CannotTargetSelfUser):
            token.invoke("transfer", {"recipient": CLKey(self.alice), "amount": CLU256(0)})

    def test_delegated_transfer_consumes_allowance_and_rolls_back_failures(self):
        token = self.install(total_supply=CLU256(100))
        token.invoke("approve", {"spender": CLKey(self.bob), "amount": CLU256(150)})
        args = {"owner": CLKey(self.alice), "recipient": CLKey(self.carol), "amount": CLU256(101)}
        with self.assertRaises(InsufficientBalance):
            token.invoke("transfer_from", args, caller=self.bob)
        self.assertEqual(self.allowance(token, self.alice, self.bob), 150)
        args["amount"] = CLU256(30)
        token.invoke("transfer_from", args, caller=self.bob)
        self.assertEqual(self.allowance(token, self.alice, self.bob), 120)
        self.assertEqual(self.balance(token, self.carol), 30)
        with self.assertRaises(InsufficientAllowance):
            token.invoke("transfer_from", args, caller=self.carol)
        count = len(self.events(token))
        args["amount"] = CLU256(0)
        token.invoke("transfer_from", args, caller=self.carol)
        self.assertEqual(len(self.events(token)), count)  # Zero delegated transfers do not emit.
        args["recipient"] = CLKey(self.alice)
        with self.assertRaises(CannotTargetSelfUser):
            token.invoke("transfer_from", args, caller=self.bob)

    def test_allowance_saturates_and_rejects_self_targets(self):
        token = self.install()
        token.invoke("approve", {"spender": CLKey(self.bob), "amount": CLU256(MAX_U256 - 1)})
        token.invoke("increase_allowance", {"spender": CLKey(self.bob), "amount": CLU256(10)})
        self.assertEqual(self.allowance(token, self.alice, self.bob), MAX_U256)
        token.invoke("decrease_allowance", {"spender": CLKey(self.bob), "amount": CLU256(MAX_U256)})
        token.invoke("decrease_allowance", {"spender": CLKey(self.bob), "amount": CLU256(1)})
        self.assertEqual(self.allowance(token, self.alice, self.bob), 0)
        for entry in ("approve", "increase_allowance", "decrease_allowance"):
            with self.subTest(entry=entry), self.assertRaises(CannotTargetSelfUser):
                token.invoke(entry, {"spender": CLKey(self.alice), "amount": CLU256(1)})

    def test_mint_burn_security_and_total_supply(self):
        token = self.install(total_supply=CLU256(100), minter_list=CLKeyList([self.bob]))
        token.invoke("mint", {"owner": CLKey(self.carol), "amount": CLU256(7)}, caller=self.bob)
        self.assertEqual(token.invoke("total_supply").value, 107)
        with self.assertRaises(InsufficientRights):
            token.invoke("mint", {"owner": CLKey(self.carol), "amount": CLU256(1)}, caller=self.carol)
        with self.assertRaises(InvalidBurnTarget):
            token.invoke("burn", {"owner": CLKey(self.carol), "amount": CLU256(1)})
        token.invoke("burn", {"owner": CLKey(self.carol), "amount": CLU256(3)}, caller=self.carol)
        self.assertEqual(token.invoke("total_supply").value, 104)
        self.assertEqual(self.balance(token, self.carol), 4)
        with self.assertRaises(InsufficientBalance):
            token.invoke("burn", {"owner": CLKey(self.carol), "amount": CLU256(5)}, caller=self.carol)

    def test_disabled_mint_burn_and_nonzero_u8_flag_semantics(self):
        disabled = self.install(enable_mint_burn=CLU8(0), events_mode=CLU8(0))
        for entry, args in (("mint", {"owner": CLKey(self.alice), "amount": CLU256(0)}),
                            ("burn", {"owner": CLKey(self.alice), "amount": CLU256(0)}),
                            ("change_security", {})):
            with self.subTest(entry=entry), self.assertRaises(MintBurnDisabled):
                disabled.invoke(entry, args)
        # Changing event mode remains an admin operation when mint/burn is off.
        disabled.invoke("change_events_mode", {"events_mode": CLU8(1)})
        other = self.install(name=CLString("Nonzero"), enable_mint_burn=CLU8(255), events_mode=CLU8(0))
        other.invoke("mint", {"owner": CLKey(self.bob), "amount": CLU256(1)})

    def test_overflow_is_checked_before_any_write(self):
        token = self.install(total_supply=CLU256(MAX_U256))
        for owner in (self.alice, self.bob):
            with self.subTest(owner=owner), self.assertRaises(Overflow):
                token.invoke("mint", {"owner": CLKey(owner), "amount": CLU256(1)})
        self.assertEqual(self.balance(token, self.alice), MAX_U256)
        self.assertEqual(self.balance(token, self.bob), 0)
        self.assertEqual(len(self.events(token)), 1)

    def test_security_precedence_caller_protection_and_revocation(self):
        token = self.install()
        args = {"minter_list": CLKeyList([self.bob, self.carol]),
                "admin_list": CLKeyList([self.bob]), "none_list": CLKeyList([self.carol, self.alice])}
        token.invoke("change_security", args)
        token.invoke("change_events_mode", {"events_mode": CLU8(0)}, caller=self.bob)
        with self.assertRaises(InsufficientRights):
            token.invoke("mint", {"owner": CLKey(self.carol), "amount": CLU256(1)}, caller=self.carol)
        token.invoke("change_security", {"admin_list": CLKeyList([]), "minter_list": CLKeyList([]),
                                         "none_list": CLKeyList([self.bob])})
        with self.assertRaises(InsufficientRights):
            token.invoke("change_security", {}, caller=self.bob)
        token.invoke("mint", {"owner": CLKey(self.alice), "amount": CLU256(1)})

    def test_security_lists_have_explicit_missing_checks_and_plain_decoding(self):
        token = self.install()
        for name, error in (("admin_list", InvalidAdminList), ("minter_list", InvalidMinterList), ("none_list", InvalidNoneList)):
            args = {argument: CLKeyList([]) for argument in ("admin_list", "minter_list", "none_list")}
            del args[name]
            with self.subTest(name=name, missing=True), self.assertRaises(error):
                token.invoke("change_security", args)
            args[name] = CLU8(255)
            with self.subTest(name=name, malformed=True), self.assertRaises(ABIError):
                token.invoke("change_security", args)
        with self.assertRaises(ABIError):
            self.session.invoke("call", {"name": CLString("Invalid"), "admin_list": CLU8(255)})
        self.assertNotIn("cep18_contract_hash_Invalid", self.host.accounts[self.alice])

    def test_security_decorators_run_after_decoding_and_local_calls_do_not_load_arguments(self):
        token = self.install(events_mode=CLU8(0))
        with self.assertRaises(ABIError):
            token.invoke("change_security", raw_args={"admin_list": b"bad"}, caller=self.bob)
        with self.assertRaises(InsufficientRights):
            token.invoke("change_security", caller=self.bob)
        disabled = self.install(name=CLString("Disabled"), enable_mint_burn=CLU8(0), events_mode=CLU8(0))
        with self.assertRaises(ABIError):
            disabled.invoke("change_security", raw_args={"admin_list": b"bad"})
        with self.assertRaises(MintBurnDisabled):
            disabled.invoke("change_security")
        before = len(self.host.calls)
        with self.host.context(contract=token.contract), use_host(self.host):
            MyToken.bind().change_security(admin_list=[self.bob], minter_list=[], none_list=[])
        self.assertFalse(any(name == "get_named_arg" for name, args in self.host.calls[before:]))
        token.invoke("change_events_mode", {"events_mode": CLU8(0)}, caller=self.bob)

    def test_installer_uses_plain_optional_argument_decoding(self):
        for argument in ("events_mode", "enable_mint_burn", "admin_list", "minter_list"):
            with self.subTest(argument=argument), self.assertRaises(ABIError):
                self.session.invoke("call", raw_args={argument: b""})
        self.assertEqual(self.host.accounts.get(self.alice, {}), {})

    def test_events_modes_switch_without_resetting_ces_history(self):
        token = self.install()
        with self.host.context(contract=token.contract), use_host(self.host):
            original = runtime.named_keys.reference("events_mode", URef[EventsMode]).get()
        addresses = set(self.host.cells)
        token.invoke("change_events_mode", {"events_mode": CLU8(2)})
        with self.host.context(contract=token.contract), use_host(self.host):
            self.assertEqual(runtime.named_keys["events_mode"], original)
            self.assertIs(original.read(), EventsMode.NATIVE)
            self.assertIs(MyToken.bind().events_mode, EventsMode.NATIVE)
        self.assertEqual(set(self.host.cells), addresses)
        token.invoke("transfer", {"recipient": CLKey(self.bob), "amount": CLU256(1)})
        self.assertEqual(self.host.messages[-1][2], Json.to_message(Transfer(self.alice, self.bob, 1)).to_bytes())
        token.invoke("change_events_mode", {"events_mode": CLU8(3)})
        token.invoke("approve", {"spender": CLKey(self.bob), "amount": CLU256(2)})
        self.assertEqual(self.host.messages[-1][2][0], 1)
        token.invoke("change_events_mode", {"events_mode": CLU8(0)})
        count = len(self.host.messages)
        token.invoke("transfer", {"recipient": CLKey(self.bob), "amount": CLU256(0)})
        self.assertEqual(len(self.host.messages), count)
        token.invoke("change_events_mode", {"events_mode": CLU8(1)})
        self.assertEqual(len(self.events(token)), 2)
        token.invoke("change_events_mode", {"events_mode": CLU8(1)})
        self.assertEqual(len(self.events(token)), 2)
        with self.assertRaises(InvalidEventsMode):
            token.invoke("change_events_mode", {"events_mode": CLU8(4)})
        self.assertEqual(len(self.events(token)), 2)
        self.assertEqual(set(self.host.cells), addresses)
        with self.host.context(contract=token.contract), use_host(self.host):
            self.assertEqual(runtime.named_keys["events_mode"], original)
            self.assertIs(original.read(), EventsMode.CES)

    def test_failed_event_rolls_back_prior_balance_and_allowance_writes(self):
        token = self.install()
        self.host.fail_next("dictionary_put", ApiError(17))
        before = deepcopy(self.host.dictionaries)
        with self.assertRaises(ApiError):
            token.invoke("approve", {"spender": CLKey(self.bob), "amount": CLU256(7)})
        self.assertEqual(self.host.dictionaries, before)
        self.assertEqual(len(self.events(token)), 1)

    def test_upgrade_preserves_storage_topics_and_disables_old_version(self):
        token = self.install(total_supply=CLU256(100))
        token.invoke("transfer", {"recipient": CLKey(self.bob), "amount": CLU256(7)})
        upgraded = self.install(events_mode=CLU8(2))
        self.assertNotEqual(upgraded.contract, token.contract)
        self.assertIn(token.contract, self.host.disabled)
        self.assertEqual(self.balance(upgraded, self.bob), 7)
        self.assertEqual(upgraded.invoke("total_supply").value, 100)
        self.assertEqual(self.host.message_topics[upgraded.contract], {"events"})
        version = self.host.accounts[self.alice]["cep18_contract_version_My Token"]
        self.assertEqual(inspect_value(self.host.cells[version.address])[1], "2.2")
        self.assertEqual(len(self.host.messages), 1)

    def test_stored_caller_uses_package_identity_for_balances_and_allowances(self):
        token = self.install(total_supply=CLU256(100))
        installer = ContractHarness(cep18_client, host=self.host)
        installer.invoke("call", {"token": CLKey(token.contract)})
        keys = self.host.accounts[self.alice]
        package, contract = keys["py_token_client_package"], keys["py_token_client"]
        client = ContractHarness(cep18_client.TokenClient, host=self.host, contract=contract)
        token.invoke("transfer", {"recipient": CLKey(package), "amount": CLU256(10)})
        client.invoke("transfer", {"recipient": CLKey(self.bob), "amount": CLU256(3)})
        self.assertEqual(client.invoke("balance").value, 7)
        self.assertEqual(self.balance(token, self.alice), 90)
        client.invoke("approve", {"spender": CLKey(self.bob), "amount": CLU256(5)})
        self.assertEqual(self.allowance(token, package, self.bob), 5)
        self.assertEqual(self.allowance(token, self.alice, self.bob), 0)
        token.invoke("approve", {"spender": CLKey(package), "amount": CLU256(8)})
        client.invoke("transfer_from", {"owner": CLKey(self.alice), "recipient": CLKey(self.bob), "amount": CLU256(4)})
        self.assertEqual(self.balance(token, self.alice), 86)
        self.assertEqual(self.allowance(token, self.alice, package), 4)
        # Importing a decorated or undecorated contract adds no Wasm exports.
        for source, expected in (("cep18_session.py", {"call"}),
                                 ("cep18_client.py", {"call", "approve", "transfer", "transfer_from", "balance"})):
            declaration, _ = load_contract(ROOT / "tests/fixtures" / source)
            self.assertEqual(set(declaration["exports"]), expected)

