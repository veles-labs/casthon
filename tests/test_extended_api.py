"""Wire-boundary and error-path checks for the remaining upstream FFI families."""

import hashlib
import sys
import unittest
from pathlib import Path

import casthon
from casthon import (
    ABIError, AccountHash, URef, ContractHash, ContractPackageHash, PackageHash,
    ContractEntity, DictionaryAddress, EntryPoint, CLU32, U32, U512, CLU512,
    ActionType, Phase, HashAlgorithm, AddKeyFailure, RemoveKeyFailure,
    UpdateKeyFailure, SetThresholdFailure, TransferredTo, EntryPointAccess,
    EntryPointType, EntryPointPayment, MessageTopicOperation,
    Ed25519PublicKey, Ed25519Signature, Secp256k1PublicKey, Secp256k1Signature,
    AccountCaller, EntityCaller, ContractCaller, MessageString, MessageBytes,
)
from casthon.codec import encode, decode, cl_value, valid_payload
from casthon.caller import decode_caller_information, decode_legacy_call_stack
from casthon.entry_points import serialize_entry_points
from casthon.contract_api import account, system, runtime, storage, cryptography
from casthon.testing import use_host
from test_contract_api import MemoryHost

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from bundle import lower_enums


def caller_bytes(kind=0, present=None):
    """Independent CallerInfo encoding: u8 + BTreeMap<u8, CLValue>."""
    present = {0: bytes([17]) * 32} if present is None else present
    data = b"\1\0\0\0" + bytes([kind]) + b"\5\0\0\0"
    for field in range(5):
        payload = b"\0" if field not in present else b"\1" + present[field]
        tag = b"\x0d\x15" if field == 3 else b"\x0d\x0f\x20\0\0\0"
        data += bytes([field]) + len(payload).to_bytes(4, "little") + payload + tag
    return data


class ExtendedHost(MemoryHost):
    def __init__(self):
        super().__init__()
        self.calls = []
        self.statuses = {}
        self.main = URef(bytes([1]) * 32)

    def record(self, name, *args):
        self.calls.append((name, args))

    def get_main_purse(self):
        return bytes(self.main)

    def add_associated_key(self, *args):
        self.record("add_key", *args)
        return self.statuses.get("add", 0)

    def remove_associated_key(self, *args):
        self.record("remove_key", *args)
        return self.statuses.get("remove", 0)

    def update_associated_key(self, *args):
        self.record("update_key", *args)
        return self.statuses.get("update", 0)

    def set_action_threshold(self, *args):
        self.record("threshold", *args)
        return self.statuses.get("threshold", 0)

    def list_authorization_keys(self):
        return b"\1\0\0\0" + bytes(self.owner)[1:]

    def get_phase(self):
        return 2

    def get_blocktime(self):
        return (1234567890123).to_bytes(8, "little")

    def get_block_info(self, field):
        return {1: (1 << 48).to_bytes(8, "little"), 2: b"p" * 32,
                3: b"s" * 32, 5: b"\0"}[field]

    def is_valid_uref(self, value):
        return value == bytes(self.main)

    def load_caller_information(self, action):
        self.record("caller", action)
        return caller_bytes()

    def load_call_stack(self):
        return b"\1\0\0\0\0" + bytes(self.owner)[1:]

    def get_system_contract(self, index):
        return bytes([index + 1]) * 32

    def create_purse(self):
        return bytes(URef(bytes([2]) * 32))

    def get_purse_balance(self, value):
        return encode("U512", (1 << 400) + 7) if value == bytes(self.main) else None

    def transfer_to_account(self, *args):
        self.record("transfer_account", *args)
        return 0

    def transfer_from_purse_to_account(self, *args):
        self.record("transfer_purse_account", *args)
        return 1

    def transfer_from_purse_to_purse(self, *args):
        self.record("transfer_purses", *args)

    def generic_hash(self, data, algorithm):
        self.record("hash", data, algorithm)
        return hashlib.sha256(data).digest() if algorithm == 2 else self.blake2b(data)

    def recover_secp256k1(self, *args):
        self.record("recover", *args)
        return b"\2\2" + b"x" * 32

    def verify_signature(self, *args):
        self.record("verify", *args)

    def random_bytes(self):
        return bytes(range(32))

    def call_versioned_contract(self, *args):
        self.record("versioned", *args)
        return encode("U32", 42)

    def call_package_version(self, *args):
        self.record("package_call", *args)
        return b""

    def create_contract_user_group(self, *args):
        self.record("group", *args)
        return b"\1\0\0\0" + bytes(self.main)[1:]

    def provision_contract_user_group_uref(self, *args):
        self.record("provision", *args)
        return bytes(self.main)[1:]

    def remove_contract_user_group_urefs(self, *args):
        self.record("remove_urefs", *args)

    def remove_contract_user_group(self, *args):
        self.record("remove_group", *args)

    def add_contract_version_legacy(self, *args):
        self.record("legacy_version", *args)
        return bytes(ContractHash(bytes(32))), 2

    def add_package_version(self, *args):
        self.record("package_version", *args)
        return self.statuses.get("package_key", bytes(ContractEntity(bytes(32)))), 3

    def enable_contract_version(self, *args):
        self.record("enable", *args)

    def dictionary_read(self, *args):
        self.record("dictionary_read", *args)
        return encode("U32", 17)

    def manage_message_topic(self, *args):
        self.record("topic", *args)

    def emit_message(self, *args):
        self.record("message", *args)


class ExtendedApiTests(unittest.TestCase):
    def setUp(self):
        self.host = ExtendedHost()
        self.enterContext(use_host(self.host))

    def test_u512_boundaries_and_clvalue_tag(self):
        for value in (0, 1, 256, (1 << 511) + 1, (1 << 512) - 1):
            payload = encode("U512", value)
            self.assertEqual(decode("U512", payload), value)
            self.assertTrue(valid_payload("U512", payload))
            self.assertEqual(CLU512(value).to_bytes(), cl_value("U512", value))
            self.assertEqual(CLU512(value).to_bytes()[-1], 8)
        self.assertEqual(encode("U512", 256), b"\2\0\1")
        for value in (-1, 1 << 512, True):
            with self.assertRaises(ABIError):
                encode("U512", value)
        for data in (b"", b"\x41" + bytes(65), b"\0\0"):
            self.assertFalse(valid_payload("U512", data))
            with self.assertRaises(ABIError):
                decode("U512", data)
        self.assertEqual(casthon.wire_type(U512), "U512")

    def test_account_domain_failures_are_values_and_weights_are_bounded(self):
        self.assertEqual(account.get_main_purse(), self.host.main)
        self.assertIsNone(account.add_associated_key(self.host.owner, 2))
        self.host.statuses = {"add": 2, "remove": 3, "update": 1, "threshold": 4}
        self.assertIs(account.add_associated_key(self.host.owner, 1), AddKeyFailure.DUPLICATE_KEY)
        self.assertIs(account.remove_associated_key(self.host.owner), RemoveKeyFailure.THRESHOLD_VIOLATION)
        self.assertIs(account.update_associated_key(self.host.owner, 1), UpdateKeyFailure.MISSING_KEY)
        self.assertIs(account.set_action_threshold(ActionType.DEPLOYMENT, 2), SetThresholdFailure.INSUFFICIENT_TOTAL_WEIGHT)
        self.assertEqual(self.host.calls[-1], ("threshold", (0, 2)))
        for value in (-1, 256, True):
            with self.assertRaises(ABIError):
                account.add_associated_key(self.host.owner, value)

    def test_context_callers_and_authorization_are_typed(self):
        self.assertEqual(runtime.list_authorization_keys(), {self.host.owner})
        self.assertIs(runtime.get_phase(), Phase.SESSION)
        self.assertEqual(runtime.get_blocktime(), 1234567890123)
        self.assertEqual(runtime.get_block_height(), 1 << 48)
        self.assertEqual(runtime.get_parent_block_hash(), b"p" * 32)
        self.assertEqual(runtime.get_state_hash(), b"s" * 32)
        self.assertFalse(runtime.get_addressable_entity())
        self.assertTrue(runtime.is_valid_uref(self.host.main))
        self.assertFalse(runtime.is_valid_uref(URef(bytes(32))))
        self.assertEqual(runtime.get_call_initiator(), self.host.owner)
        self.assertIsInstance(runtime.get_immediate_caller(), AccountCaller)
        self.assertEqual(runtime.get_call_stack()[0].account_hash, self.host.owner)
        self.assertEqual(runtime.get_legacy_call_stack()[0].account_hash, self.host.owner)

    def test_caller_info_variants_and_malformed_results(self):
        info = decode_caller_information(caller_bytes(4, {2: b"p" * 32, 4: b"c" * 32}))[0]
        self.assertIsInstance(info, ContractCaller)
        self.assertEqual(info.contract_package_hash, ContractPackageHash(b"p" * 32))
        self.assertEqual(info.contract_hash, ContractHash(b"c" * 32))
        info = decode_caller_information(caller_bytes(3, {1: b"p" * 32, 3: b"\2" + b"e" * 32}))[0]
        self.assertIsInstance(info, EntityCaller)
        self.assertEqual(info.package_hash, PackageHash(b"p" * 32))
        self.assertEqual(info.entity, ContractEntity(b"e" * 32))
        for data in (b"", caller_bytes()[:-1], caller_bytes() + b"x", b"\xff" * 4):
            with self.assertRaises(ABIError):
                decode_caller_information(data)
        for data in (b"", b"\1\0\0\0\3" + bytes(32)):
            with self.assertRaises(ABIError):
                decode_legacy_call_stack(data)

    def test_purses_and_transfers_encode_native_urefs_u512_and_optional_ids(self):
        self.assertEqual(system.get_mint(), ContractHash(bytes([1]) * 32))
        self.assertEqual(system.create_purse(), URef(bytes([2]) * 32))
        self.assertEqual(system.get_balance(), (1 << 400) + 7)
        self.assertIsNone(system.get_purse_balance(URef(bytes(32))))
        self.assertIs(system.transfer_to_account(self.host.owner, 256, 1 << 63), TransferredTo.EXISTING_ACCOUNT)
        self.assertEqual(self.host.calls[-1], ("transfer_account", (bytes(self.host.owner), b"\2\0\1", b"\1" + (1 << 63).to_bytes(8, "little"))))
        self.assertIs(system.transfer_from_purse_to_account(self.host.main, self.host.owner, 1), TransferredTo.NEW_ACCOUNT)
        system.transfer_from_purse_to_purse(self.host.main, self.host.main, 7)
        self.assertEqual(self.host.calls[-1][-1][-1], b"\0")

    def test_crypto_types_digests_and_signature_wire_bytes(self):
        key, signature = Ed25519PublicKey(bytes(32)), Ed25519Signature(bytes(64))
        self.assertEqual(casthon.PublicKey.from_bytes(key.to_bytes()), key)
        self.assertEqual(cryptography.generic_hash(b"Casper", HashAlgorithm.SHA256), hashlib.sha256(b"Casper").digest())
        cryptography.verify_signature(b"message", signature, key)
        self.assertEqual(self.host.calls[-1], ("verify", (b"message", b"\1" + bytes(64), b"\1" + bytes(32))))
        recovered = cryptography.recover_secp256k1(b"message", Secp256k1Signature(bytes(64)), 1)
        self.assertIsInstance(recovered, Secp256k1PublicKey)
        self.assertEqual(runtime.random_bytes(), bytes(range(32)))
        with self.assertRaises(ABIError):
            cryptography.recover_secp256k1(b"message", Secp256k1Signature(bytes(64)), 4)

    def test_versioned_calls_encode_both_options_and_decode_returns(self):
        package = ContractPackageHash(bytes(32))
        self.assertEqual(runtime.call_versioned_contract(package, None, "get", {}, U32), 42)
        self.assertEqual(self.host.calls[-1], ("versioned", (bytes(package), b"\0", "get", b"\0" * 4)))
        runtime.call_package_version(package, 2, 3, "increment", {"amount": CLU32(1)})
        args = self.host.calls[-1][1]
        self.assertEqual(args[1:3], (b"\1\2\0\0\0", b"\1\3\0\0\0"))
        self.assertEqual(args[-1], b"\1\0\0\0" + encode("String", "amount") + CLU32(1).to_bytes())

    def test_user_groups_deduplicate_urefs_and_return_typed_capabilities(self):
        package = ContractPackageHash(bytes(32))
        self.assertEqual(storage.create_contract_user_group(package, "admin", 1, [self.host.main, self.host.main]), [self.host.main])
        self.assertEqual(self.host.calls[-1][1][-1], b"\1\0\0\0" + bytes(self.host.main)[1:])
        self.assertEqual(storage.provision_contract_user_group_uref(package, "admin"), self.host.main)
        storage.remove_contract_user_group_urefs(package, "admin", {self.host.main})
        with self.assertRaises(TypeError):
            storage.create_contract_user_group(package, "bad", 0, [self.host.owner])
        storage.remove_contract_user_group(package, "admin")

    def test_restricted_entrypoints_legacy_encoding_and_package_registration(self):
        entry = EntryPoint("get", {}, U32, access=EntryPointAccess.GROUPS, groups=("admin",), payment=EntryPointPayment.CALLER)
        expected = encode("String", "get") + b"\0" * 4 + b"\4\2\1\0\0\0" + encode("String", "admin") + b"\1\0"
        self.assertEqual(entry.to_bytes(), expected)
        self.assertEqual(entry.to_legacy_bytes(), expected[:-1])
        package = ContractPackageHash(bytes(32))
        storage.add_contract_version_legacy(package, [entry], {})
        self.assertEqual(self.host.calls[-1][1][1], serialize_entry_points([entry], legacy=True))
        entity, version = storage.add_package_version(PackageHash(bytes(32)), [entry], {}, {"events": MessageTopicOperation.ADD})
        self.assertIsInstance(entity, ContractEntity)
        self.assertEqual(version, 3)
        self.assertEqual(self.host.calls[-1][1][-1], b"\1\0\0\0" + encode("String", "events") + b"\0")
        self.host.statuses["package_key"] = bytes(ContractHash(bytes(32)))
        contract, _ = storage.add_package_version(PackageHash(bytes(32)), [entry], {})
        self.assertIsInstance(contract, ContractHash)
        storage.enable_contract_version(package, ContractHash(bytes(32)))
        with self.assertRaises(ABIError):
            EntryPoint("factory", {}, entry_point_type=EntryPointType.FACTORY).to_legacy_bytes()

    def test_dictionary_address_reads_and_message_payload_variants(self):
        self.assertEqual(storage.dictionary_read(DictionaryAddress(bytes(32)), U32), 17)
        runtime.manage_message_topic("events")
        self.assertEqual(self.host.calls[-1], ("topic", ("events", b"\0")))
        runtime.emit_message("events", MessageString("hello"))
        self.assertEqual(self.host.calls[-1][1][-1], b"\0" + encode("String", "hello"))
        runtime.emit_message("events", MessageBytes(b"hello"))
        self.assertEqual(self.host.calls[-1][1][-1], b"\1" + encode("Bytes", b"hello"))
        serialized = MessageString("serialized").to_bytes()
        runtime.emit_message("events", serialized)
        self.assertEqual(self.host.calls[-1][1][-1], serialized)

    def test_frozen_enum_protocol_matches_cpython_members(self):
        namespace = {}
        source = Path(__file__).resolve().parents[1] / "src/casthon/enums.py"
        exec(lower_enums(source), namespace)
        for name, frozen in namespace.items():
            original = getattr(casthon, name, None)
            if original is None or name == "WireEnum" or not isinstance(frozen, type):
                continue
            for member in original:
                other = frozen.from_value(int(member))
                self.assertEqual(int(other), int(member))
                self.assertEqual(other.name, member.name)
                self.assertIsInstance(other, frozen)
