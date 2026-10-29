"""CPython test helpers. No testing code is frozen into contract Wasm."""

from contextlib import contextmanager
from typing import Any, Iterator, TYPE_CHECKING

from .._context import _HOST
from ..errors import ApiError


class _FixtureTransport:
    def __init__(self, host: Any) -> None:
        self.host = host

    def __getattr__(self, name: str) -> Any:
        method = getattr(self.host, name)

        def invoke(*args: Any) -> tuple[int, Any]:
            try:
                return 0, method(*args)
            except ApiError as error:
                return error.code, None

        return invoke


@contextmanager
def use_host(host: Any, *, raw: bool = False) -> Iterator[None]:
    """Bind a scoped host; raw transports return (status, value) themselves."""
    token = _HOST.set(host if raw else _FixtureTransport(host))
    try:
        yield
    finally:
        _HOST.reset(token)


from .mock import MockHost as MockHost
from .contract import ContractHarness as ContractHarness, InvocationResult as InvocationResult
from .mock import MockAccessError as MockAccessError, UnsupportedHostCall as UnsupportedHostCall
if TYPE_CHECKING:
    from .build import build_contract as build_contract
    from .devnet import (
        DevnetClient as DevnetClient, DevnetNetwork as DevnetNetwork, DevnetError as DevnetError,
        TestAccount as TestAccount, TransactionReceipt as TransactionReceipt, QueryResult as QueryResult,
    )
    from .live import LiveNetworkTest as LiveNetworkTest
    from .simulation import SimulationResult as SimulationResult
    from .prints import ContractPrint as ContractPrint


__all__ = ["use_host", "MockHost", "MockAccessError", "UnsupportedHostCall", "ContractHarness", "InvocationResult",
           "build_contract", "DevnetClient", "DevnetNetwork", "DevnetError", "TestAccount",
           "TransactionReceipt", "QueryResult", "LiveNetworkTest", "ContractPrint", "SimulationResult"]


def __getattr__(name: str) -> Any:
    # Native state tests do not import subprocess/network/build dependencies.
    import importlib
    modules = {"build_contract": "build", "LiveNetworkTest": "live", "ContractPrint": "prints", "SimulationResult": "simulation",
               **{item: "devnet" for item in ("DevnetClient", "DevnetNetwork", "DevnetError",
                                               "TestAccount", "TransactionReceipt", "QueryResult")}}
    if name not in modules:
        raise AttributeError(name)
    value = getattr(importlib.import_module(__name__ + "." + modules[name]), name)
    globals()[name] = value
    return value
