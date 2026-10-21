"""Procedural devnet probes for the remaining ext_ffi function families."""

from cspr import (
    EntryPoint, EntryPointAccess, U8, U32, U64, U512,
    CLU32, CLU64, CLU512, CLBool, CLBytes, AccountHash, URef,
    ContractPackageHash, ContractHash, ContractEntity, PackageHash, DictionaryAddress,
    AccountCaller, Phase, ActionType, AddKeyFailure, UpdateKeyFailure, RemoveKeyFailure,
    TransferredTo, HashAlgorithm, MessageString, MessageBytes,
    Ed25519PublicKey, Ed25519Signature, Secp256k1PublicKey, Secp256k1Signature,
    api_error, export,
)
from cspr.contract_api import runtime, storage, account, system, cryptography

ENTRY_POINTS = [
    EntryPoint("ping", {}, U32),
    EntryPoint("restricted", {}, U32, access=EntryPointAccess.GROUPS, groups=("admin",)),
    EntryPoint("inspect_caller", {}, U32),
    EntryPoint("emit_events", {}, U32),
]


def _assert(condition: bool) -> None:
    if not condition:
        runtime.revert(api_error.user(500))


def _save(name: str, value: bool) -> None:
    runtime.put_key("ffi_" + name + "_ok", storage.new_uref(CLBool(value)))


@export
def ping() -> None:
    runtime.ret(CLU32(7))


@export
def restricted() -> None:
    runtime.ret(CLU32(42))


@export
def inspect_caller() -> None:
    caller = runtime.get_caller()
    _assert(runtime.get_call_initiator() == caller)
    immediate = runtime.get_immediate_caller()
    _assert(isinstance(immediate, AccountCaller) and immediate.account_hash == caller)
    _assert(len(runtime.get_call_stack()) >= 2)
    _assert(runtime.get_legacy_call_stack()[0].account_hash == caller)
    runtime.ret(CLU32(1))


def context() -> None:
    caller = runtime.get_caller()
    _assert(caller in runtime.list_authorization_keys())
    _assert(runtime.get_phase() == Phase.SESSION)
    _assert(runtime.get_blocktime() > 0)
    _assert(runtime.get_block_height() > 0)
    _assert(len(runtime.get_parent_block_hash()) == 32)
    _assert(len(runtime.get_state_hash()) == 32)
    _assert(runtime.get_call_initiator() == caller)
    package, access = storage.create_contract_package_at_hash()
    contract, version = storage.add_contract_version(package, [ENTRY_POINTS[2]], {})
    _assert(runtime.call_contract(contract, "inspect_caller", {}, U32) == 1)
    purse = account.get_main_purse()
    _assert(runtime.is_valid_uref(purse))
    _assert(system.get_balance() is not None)
    for contract in (system.get_mint(), system.get_handle_payment(), system.get_auction()):
        _assert(isinstance(contract, ContractHash))
    _assert(len(runtime.random_bytes()) == 32)
    runtime.put_key("ffi_entity_enabled", storage.new_uref(CLBool(runtime.get_addressable_entity())))
    runtime.put_key("ffi_block_height", storage.new_uref(CLU64(runtime.get_block_height())))
    _save("context", True)


def keys() -> None:
    extra = AccountHash(bytes([68]) * 32)
    _assert(account.add_associated_key(extra, 1) is None)
    _assert(account.add_associated_key(extra, 1) == AddKeyFailure.DUPLICATE_KEY)
    _assert(account.update_associated_key(extra, 2) is None)
    _assert(account.set_action_threshold(ActionType.DEPLOYMENT, 1) is None)
    _assert(account.set_action_threshold(ActionType.KEY_MANAGEMENT, 1) is None)
    _assert(account.remove_associated_key(extra) is None)
    _assert(account.remove_associated_key(extra) == RemoveKeyFailure.MISSING_KEY)
    _assert(account.update_associated_key(extra, 1) == UpdateKeyFailure.MISSING_KEY)
    _save("keys", True)


def funds() -> None:
    source = account.get_main_purse()
    first, second = system.create_purse(), system.create_purse()
    _assert(system.get_purse_balance(first) == 0)
    system.transfer_from_purse_to_purse(source, first, 20_000_000_000, 11)
    system.transfer_from_purse_to_purse(first, second, 10_000_000_000)
    target = AccountHash(bytes([66]) * 32)
    _assert(system.transfer_from_purse_to_account(first, target, 5_000_000_000, 12) == TransferredTo.NEW_ACCOUNT)
    _assert(system.transfer_to_account(target, 3_000_000_000, 13) == TransferredTo.EXISTING_ACCOUNT)
    _assert(system.get_purse_balance(first) == 5_000_000_000)
    _assert(system.get_purse_balance(second) == 10_000_000_000)
    runtime.put_key("ffi_first_purse", first)
    runtime.put_key("ffi_second_purse", second)
    _save("funds", True)


def groups() -> None:
    package, access = storage.create_contract_package_at_hash()
    members = storage.create_contract_user_group(package, "admin", 1)
    _assert(len(members) == 1 and isinstance(members[0], URef))
    extra = storage.provision_contract_user_group_uref(package, "admin")
    contract, version = storage.add_contract_version(package, ENTRY_POINTS, {})
    _assert(runtime.call_contract(contract, "restricted", {}, U32) == 42)
    storage.remove_contract_user_group_urefs(package, "admin", [extra])
    storage.create_contract_user_group(package, "temporary", 0)
    storage.remove_contract_user_group(package, "temporary")
    runtime.put_key("ffi_group_package", package)
    runtime.put_key("ffi_group_access", access)
    runtime.put_key("ffi_group_contract", contract)
    _save("groups", True)


def versions_legacy() -> None:
    package, access = storage.create_contract_package_at_hash()
    first, version = storage.add_contract_version_legacy(package, [ENTRY_POINTS[0]], {})
    _assert(version == 1)
    _assert(runtime.call_versioned_contract(package, None, "ping", {}, U32) == 7)
    storage.disable_contract_version(package, first)
    storage.enable_contract_version(package, first)
    _assert(runtime.call_versioned_contract(package, 1, "ping", {}, U32) == 7)
    runtime.put_key("ffi_version_package", package)
    runtime.put_key("ffi_version_access", access)
    runtime.put_key("ffi_version_first", first)
    _save("versions_legacy", True)


def versions() -> None:
    package_key = runtime.get_key("ffi_version_package")
    if package_key is None:
        runtime.revert(api_error.MISSING_KEY)
    package = ContractPackageHash(bytes(package_key)[1:])
    second, version = storage.add_package_version(PackageHash(bytes(package)[1:]), [ENTRY_POINTS[0]], {})
    _assert(version == 2)
    _assert(isinstance(second, ContractEntity if runtime.get_addressable_entity() else ContractHash))
    _assert(runtime.call_package_version(package, None, None, "ping", {}, U32) == 7)
    _assert(runtime.call_package_version(package, 2, 1, "ping", {}, U32) == 7)
    runtime.put_key("ffi_version_second", second)
    _save("versions", True)


def dictionaries() -> None:
    seed = storage.new_dictionary("ffi_dictionary")
    storage.dictionary_put(seed, "answer", CLU512((1 << 400) + 7))
    address = runtime.blake2b(seed.address + b"answer")
    key = DictionaryAddress(address)
    _assert(storage.dictionary_read(key, U512) == (1 << 400) + 7)
    missing = DictionaryAddress(runtime.blake2b(seed.address + b"missing"))
    _assert(storage.dictionary_read(missing, U512) is None)
    _save("dictionaries", True)


def unexported() -> None:
    runtime.ret(CLU32(99))


def missing_export() -> None:
    package, access = storage.create_contract_package_at_hash()
    storage.add_contract_version(package, [EntryPoint("unexported", {}, U32)], {})


def crypto() -> None:
    message = b"Casper"
    for algorithm in (HashAlgorithm.BLAKE2B, HashAlgorithm.BLAKE3, HashAlgorithm.SHA256):
        digest = cryptography.generic_hash(message, algorithm)
        _assert(len(digest) == 32)
        runtime.put_key("ffi_hash_" + str(int(algorithm)), storage.new_uref(CLBytes(digest)))
    public = Ed25519PublicKey(bytes.fromhex("d75a980182b10ab7d54bfed3c964073a0ee172f3daa62325af021a68f707511a"))
    signature = Ed25519Signature(bytes.fromhex("e5564300c360ac729086e2cc806e828a84877f1eb8e5d974d873e06522490155"
                                             "5fb8821590a33bacc61e39701cf9b46bd25bf5f0595bbe24655141438e7a100b"))
    cryptography.verify_signature(b"", signature, public)
    raw_signature = bytes.fromhex(runtime.get_named_arg("signature", str))
    raw_public = bytes.fromhex(runtime.get_named_arg("public_key", str))
    secp_signature, secp_public = Secp256k1Signature(raw_signature), Secp256k1PublicKey(raw_public)
    cryptography.verify_signature(message, secp_signature, secp_public)
    matched = False
    for recovery_id in (0, 1):
        recovered = cryptography.recover_secp256k1(message, secp_signature, recovery_id)
        if recovered == secp_public:
            matched = True
    _assert(matched)
    _save("crypto", True)


def crypto_bad() -> None:
    public = Ed25519PublicKey(bytes.fromhex("d75a980182b10ab7d54bfed3c964073a0ee172f3daa62325af021a68f707511a"))
    signature = Ed25519Signature(bytes.fromhex("e5564300c360ac729086e2cc806e828a84877f1eb8e5d974d873e06522490155"
                                             "5fb8821590a33bacc61e39701cf9b46bd25bf5f0595bbe24655141438e7a100b"))
    cryptography.verify_signature(b"wrong message", signature, public)


@export
def emit_events() -> None:
    runtime.manage_message_topic("ffi_events")
    runtime.emit_message("ffi_events", MessageString("hello"))
    runtime.emit_message("ffi_events", MessageBytes(b"hello"))
    runtime.ret(CLU32(1))


def messages() -> None:
    contract = runtime.get_key("ffi_group_contract")
    if contract is None:
        runtime.revert(api_error.MISSING_KEY)
    _assert(runtime.call_contract(contract, "emit_events", {}, U32) == 1)
    _save("messages", True)


@export
def call() -> None:
    operation = runtime.get_named_arg("operation", str)
    if operation == "context":
        context()
    elif operation == "keys":
        keys()
    elif operation == "funds":
        funds()
    elif operation == "groups":
        groups()
    elif operation == "versions_legacy":
        versions_legacy()
    elif operation == "versions":
        versions()
    elif operation == "dictionaries":
        dictionaries()
    elif operation == "missing_export":
        missing_export()
    elif operation == "crypto":
        crypto()
    elif operation == "crypto_bad":
        crypto_bad()
    elif operation == "messages":
        messages()
    elif operation == "standard_payment":
        system.get_standard_payment()
    else:
        runtime.revert(api_error.INVALID_ARGUMENT)
    runtime.ret(CLU32(1))
