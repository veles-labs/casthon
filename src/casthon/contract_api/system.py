"""System contracts, purses and CSPR transfers, matching contract_api/system.rs."""

from .._ffi import call as _call
from ..errors import InvalidPurse
from ..codec import encode, decode
from ..key import AccountHash, ContractHash, URef
from ..crypto import PublicKey
from ..enums import SystemEntityType, TransferredTo
from ..types import U512, U64
from . import account, runtime


def get_system_contract(contract: SystemEntityType) -> ContractHash:
    index = SystemEntityType.from_value(int(contract))
    return ContractHash(_call('get_system_contract', int(index)))


def get_mint() -> ContractHash:
    return get_system_contract(SystemEntityType.MINT)


def get_handle_payment() -> ContractHash:
    return get_system_contract(SystemEntityType.HANDLE_PAYMENT)


def get_standard_payment() -> ContractHash:
    return get_system_contract(SystemEntityType.STANDARD_PAYMENT)


def get_auction() -> ContractHash:
    return get_system_contract(SystemEntityType.AUCTION)


def create_purse() -> URef:
    return URef(_call('create_purse'))


def get_purse_balance(purse: URef) -> U512 | None:
    try:
        data = _call('get_purse_balance', bytes(purse))
    except InvalidPurse:
        return None
    return None if data is None else decode("U512", data)


def get_balance() -> U512 | None:
    return get_purse_balance(account.get_main_purse())


def _transfer_id(value: U64 | None) -> bytes:
    return b"\0" if value is None else b"\1" + encode("U64", value)


def transfer_to_account(target: AccountHash, amount: U512, transfer_id: U64 | None = None) -> TransferredTo:
    result = _call('transfer_to_account', bytes(target), encode("U512", amount), _transfer_id(transfer_id))
    return TransferredTo.from_value(result)


def transfer_from_purse_to_account(source: URef, target: AccountHash, amount: U512,
                                 transfer_id: U64 | None = None) -> TransferredTo:
    result = _call('transfer_from_purse_to_account', bytes(source), bytes(target),
                                                   encode("U512", amount), _transfer_id(transfer_id))
    return TransferredTo.from_value(result)


def transfer_from_purse_to_purse(source: URef, target: URef, amount: U512,
                               transfer_id: U64 | None = None) -> None:
    _call('transfer_from_purse_to_purse', bytes(source), bytes(target), encode("U512", amount), _transfer_id(transfer_id))


def transfer_to_public_key(target: PublicKey, amount: U512, transfer_id: U64 | None = None) -> TransferredTo:
    return transfer_to_account(AccountHash(runtime.blake2b(target.account_hash_preimage)), amount, transfer_id)


def transfer_from_purse_to_public_key(source: URef, target: PublicKey, amount: U512,
                                    transfer_id: U64 | None = None) -> TransferredTo:
    return transfer_from_purse_to_account(source, AccountHash(runtime.blake2b(target.account_hash_preimage)), amount, transfer_id)
