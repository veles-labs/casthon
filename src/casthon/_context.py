"""CPython host binding; frozen code calls the Casper host module directly."""

from contextvars import ContextVar
from typing import Any

_HOST: ContextVar[Any] = ContextVar("cspr_host")


def _host() -> Any:
    try:
        return _HOST.get()
    except LookupError:
        raise RuntimeError(
            "Use casthon.testing.use_host() when running contracts under CPython"
        ) from None
