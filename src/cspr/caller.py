"""CallerInfo and legacy call-stack variants from Casper's host API."""

from typing import Any
from .bytesrepr import Reader
from .errors import ABIError
from .key import AccountHash, ContractHash, ContractPackageHash, PackageHash, AddressableEntity, Key
from .values import SerializedCLValue


class CallerInfo:
    def __init__(self, fields: dict[int, SerializedCLValue]) -> None:
        self.fields = fields

    def _optional(self, index: int, entity: bool = False) -> bytes | None:
        value = self.fields.get(index)
        expected = b"\x0d\x15" if entity else b"\x0d\x0f\x20\0\0\0"
        if value is None or value.cl_type_bytes != expected:
            raise ABIError("Invalid caller field CLType")
        data = value.payload
        if data == b"\0":
            return None
        if len(data) != (34 if entity else 33) or data[0] != 1:
            raise ABIError("Invalid caller field payload")
        return data[1:]

    @property
    def account_hash(self) -> AccountHash | None:
        value = self._optional(0)
        return None if value is None else AccountHash(value)

    @property
    def package_hash(self) -> PackageHash | None:
        value = self._optional(1)
        return None if value is None else PackageHash(value)

    @property
    def contract_package_hash(self) -> ContractPackageHash | None:
        value = self._optional(2)
        return None if value is None else ContractPackageHash(value)

    @property
    def entity(self) -> AddressableEntity | None:
        value = self._optional(3, True)
        if value is None:
            return None
        result = Key.from_bytes(b"\x11" + value)
        if not isinstance(result, AddressableEntity):
            raise ABIError("Expected caller entity")
        return result

    @property
    def contract_hash(self) -> ContractHash | None:
        value = self._optional(4)
        return None if value is None else ContractHash(value)


class AccountCaller(CallerInfo):
    pass


class EntityCaller(CallerInfo):
    pass


class ContractCaller(CallerInfo):
    pass


def decode_caller_information(data: bytes) -> list[CallerInfo]:
    reader = Reader(data)
    result = []
    for _ in range(reader.count(5)):
        kind = reader.u8()
        fields = {}
        for _ in range(reader.count(6)):
            index = reader.u8()
            if index in fields:
                raise ABIError("Duplicate caller field")
            fields[index] = reader.cl_value()
        cls: Any = {0: AccountCaller, 3: EntityCaller, 4: ContractCaller}.get(kind)
        if cls is None:
            raise ABIError("Invalid caller kind")
        info = cls(fields)
        # Validate all five field types, including Option::None fields.
        for index in range(5):
            info._optional(index, index == 3)
        result.append(info)
    reader.finish()
    return result


class CallStackElement:
    def __init__(self, account_hash: AccountHash | None = None,
                 contract_package_hash: ContractPackageHash | None = None,
                 contract_hash: ContractHash | None = None) -> None:
        self.account_hash = account_hash
        self.contract_package_hash = contract_package_hash
        self.contract_hash = contract_hash


class Session(CallStackElement):
    pass


class StoredSession(CallStackElement):
    pass


class StoredContract(CallStackElement):
    pass


def decode_legacy_call_stack(data: bytes) -> list[CallStackElement]:
    reader = Reader(data)
    result: list[CallStackElement] = []
    for _ in range(reader.count(33)):
        tag = reader.u8()
        account = AccountHash(reader.take(32)) if tag in (0, 1) else None
        package = ContractPackageHash(reader.take(32)) if tag in (1, 2) else None
        contract = ContractHash(reader.take(32)) if tag in (1, 2) else None
        if tag > 2:
            raise ABIError("Invalid legacy caller tag")
        result.append((Session, StoredSession, StoredContract)[tag](account, package, contract))
    reader.finish()
    return result
