"""Check the procedural SDK and reject incorrect Casper data types."""

import subprocess
import sys
from pathlib import Path

root = Path(__file__).resolve().parent.parent
subprocess.run([sys.executable, "-m", "mypy"], cwd=root, check=True)
flow = root / ".cache/revert_types.py"
flow.write_text("""from typing import Mapping, NoReturn, Optional, assert_type
from casthon import const_blake2b, Key, URef, U32, U256, AccountHash, ContractHash, ContractPackageHash, Dictionary, Ret, Revert, ApiError, UserError, CLU32, SerializedCLValue, OptionalArg, MISSING, export, Event, Bytesrepr, Json, JsonBytes, MessageEncoder, MessageString, MessageBytes, emit
from casthon.contract_api import runtime
from casthon.contracts import Contract
from casthon.testing import DevnetNetwork, TestAccount, SimulationResult
from contracts import counter
from contracts.my_token import MyToken
from contracts.cep18_events import EventsMode, Mint, ChangeSecurity
from contracts import typed_exports
assert_type(const_blake2b("MINTER_ROLE"), bytes)
class Properties(Contract):
    value: U32 = runtime.named_keys.property()
    target: ContractHash = runtime.named_keys.property()
    stored_target: ContractHash = runtime.named_keys.property(uref=True)
    items: Dictionary[str, U32] = runtime.named_keys.property()
def state_property_types(state: Properties, target: ContractHash) -> None:
    assert_type(state.value, int)
    assert_type(state.target, ContractHash)
    assert_type(state.stored_target, ContractHash)
    assert_type(state.items, Dictionary[str, int])
    state.value += 1
    state.target = target
    state.stored_target = target
    state.items["item"] = state.value
def getter_simulation(network: DevnetNetwork, contract: ContractHash, caller: TestAccount) -> None:
    result = network.simulate(contract, "get", caller=caller)
    assert_type(result, SimulationResult)
    assert_type(result.cl_value, SerializedCLValue | None)
    assert_type(result.consumed, int)
    assert_type(result.block_height, int)
    assert_type(result.state_root_hash, str)
def event_types(owner: AccountHash) -> None:
    event = Mint(owner, 42)
    assert_type(event.amount, int)
    assert_type(event.recipient, Key)
    assert_type(ChangeSecurity(owner, {owner: 1}).sec_change_map, dict[Key, int])
class BinaryEvent(Event, Bytesrepr):
    amount: U32
class MultiEvent(Event, Bytesrepr, Json):
    amount: U32
class DefaultEvent(MultiEvent):
    def to_message(self) -> MessageString | MessageBytes:
        return Json.to_message(self)
def custom_encoder(event: BinaryEvent) -> MessageString:
    return MessageString(str(event.amount))
def message_types() -> None:
    record = BinaryEvent(7)
    assert_type(record.to_message(), MessageString | MessageBytes)
    assert_type(Bytesrepr.to_message(record), MessageString | MessageBytes)
    runtime.emit_message("events", MessageString("payload"))
    emit(record)
    emit(record, topic="audit", encoder=custom_encoder)
    multi = MultiEvent(7)
    emit(multi, encoder=Json.to_message)
    emit(multi, encoder=Bytesrepr.to_message)
    emit(DefaultEvent(7))
    runtime.emit_message("events", MessageBytes(b"serialized").to_bytes())
def presence_type(value: OptionalArg[Optional[U32]] = MISSING) -> U32:
    if value is MISSING:
        return 1
    if value is None:
        return 2
    assert_type(value, int)
    return value
def optional_calls(contract: ContractHash) -> None:
    assert_type(presence_type(MISSING), int)
    assert_type(presence_type(None), int)
    assert_type(presence_type(0), int)
    assert_type(contract.call(typed_exports.presence, MISSING), str)
    assert_type(contract.call(typed_exports.presence, None), str)
    assert_type(contract.call(typed_exports.presence_number), str)
    runtime.get_named_arg("value", OptionalArg[Optional[U32]])
@export
def typed_export(amount: U32, memo: Optional[str] = None) -> U32:
    assert_type(amount, int)
    assert_type(memo, str | None)
    return amount + 1
def ordinary_calls() -> None:
    assert_type(typed_export(7), int)
    assert_type(counter.Counter(3).get(), int)
    assert_type(counter.Counter.bind().get_increments(AccountHash(bytes(32))), int)
    state = counter.Counter.bind()
    assert_type(state, counter.Counter)
    assert_type(state.named_keys, Mapping[str, Key])
    package = ContractPackageHash(bytes(32))
    assert_type(package.add_contract_version(state), tuple[ContractHash, int])
    assert_type(package.disable_contract_version(ContractHash(bytes(32))), None)
    assert_type(package.enable_contract_version(ContractHash(bytes(32))), None)
    assert_type(state.count, int)
    assert_type(state.paused, bool)
    assert_type(state.owner, AccountHash)
    assert_type(state.increments.get(AccountHash(bytes(32)), 0), int)
    token = MyToken(total_supply=100)
    assert_type(token.events_mode, EventsMode)
    token.events_mode = EventsMode.CES
    assert_type(MyToken(events_mode=EventsMode.NATIVE), MyToken)
    assert_type(token.balance_of(AccountHash(bytes(32))), int)
    assert_type(token.balances.get(AccountHash(bytes(32)), 0), int)
    assert_type(token.allowances.get(bytes(66), 0), int)
    assert_type(token.supply, int)
def remote_calls(contract: ContractHash) -> None:
    assert_type(contract.call(counter.Counter.get), int)
    assert_type(contract.call(counter.Counter.increment_by, 5), None)
    assert_type(contract.call(counter.Counter.increment_by, amount=5), None)
    assert_type(contract.call(counter.Counter.get_increments, AccountHash(bytes(32))), int)
    assert_type(contract.call(counter.Counter.get_owner), AccountHash)
    assert_type(contract.call(counter.Counter.is_paused), bool)
    assert_type(contract.call(counter.Counter.pause), None)
    assert_type(contract.call(MyToken.transfer, AccountHash(bytes(32)), 5), None)
    assert_type(contract.call(MyToken.balance_of, AccountHash(bytes(32))), int)
def abort() -> NoReturn:
    runtime.revert(3)
def finish() -> NoReturn:
    runtime.ret(CLU32(7))
def return_if_missing() -> Key:
    key = runtime.get_key("count")
    if key is None:
        runtime.ret(CLU32(0))
    assert_type(key, Key)
    return key
def require_key() -> Key:
    key = runtime.get_key("count")
    if key is None:
        runtime.revert(24)
    assert_type(key, Key)
    return key
def ordinary_error() -> ApiError:
    return UserError(100)
def named_key_access() -> None:
    keys = runtime.named_keys
    keys["count"] = URef(bytes(32))
    assert_type(keys["count"], Key)
    assert_type(keys.get("count"), Key | None)
    assert_type(keys.get("count", 0), Key | int)
    for name, key in keys.items():
        assert_type(name, str)
        assert_type(key, Key)
        if isinstance(key, URef):
            key.write(CLU32(7))
            key.read(U32)
def typed_references() -> None:
    count = runtime.named_keys.reference("count", URef[U32])
    assert_type(count.read(), int)
    assert_type(count.get(), URef[U32])
    assert_type(count.get().read(), int)
    count.write(7)
    count.get().write(8)
    total = runtime.named_keys.reference("total", URef[U256])
    total.add(1)
    hash_ref = runtime.named_keys.reference("contract", ContractHash)
    assert_type(hash_ref.get(), ContractHash)
    balances = runtime.named_keys.reference("balances", Dictionary[AccountHash, U256](key=lambda account: bytes(account).hex()))
    owner = AccountHash(bytes(32))
    balances[owner] = 5
    assert_type(balances[owner], int)
    assert_type(balances.get(owner), int | None)
    assert_type(balances.get(owner, 0), int)
    assert_type(balances.seed, URef)
try:
    abort()
except Revert as error:
    assert_type(error.code, int)
try:
    finish()
except Ret as outcome:
    assert_type(outcome.payload, bytes)
""")
subprocess.run([sys.executable, "-m", "mypy", str(flow)], cwd=root, check=True)
bad = root / ".cache/type_errors.py"
bad.write_text("""from casthon import Event, Bytesrepr, Json, MessageEncoder, MessageString, MessageBytes, AccountHash, ContractHash, ContractPackageHash, Dictionary, URef, U32, CLU32, CLKey, OptionalArg, emit
from casthon.contract_api import runtime, storage
from contracts import counter
from contracts.my_token import MyToken
from contracts.cep18 import SecurityBadge
from contracts.cep18_events import Mint, ChangeSecurity
from contracts import typed_exports
CLU32("5")
CLKey("recipient")
storage.write(AccountHash(bytes(32)), CLU32(5))
storage.new_uref(5)
storage.dictionary_put(URef(bytes(32)), 1, CLU32(5))
runtime.call_contract(AccountHash(bytes(32)), "get", {"amount": (int, 5)})
runtime.named_keys["count"].write(CLU32(5))
runtime.named_keys["count"] = CLU32(5)
count = runtime.named_keys.reference("count", URef[U32])
count.write("bad")
count.create("bad")
ledger = runtime.named_keys.reference("ledger", Dictionary[str, U32]())
ledger[1] = 5
ledger["x"] = "bad"
runtime.named_keys.reference("contract", ContractHash).set(AccountHash(bytes(32)))
counter.Counter().increment_by("bad")
counter.Counter().get_increments(ContractHash(bytes(32)))
contract = ContractHash(bytes(32))
contract.call(counter.Counter.increment_by, "bad")
contract.call(counter.Counter.increment_by)
contract.call(counter.Counter.get, amount=1)
contract.call(counter.Counter.get_increments, contract)
wrong_result: str = contract.call(counter.Counter.get)
state = counter.Counter()
state.count = "bad"
state.paused = 1
state.owner = contract
state.increments[contract] = 1
contract.call(counter.Counter.transfer_ownership, contract)
counter.Counter("bad")
counter.Counter.bind(3)
package = runtime.named_keys.reference("package", ContractPackageHash).get()
package.add_contract_version(state, {})
package.add_contract_version(contract)
package.disable_contract_version(AccountHash(bytes(32)))
package.enable_contract_version(URef(bytes(32)))
state.add_contract_version(package)
MyToken(total_supply="bad")
contract.call(MyToken.transfer, AccountHash(bytes(32)), "bad")
wrong_balance: str = contract.call(MyToken.balance_of, AccountHash(bytes(32)))
token = MyToken()
token.events_mode = 1
token.events_mode = SecurityBadge.ADMIN
contract.call(MyToken.change_events_mode, "CES")
contract.call(MyToken.change_events_mode, 1)
MyToken(events_mode=1)
token.balances["not a Key"] = 1
token.allowances[AccountHash(bytes(32))] = 1
typed_exports.presence("bad")
typed_exports.presence_number(None)
contract.call(typed_exports.presence, "bad")
Mint(AccountHash(bytes(32)))
Mint(AccountHash(bytes(32)), "bad")
ChangeSecurity(AccountHash(bytes(32)), {AccountHash(bytes(32)): "bad"})
class BinaryEvent(Event, Bytesrepr):
    amount: U32
class BadEncoder(MessageEncoder):
    def to_message(self) -> str:
        return "wrong carrier"
def bad_encoder(event: BinaryEvent) -> bytes:
    return b"wrong carrier"
emit(BinaryEvent(7), encoder=bad_encoder)
emit(MessageString("payload"))
emit(b"serialized")
emit(BinaryEvent(7), encoder=Json.to_message)
runtime.emit_message("events", BinaryEvent(7))
Json.to_message(BinaryEvent(7))
def unhandled_missing(value: OptionalArg[U32]) -> U32:
    return value
""")
result = subprocess.run(
    [sys.executable, "-m", "mypy", str(bad)], cwd=root, capture_output=True, text=True
)
print(result.stdout, end="")
if result.returncode != 1 or result.stdout.count("error:") != 56:
    raise SystemExit("Expected fifty-six rejected type mistakes\n" + result.stderr)
