"""Reusable owner-authorized pause controls and an entrypoint pause guard."""

from functools import wraps
from typing import Any, Callable, TypeVar, cast

from cspr import URef, UserError
from cspr.contracts import entry_point
from contracts.ownable import Ownable, require_owner


class Paused(UserError):
    def __init__(self) -> None:
        super().__init__(101)


_F = TypeVar("_F", bound=Callable[..., Any])


def require_unpaused(function: _F) -> _F:
    @wraps(function)
    def guarded(self: "Pausable", *args: Any, **kwargs: Any) -> Any:
        self._require_unpaused()
        return function(self, *args, **kwargs)
    return cast(_F, guarded)


class Pausable(Ownable):
    paused: URef[bool]

    def __init__(self, *, paused: bool = False, **state: Any) -> None:
        super().__init__(paused=paused, **state)

    def _require_unpaused(self) -> None:
        if self.paused.read():
            raise Paused()

    @entry_point
    @require_owner
    def pause(self) -> None:
        self.paused.write(True)

    @entry_point
    @require_owner
    def unpause(self) -> None:
        self.paused.write(False)

    @entry_point
    def is_paused(self) -> bool:
        return self.paused.read()
