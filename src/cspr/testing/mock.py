"""Small stateful host for native tests; unsupported engine features fail loudly."""

from contextlib import contextmanager
from contextvars import ContextVar
from copy import deepcopy
from dataclasses import dataclass, field
from hashlib import blake2b
from types import ModuleType
from typing import Any, Iterator, Mapping, NoReturn

from ..bytesrepr import Reader
from ..contracts import Contract
from ..codec import encode
from ..entry_points import EntryPoint
from ..enums import EntryPointAccess, EntryPointType, EntryPointPayment, Phase
from ..errors import ABIError, ApiError, InvalidArgument, MissingArgument, MissingKey, Revert, ValueNotFound
from ..key import AccountHash, ContractHash, ContractPackageHash, DictionaryAddress, Key, URef
from ..return_value import validate_return_payload
from .values import inspect_value, read_kind


class MockAccessError(BaseException):
    """An unknown URef or insufficient capability in the simulated context."""


class UnsupportedHostCall(BaseException):
    """Missing mock functionality must not be swallowed by contract except Exception."""


@dataclass
class _Context:
    scope: Key
    caller: AccountHash
    args: dict[str, bytes] = field(default_factory=dict)
    grants: dict[bytes, int] = field(default_factory=dict)
    module: ModuleType | type[Contract] | None = None
    stack: tuple[Key, ...] = ()


class MockHost:
    def __init__(self, *, caller: AccountHash | None = None, block_time: int = 0,
                 protocol_version: tuple[int, int, int] = (2, 2, 0),
                 strict_arguments: bool = False) -> None:
        caller = caller or AccountHash(bytes([17]) * 32)
        self.accounts: dict[Key, dict[str, Key]] = {}
        self.contracts: dict[Key, dict[str, Key]] = {}
        self.cells: dict[bytes, bytes] = {}
        self.dictionaries: dict[bytes, dict[str, bytes]] = {}
        self.global_values: dict[bytes, bytes] = {}
        self.packages: dict[bytes, list[ContractHash]] = {}
        self.entry_points: dict[Key, dict[str, EntryPoint]] = {}
        self.contract_modules: dict[Key, ModuleType | type[Contract]] = {}
        self.disabled: set[Key] = set()
        self.message_topics: dict[Key, set[str]] = {}
        self.messages: list[tuple[Key, str, bytes]] = []
        self.calls: list[tuple[str, tuple[Any, ...]]] = []
        self._failures: dict[str, list[BaseException]] = {}
        self._next = 1
        self._transaction_depth = 0
        self._contract_revert: Revert | None = None
        self.block_time, self.protocol_version = block_time, protocol_version
        self.strict_arguments = strict_arguments
        self.phase = Phase.SESSION
        self._current: ContextVar[_Context] = ContextVar("mock_host_context", default=_Context(caller, caller))

    def __getattr__(self, name: str) -> Any:
        raise UnsupportedHostCall(f"MockHost.{name} is unsupported; use a Wasm or live test")

    @property
    def caller(self) -> AccountHash:
        return self._current.get().caller

    @property
    def args(self) -> dict[str, bytes]:
        return self._current.get().args

    @property
    def named_keys(self) -> dict[str, Key]:
        scope = self._current.get().scope
        namespaces = self.accounts if isinstance(scope, AccountHash) else self.contracts
        return namespaces.setdefault(scope, {})

    @contextmanager
    def context(self, *, account: AccountHash | None = None, contract: Key | None = None,
                caller: AccountHash | None = None, args: Mapping[str, bytes] | None = None,
                module: ModuleType | type[Contract] | None = None) -> Iterator["MockHost"]:
        if account is not None and contract is not None:
            raise ValueError("Choose an account or a contract context")
        current = self._current.get()
        scope = contract if contract is not None else account if account is not None else current.scope
        initiator = caller or current.caller
        if contract is not None:
            stack = ((initiator,) if isinstance(current.scope, AccountHash)
                     else current.stack or (initiator, current.scope)) + (contract,)
        else:
            stack = (scope,) if account is not None else current.stack or (scope,)
        context = _Context(scope, initiator, dict(args or {}), module=module, stack=stack)
        namespaces = self.accounts if isinstance(scope, AccountHash) else self.contracts
        # Removing/replacing a named key does not revoke a capability already
        # available to this invocation. The next context starts with fresh grants.
        for key in namespaces.get(scope, {}).values():
            if isinstance(key, URef):
                context.grants[key.address] = context.grants.get(key.address, 0) | key.access_rights
        token = self._current.set(context)
        try:
            yield self
        finally:
            self._current.reset(token)

    @contextmanager
    def transaction(self) -> Iterator[None]:
        names = ("accounts", "contracts", "cells", "dictionaries", "global_values", "packages",
                 "entry_points", "disabled", "message_topics", "messages", "_next")
        snapshot = deepcopy({name: getattr(self, name) for name in names})
        modules = self.contract_modules.copy()
        grants = self._current.get().grants.copy()
        self._transaction_depth += 1
        try:
            yield
            if self._contract_revert is not None:
                raise self._contract_revert
        except BaseException:
            for name, value in snapshot.items():
                setattr(self, name, value)
            self.contract_modules = modules
            self._current.get().grants.clear()
            self._current.get().grants.update(grants)
            raise
        finally:
            self._transaction_depth -= 1
            if self._transaction_depth == 0:
                self._contract_revert = None

    def fail_next(self, operation: str, error: BaseException) -> None:
        self._failures.setdefault(operation, []).append(error)

    def _call(self, name: str, *args: Any) -> None:
        self.calls.append((name, args))
        failures = self._failures.get(name)
        if failures:
            raise failures.pop(0)

    def _address(self, domain: bytes) -> bytes:
        result = blake2b(domain + self._next.to_bytes(8, "little"), digest_size=32).digest()
        self._next += 1
        return result

    def grant(self, key: URef) -> None:
        """Explicitly make an allocated capability available to the active context."""
        if key.address not in self.cells:
            raise MockAccessError("Cannot grant an unknown URef")
        grants = self._current.get().grants
        grants[key.address] = grants.get(key.address, 0) | key.access_rights

    def _uref(self, data: bytes, right: int) -> URef:
        key = URef(data)
        allowed = self._current.get().grants.get(key.address, 0)
        for value in self.named_keys.values():
            if isinstance(value, URef) and value.address == key.address:
                allowed |= value.access_rights
        if key.access_rights & ~allowed or right and not key.access_rights & right:
            raise MockAccessError("URef is unknown to this context or lacks access rights")
        return key

    def get_key(self, name: str) -> bytes:
        self._call("get_key", name)
        if name not in self.named_keys:
            raise MissingKey()
        return bytes(self.named_keys[name])

    def has_key(self, name: str) -> bool:
        self._call("has_key", name)
        return name in self.named_keys

    def put_key(self, name: str, key: bytes) -> None:
        self._call("put_key", name, key)
        value = Key.from_bytes(key)
        if isinstance(value, URef):
            self._uref(key, 0)
        self.named_keys[name] = value

    def remove_key(self, name: str) -> None:
        self._call("remove_key", name)
        self.named_keys.pop(name, None)

    def list_named_keys(self) -> bytes:
        self._call("list_named_keys")
        return encode("U32", len(self.named_keys)) + b"".join(
            encode("String", name) + bytes(key) for name, key in sorted(self.named_keys.items()))

    def get_caller(self) -> bytes:
        self._call("get_caller")
        return bytes(self.caller)[1:]

    def load_caller_information(self, action: int) -> bytes:
        self._call("load_caller_information", action)
        context = self._current.get()
        stack = context.stack or (context.caller,)
        if action == 1 and len(stack) < 2:
            raise ApiError(31)  # Casper has no previous frame in session code.
        callers = {0: (context.caller,), 1: (stack[-2] if len(stack) > 1 else stack[0],), 2: stack}.get(action)
        if callers is None:
            raise InvalidArgument()
        data = encode("U32", len(callers))
        from ..codec import cl_value
        for caller in callers:
            fields: list[bytes | None] = [None] * 5
            if isinstance(caller, AccountHash):
                kind, fields[0] = 0, bytes(caller)[1:]
            else:
                package = next((key for key, versions in self.packages.items() if caller in versions), None)
                if package is None:
                    raise UnsupportedHostCall("Caller contract has no registered package")
                kind, fields[2], fields[4] = 4, package[1:], bytes(caller)[1:]
            data += bytes([kind]) + encode("U32", 5)
            for index, value in enumerate(fields):
                payload = b"\0" if value is None else b"\1" + value
                # CallerInfo fields 0,1,2,4 are Option<ByteArray(32)>;
                # field 3 is Option<Any> holding an EntityAddr.
                field_type = b"\x0d\x15" if index == 3 else b"\x0d\x0f\x20\0\0\0"
                data += bytes([index]) + encode("U32", len(payload)) + payload + field_type
        return data

    def emit_message(self, topic: str, payload: bytes) -> None:
        self._call("emit_message", topic, payload)
        scope = self._current.get().scope
        if topic not in self.message_topics.get(scope, set()):
            raise InvalidArgument()
        reader = Reader(payload)
        if reader.u8() not in (0, 1):
            raise InvalidArgument()
        reader.take(reader.u32())
        reader.finish()
        self.messages.append((scope, topic, payload))

    def get_named_arg(self, name: str) -> bytes:
        self._call("get_named_arg", name)
        if name not in self.args:
            raise MissingArgument()
        return self.args[name]

    def get_protocol_version(self) -> tuple[int, int, int]:
        self._call("get_protocol_version")
        return self.protocol_version

    def get_blocktime(self) -> bytes:
        self._call("get_blocktime")
        return encode("U64", self.block_time)

    def get_phase(self) -> int:
        self._call("get_phase")
        return int(self.phase)

    def blake2b(self, data: bytes) -> bytes:
        self._call("blake2b", data)
        return blake2b(data, digest_size=32).digest()

    def new_uref(self, value: bytes) -> bytes:
        self._call("new_uref", value)
        validate_return_payload(value)
        key = URef(self._address(b"uref"))
        self.cells[key.address] = value
        self.grant(key)
        return bytes(key)

    def read_value(self, data: bytes) -> bytes:
        self._call("read_value", data)
        key = Key.from_bytes(data)
        if isinstance(key, URef):
            key = self._uref(data, 1)
            value = self.cells.get(key.address)
        else:
            value = self.global_values.get(data)
        if value is None:
            raise ValueNotFound()
        return value[4:4 + int.from_bytes(value[:4], "little")]

    def write(self, key: bytes, value: bytes) -> None:
        self._call("write", key, value)
        uref = self._uref(key, 2)
        validate_return_payload(value)
        self.cells[uref.address] = value

    def add(self, key: bytes, value: bytes) -> None:
        self._call("add", key, value)
        uref = self._uref(key, 4)
        kind, amount = inspect_value(value)
        current_kind, current = inspect_value(self.cells[uref.address])
        if kind != current_kind or kind not in ("U64", "U256", "U512"):
            raise InvalidArgument()
        from ..codec import cl_value
        self.cells[uref.address] = cl_value(kind, current + amount)

    def new_dictionary(self) -> bytes:
        self._call("new_dictionary")
        from ..codec import cl_value
        key = URef(self.new_uref(cl_value("Unit", None)))
        self.dictionaries[key.address] = {}
        return bytes(key)

    def dictionary_get(self, seed: bytes, item: str) -> bytes:
        self._call("dictionary_get", seed, item)
        key = self._uref(seed, 1)
        try:
            value = self.dictionaries[key.address][item]
        except KeyError:
            raise ValueNotFound() from None
        return value[4:4 + int.from_bytes(value[:4], "little")]

    def dictionary_put(self, seed: bytes, item: str, value: bytes) -> None:
        self._call("dictionary_put", seed, item, value)
        key = self._uref(seed, 2)
        validate_return_payload(value)
        self.dictionaries.setdefault(key.address, {})[item] = value

    def dictionary_read(self, address: bytes) -> bytes:
        self._call("dictionary_read", address)
        target = DictionaryAddress(address)
        for seed, items in self.dictionaries.items():
            for item, value in items.items():
                if blake2b(seed + item.encode("utf8"), digest_size=32).digest() == bytes(target)[1:]:
                    return value[4:4 + int.from_bytes(value[:4], "little")]
        raise ValueNotFound()

    def create_contract_package_at_hash(self, is_locked: bool = False) -> tuple[bytes, bytes]:
        self._call("create_contract_package_at_hash", is_locked)
        if is_locked:
            raise UnsupportedHostCall("Locked packages are not modeled by MockHost")
        package = ContractPackageHash(self._address(b"package"))
        self.packages[bytes(package)] = []
        from ..codec import cl_value
        access = self.new_uref(cl_value("Unit", None))
        return bytes(package), access

    def add_contract_version(self, package: bytes, entries: bytes, named_keys: bytes, topics: bytes) -> tuple[bytes, int]:
        self._call("add_contract_version", package, entries, named_keys, topics)
        if package not in self.packages:
            raise InvalidArgument()
        versions = self.packages[package]
        previous = versions[-1] if versions else None
        topic_names = self.message_topics[previous].copy() if previous is not None else set()
        topic_reader = Reader(topics)
        for _ in range(topic_reader.count(5)):
            topic = self._string(topic_reader)
            if topic_reader.u8() != 0 or topic in topic_names:
                raise InvalidArgument()
            topic_names.add(topic)
        topic_reader.finish()
        key = ContractHash(self._address(b"contract"))
        keys = Reader(named_keys)
        namespace = self.contracts[previous].copy() if previous is not None else {}
        for _ in range(keys.count(6)):
            name = self._string(keys)
            from ..key import key_length
            value = Key.from_bytes(keys.take(key_length(keys.data, keys.offset)))
            if isinstance(value, URef):
                self._uref(bytes(value), 0)
            namespace[name] = value
        keys.finish()
        metadata = Reader(entries)
        entry_points = {}
        for _ in range(metadata.count(10)):
            name = self._string(metadata)
            if self._string(metadata) != name:
                raise InvalidArgument()
            args = {}
            for _ in range(metadata.count(5)):
                arg = self._string(metadata)
                args[arg] = read_kind(metadata)
            returns = read_kind(metadata)
            access = EntryPointAccess.from_value(metadata.u8())
            groups = [self._string(metadata) for _ in range(metadata.count(4))] if access == EntryPointAccess.GROUPS else []
            kind = EntryPointType.from_value(metadata.u8())
            payment = EntryPointPayment.from_value(metadata.u8())
            entry_points[name] = EntryPoint(name, args, returns, access=access, groups=groups,
                                           entry_point_type=kind, payment=payment)
        metadata.finish()
        self.contracts[key], self.entry_points[key] = namespace, entry_points
        self.message_topics[key] = topic_names
        module = self._current.get().module
        if module is not None:
            self.contract_modules[key] = module
        self.packages[package].append(key)
        return bytes(key), len(self.packages[package])

    @staticmethod
    def _string(reader: Reader) -> str:
        from ..codec import decode
        size = reader.u32()
        return str(decode("String", encode("U32", size) + reader.take(size)))

    def call_contract(self, contract: bytes, entry: str, args: bytes) -> bytes:
        """Route registered Python implementations through their own dispatcher."""
        from .contract import ContractHarness

        self._call("call_contract", contract, entry, args)
        key = ContractHash(contract)
        module = self.contract_modules.get(key)
        if module is None:
            raise UnsupportedHostCall("No Python implementation registered for this contract hash")
        reader = Reader(args)
        arguments = {}
        for _ in range(reader.count(9)):
            name = self._string(reader)
            if name in arguments:
                raise InvalidArgument()
            arguments[name] = reader.cl_value()
        reader.finish()
        try:
            result = ContractHarness(module, host=self, contract=key).invoke(
                entry, arguments, caller=self.caller)
        except (ApiError, Revert) as error:
            self._abort_contract_call(error.code)
        except ABIError:
            self._abort_contract_call(3)
        except Exception:
            self._abort_contract_call(65536 + 610)
        # Casper passes returned URef capabilities back to the calling context,
        # including URefs nested in receipt tuples. Never grant rights the
        # callee did not itself possess when completing the invocation.
        self._grant_returned(result.value, result._grants)
        value = result.cl_value
        return b"" if value is None else value.payload

    def _grant_returned(self, value: Any, grants: Mapping[bytes, int]) -> None:
        if isinstance(value, URef):
            if value.access_rights & ~grants.get(value.address, 0):
                raise MockAccessError("Returned URef exceeds the callee's access rights")
            self.grant(value)
        elif isinstance(value, (list, tuple)):
            for item in value:
                self._grant_returned(item, grants)
        elif isinstance(value, dict):
            for key, item in value.items():
                self._grant_returned(key, grants)
                self._grant_returned(item, grants)

    def _abort_contract_call(self, code: int) -> NoReturn:
        error = Revert(code)
        if self._transaction_depth:
            self._contract_revert = error
        raise error from None

    def disable_contract_version(self, package: bytes, contract: bytes) -> None:
        self._call("disable_contract_version", package, contract)
        key = ContractHash(contract)
        if key not in self.packages.get(package, []):
            raise InvalidArgument()
        self.disabled.add(key)

    def enable_contract_version(self, package: bytes, contract: bytes) -> None:
        self._call("enable_contract_version", package, contract)
        self.disabled.discard(ContractHash(contract))
