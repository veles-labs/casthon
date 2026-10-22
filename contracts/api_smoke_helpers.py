"""A reusable procedural entrypoint imported by the host-API test session."""

from casthon import EntryPoint, U32, U256, URef, CLU32, api_error
from casthon.contract_api import runtime, storage

ENTRY_POINTS = [EntryPoint("read_count", {}, U32)]


def read_count() -> None:
    key = runtime.get_key("api_smoke_count")
    if not isinstance(key, URef):
        runtime.revert(api_error.INVALID_ARGUMENT)
    runtime.ret(CLU32(storage.read_or_revert(key, U256)))
