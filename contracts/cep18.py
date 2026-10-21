# SPDX-License-Identifier: Apache-2.0
"""Reusable port of CEP-18 2.0.0 (7fa83c559d04b3516e06b4d7202aba912c14c235).

The ABI, error numbers, dictionary layouts and events follow upstream Rust.
Construction creates state; init finishes deployment once, in stored context.
See reference/cep18/LICENSE for the upstream license.
"""

from functools import wraps
from typing import Any, Callable, TypeVar, cast

from cspr import (
    AccountCaller, ContractCaller, EntityCaller,
    Key, U8, URef, U256, Dictionary, OptionalArg, MISSING, MissingArgument, base64,
)
from cspr.contract_api import runtime
from cspr.contract_api.runtime import named_keys
from cspr.contracts import Contract, entry_point
from cspr.enums import WireEnum
from contracts.cep18_errors import (
    AlreadyInitialized, CannotTargetSelfUser, InsufficientAllowance,
    InsufficientBalance, InsufficientRights, InvalidAdminList, InvalidBurnTarget,
    InvalidContext, InvalidMinterList, InvalidNoneList, MintBurnDisabled, Overflow,
    FailedToChangeTotalSupply,
)
from contracts.cep18_events import (
    EventsMode, Mint, Burn, SetAllowance, IncreaseAllowance, DecreaseAllowance,
    Transfer, TransferFrom, ChangeSecurity, ChangeEventsMode, emit, initialize_events,
)

MAX_U256 = (1 << 256) - 1


class SecurityBadge(WireEnum):
    ADMIN = 0
    MINTER = 1
    NONE = 2


def address_key(address: Key) -> str:
    # Upstream uses the complete Key bytes, including the variant tag.
    # Hex would exceed Casper's 64-byte item-key limit for account/hash Keys.
    return base64(bytes(address))


def allowance_key(pair: bytes) -> str:
    return runtime.blake2b(pair).hex()


def immediate_caller() -> Key:
    """CEP-18's account/package/entity identity, not the initiating account."""
    info = runtime.get_immediate_caller()
    key: Key | None = None
    if isinstance(info, AccountCaller):
        key = info.account_hash
    elif isinstance(info, ContractCaller):
        key = info.contract_package_hash
    elif isinstance(info, EntityCaller):
        key = info.entity
    if key is None:
        raise InvalidContext()
    return key


_F = TypeVar("_F", bound=Callable[..., Any])


def require_uninitialized(function: _F) -> _F:
    @wraps(function)
    def guarded(self: "Cep18", *args: Any, **kwargs: Any) -> Any:
        if "package_hash" in named_keys:
            raise AlreadyInitialized()
        return function(self, *args, **kwargs)
    return cast(_F, guarded)


def require_security_admin(function: _F) -> _F:
    @wraps(function)
    def guarded(self: "Cep18", *args: Any, **kwargs: Any) -> Any:
        self._require_mint_burn()
        self._require_badge()
        return function(self, *args, **kwargs)
    return cast(_F, guarded)


class Cep18(Contract):
    events = (Mint, Burn, SetAllowance, IncreaseAllowance, DecreaseAllowance,
              Transfer, TransferFrom, ChangeSecurity, ChangeEventsMode)
    token_name: URef[str] = named_keys.reference("name")
    token_symbol: URef[str] = named_keys.reference("symbol")
    token_decimals: URef[U8] = named_keys.reference("decimals")
    supply: URef[U256] = named_keys.reference("total_supply")
    events_mode: URef[EventsMode]
    enable_mint_burn: URef[U8]
    balances: Dictionary[Key, U256] = named_keys.reference(key=address_key)
    # The compound key is the owner's Key bytes followed by the spender's.
    allowances: Dictionary[bytes, U256] = named_keys.reference(key=allowance_key)
    security_badges: Dictionary[Key, U8] = named_keys.reference(key=address_key)

    def __init__(self, name: str, symbol: str, decimals: U8, total_supply: U256 = 0, *,
                 events_mode: EventsMode = EventsMode.NO_EVENTS, enable_mint_burn: U8 = 0,
                 admin_list: list[Key] | None = None, minter_list: list[Key] | None = None,
                 **state: Any) -> None:
        # Construction runs in the installing session, which has no previous
        # stack frame. Stored methods below use the immediate caller instead.
        caller = runtime.get_caller()
        badges: dict[Key, int] = {caller: int(SecurityBadge.ADMIN)}
        for key in minter_list or []:
            badges[key] = int(SecurityBadge.MINTER)
        for key in admin_list or []:
            badges[key] = int(SecurityBadge.ADMIN)
        super().__init__(token_name=name, token_symbol=symbol, token_decimals=decimals,
                         supply=total_supply, events_mode=events_mode,
                         enable_mint_burn=enable_mint_burn, balances={caller: total_supply},
                         security_badges=badges, **state)

    @entry_point
    @require_uninitialized
    def init(self, package_hash: OptionalArg[Key] = MISSING,
             contract_hash: OptionalArg[Key] = MISSING) -> None:
        if package_hash is MISSING or contract_hash is MISSING:
            raise MissingArgument()
        named_keys["package_hash"] = package_hash
        named_keys["contract_hash"] = contract_hash
        initialize_events(self.event_types())
        emit(Mint(recipient=immediate_caller(), amount=self.supply.read()))

    @entry_point
    def name(self) -> str:
        return self.token_name.read()

    @entry_point
    def symbol(self) -> str:
        return self.token_symbol.read()

    @entry_point
    def decimals(self) -> U8:
        return self.token_decimals.read()

    @entry_point
    def total_supply(self) -> U256:
        return self.supply.read()

    @entry_point
    def balance_of(self, address: Key) -> U256:
        return self.balances.get(address, 0)

    @entry_point
    def allowance(self, owner: Key, spender: Key) -> U256:
        return self.allowances.get(bytes(owner) + bytes(spender), 0)

    @entry_point
    def approve(self, spender: Key, amount: U256) -> None:
        caller = immediate_caller()
        if spender == caller:
            raise CannotTargetSelfUser()
        self.allowances[bytes(caller) + bytes(spender)] = amount
        emit(SetAllowance(owner=caller, spender=spender, allowance=amount))

    @entry_point
    def increase_allowance(self, spender: Key, amount: U256) -> None:
        caller = immediate_caller()
        if spender == caller:
            raise CannotTargetSelfUser()
        pair = bytes(caller) + bytes(spender)
        allowance = min(MAX_U256, self.allowances.get(pair, 0) + amount)
        self.allowances[pair] = allowance
        emit(IncreaseAllowance(owner=caller, spender=spender, allowance=allowance, inc_by=amount))

    @entry_point
    def decrease_allowance(self, spender: Key, amount: U256) -> None:
        caller = immediate_caller()
        if spender == caller:
            raise CannotTargetSelfUser()
        pair = bytes(caller) + bytes(spender)
        allowance = max(0, self.allowances.get(pair, 0) - amount)
        self.allowances[pair] = allowance
        emit(DecreaseAllowance(owner=caller, spender=spender, allowance=allowance, decr_by=amount))

    def _transfer_balance(self, sender: Key, recipient: Key, amount: int) -> None:
        if amount == 0 or sender == recipient:
            return
        balance = self.balances.get(sender, 0) - amount
        if balance < 0:
            raise InsufficientBalance()
        received = self.balances.get(recipient, 0) + amount
        if received > MAX_U256:
            raise Overflow()
        self.balances[sender] = balance
        self.balances[recipient] = received

    @entry_point
    def transfer(self, recipient: Key, amount: U256) -> None:
        caller = immediate_caller()
        if recipient == caller:
            raise CannotTargetSelfUser()
        self._transfer_balance(caller, recipient, amount)
        emit(Transfer(sender=caller, recipient=recipient, amount=amount))

    @entry_point
    def transfer_from(self, owner: Key, recipient: Key, amount: U256) -> None:
        caller = immediate_caller()
        if owner == recipient:
            raise CannotTargetSelfUser()
        if amount == 0:
            return
        pair = bytes(owner) + bytes(caller)
        allowance = self.allowances.get(pair, 0) - amount
        if allowance < 0:
            raise InsufficientAllowance()
        self._transfer_balance(owner, recipient, amount)
        self.allowances[pair] = allowance
        emit(TransferFrom(spender=caller, owner=owner, recipient=recipient, amount=amount))

    def _require_mint_burn(self) -> None:
        # Upstream enables this for every nonzero U8, not only 1.
        if self.enable_mint_burn.read() == 0:
            raise MintBurnDisabled()

    def _require_badge(self, allow_minter: bool = False) -> None:
        badge = self.security_badges.get(immediate_caller())
        if badge != int(SecurityBadge.ADMIN) and not (allow_minter and badge == int(SecurityBadge.MINTER)):
            raise InsufficientRights()

    @entry_point
    def mint(self, owner: Key, amount: U256) -> None:
        self._require_mint_burn()
        self._require_badge(allow_minter=True)
        balance = self.balances.get(owner, 0) + amount
        supply = self.supply.read() + amount
        if balance > MAX_U256 or supply > MAX_U256:
            raise Overflow()
        self.balances[owner] = balance
        self.supply.write(supply)
        emit(Mint(recipient=owner, amount=amount))

    @entry_point
    def burn(self, owner: Key, amount: U256) -> None:
        self._require_mint_burn()
        if owner != immediate_caller():
            raise InvalidBurnTarget()
        balance = self.balances.get(owner, 0) - amount
        if balance < 0:
            raise InsufficientBalance()
        supply = self.supply.read() - amount
        if supply < 0:
            raise FailedToChangeTotalSupply()
        self.balances[owner] = balance
        self.supply.write(supply)
        emit(Burn(owner=owner, amount=amount))

    @entry_point
    @require_security_admin
    def change_security(self, *,
                        admin_list: OptionalArg[list[Key]] = MISSING,
                        minter_list: OptionalArg[list[Key]] = MISSING,
                        none_list: OptionalArg[list[Key]] = MISSING) -> None:
        if admin_list is MISSING:
            raise InvalidAdminList()
        if minter_list is MISSING:
            raise InvalidMinterList()
        if none_list is MISSING:
            raise InvalidNoneList()
        changes = {}
        for keys, badge in ((minter_list, SecurityBadge.MINTER), (admin_list, SecurityBadge.ADMIN), (none_list, SecurityBadge.NONE)):
            for key in keys:
                changes[key] = int(badge)
        caller = immediate_caller()
        changes.pop(caller, None)
        for key, value in sorted(changes.items()):
            self.security_badges[key] = value
        emit(ChangeSecurity(admin=caller, sec_change_map=changes))

    @entry_point
    def change_events_mode(self, events_mode: EventsMode) -> None:
        self._require_badge()
        old = self.events_mode.read()
        if events_mode is old:
            return
        self.events_mode.write(events_mode)
        initialize_events(self.event_types())
        emit(ChangeEventsMode(events_mode=events_mode))
