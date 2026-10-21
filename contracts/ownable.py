"""Reusable ownership state and owner-authorized entrypoints."""

from typing import Any

from cspr import AccountHash, URef, UserError
from cspr.contract_api.runtime import get_caller
from cspr.contracts import Contract, entry_point


class NotOwner(UserError):
    def __init__(self) -> None:
        super().__init__(100)


class Ownable(Contract):
    owner: URef[AccountHash]

    def __init__(self, *, owner: AccountHash | None = None, **state: Any) -> None:
        super().__init__(owner=get_caller() if owner is None else owner, **state)

    def _require_owner(self) -> None:
        if get_caller() != self.owner.read():
            raise NotOwner()

    @entry_point
    def get_owner(self) -> AccountHash:
        return self.owner.read()

    @entry_point
    def transfer_ownership(self, new_owner: AccountHash) -> None:
        self._require_owner()
        self.owner.write(new_owner)
