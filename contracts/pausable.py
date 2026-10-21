"""Reusable owner-authorized pause controls and a local pause guard."""

from typing import Any

from cspr import URef, UserError
from cspr.contracts import entry_point
from contracts.ownable import Ownable


class Paused(UserError):
    def __init__(self) -> None:
        super().__init__(101)


class Pausable(Ownable):
    paused: URef[bool]

    def __init__(self, *, paused: bool = False, **state: Any) -> None:
        super().__init__(paused=paused, **state)

    def _require_unpaused(self) -> None:
        if self.paused.read():
            raise Paused()

    @entry_point
    def pause(self) -> None:
        self._require_owner()
        self.paused.write(True)

    @entry_point
    def unpause(self) -> None:
        self._require_owner()
        self.paused.write(False)

    @entry_point
    def is_paused(self) -> bool:
        return self.paused.read()
