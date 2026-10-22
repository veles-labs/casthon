"""Account purse and key-management operations, matching contract_api/account.rs."""

from typing import cast
from .._ffi import call as _call
from ..codec import encode
from ..key import AccountHash, URef
from ..enums import ActionType, AddKeyFailure, RemoveKeyFailure, UpdateKeyFailure, SetThresholdFailure


def get_main_purse() -> URef:
    return URef(_call('get_main_purse'))


def add_associated_key(account_hash: AccountHash, weight: int) -> AddKeyFailure | None:
    encode("U8", weight)
    status = cast(int, _call('add_associated_key', bytes(account_hash), weight))
    return None if status == 0 else AddKeyFailure.from_value(status)


def remove_associated_key(account_hash: AccountHash) -> RemoveKeyFailure | None:
    status = cast(int, _call('remove_associated_key', bytes(account_hash)))
    return None if status == 0 else RemoveKeyFailure.from_value(status)


def update_associated_key(account_hash: AccountHash, weight: int) -> UpdateKeyFailure | None:
    encode("U8", weight)
    status = cast(int, _call('update_associated_key', bytes(account_hash), weight))
    return None if status == 0 else UpdateKeyFailure.from_value(status)


def set_action_threshold(action_type: ActionType, threshold: int) -> SetThresholdFailure | None:
    encode("U8", threshold)
    action = ActionType.from_value(int(action_type))
    status = cast(int, _call('set_action_threshold', int(action), threshold))
    return None if status == 0 else SetThresholdFailure.from_value(status)
