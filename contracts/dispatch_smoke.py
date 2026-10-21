"""Exercise ordinary internal calls and the outer return/error boundary."""

from typing import cast, NoReturn
from cspr import ApiError, User, UserError, Ret, Revert, Read, ValueNotFound, MissingKey, Hash, U32, URef, CLValue, CLU32, CLString, CLUnit, export
from cspr import MissingArgument, InvalidArgument, Key, U8, CLKeyList, CLSecurityMap, wire_type, Ed25519PublicKey, Ed25519Signature
from cspr.contract_api import runtime, storage, cryptography


class ProbeError(User):
    pass


class ProbeRevert(Revert):
    pass


class ProbeRet(Ret):
    pass


class LiveReturn(CLU32):
    def to_bytes(self) -> bytes:
        return CLU32(self.value).to_bytes()


class MissingRet(Ret):
    def __init__(self) -> None:
        pass


class PropertyRet(Ret):
    def __init__(self) -> None:
        pass

    @property
    def payload(self) -> bytes:
        raise UserError(49)

    @payload.setter
    def payload(self, value: bytes) -> None:
        pass


class NativeReturn:
    @property
    def value(self) -> CLU32:
        runtime.ret(CLU32(11))


class BrokenReturn(CLU32):
    def to_bytes(self) -> bytes:
        return cast(bytes, 7)


def _mark(value: int) -> None:
    key = runtime.get_key("dispatch_trace")
    if key is None:
        runtime.put_key("dispatch_trace", storage.new_uref(CLU32(value)))
    elif isinstance(key, URef):
        storage.write(key, CLU32(value))


def _fail() -> None:
    _mark(3)
    raise ProbeError(42)


def _return(value: CLValue) -> NoReturn:
    try:
        runtime.ret(value)
    finally:
        print("FINALLY:ret_helper")


@export
def value() -> CLU32:
    return CLU32(7)


@export
def call() -> CLValue | None:
    operation = runtime.get_named_arg("operation", str)
    if operation == "internal_return":
        # @export leaves this an ordinary Python call.
        return CLU32(value().value + 1)
    if operation in ("ret_finally", "normal_return_finally", "ret_replaced",
                     "revert_then_ret", "ret_then_return", "ret_subclass",
                     "ret_then_revert", "ret_then_error"):
        result = LiveReturn(11)
        try:
            _mark(3)
            if operation == "normal_return_finally":
                return result
            if operation == "revert_then_ret":
                runtime.revert(65536 + 47)
            if operation == "ret_subclass":
                raise ProbeRet(CLU32(31).to_bytes())
            _return(result)
        except Exception:
            _mark(99)
            print("CAUGHT:ret")
        finally:
            result.value = 99
            _mark(19)
            print("FINALLY:ret")
            if operation in ("ret_replaced", "revert_then_ret"):
                runtime.ret(CLU32(23))
            if operation == "ret_then_return":
                return CLU32(29)
            if operation == "ret_then_revert":
                runtime.revert(65536 + 47)
            if operation == "ret_then_error":
                raise UserError(48)
        print("AFTER:ret")
    if operation == "ret_caught":
        try:
            _return(CLU32(11))
        except Ret as outcome:
            if outcome.payload != CLU32(11).to_bytes():
                raise
            _mark(7)
        finally:
            _mark(19)
        return CLU32(37)
    if operation == "ret_unit":
        _mark(19)
        runtime.ret(CLUnit())
    if operation == "ret_native_escape":
        try:
            _mark(3)
            return NativeReturn().value
        finally:
            _mark(19)
            print("FINALLY:native_ret")
    if operation in ("ret_invalid_payload", "ret_invalid_type", "ret_missing_payload",
                     "ret_bad_property", "ret_invalid_value", "ret_invalid_serialized"):
        try:
            _mark(3)
            if operation == "ret_invalid_payload":
                raise Ret(b"bad")
            if operation == "ret_invalid_type":
                raise Ret(cast(bytes, 7))
            if operation == "ret_missing_payload":
                raise MissingRet()
            if operation == "ret_bad_property":
                raise PropertyRet()
            if operation == "ret_invalid_value":
                runtime.ret(cast(CLValue, 7))
            runtime.ret(BrokenReturn(7))
        finally:
            _mark(19)
            print("FINALLY:invalid_ret")
    if operation == "caught":
        try:
            _fail()
        except ApiError as error:
            if error.code != 65536 + 42:
                raise
            _mark(7)
        finally:
            _mark(13)
        key = runtime.get_key("dispatch_trace")
        if not isinstance(key, URef):
            raise MissingKey()
        return CLU32(storage.read_or_revert(key, U32))
    if operation == "uncaught":
        try:
            _fail()
        finally:
            _mark(13)
            print("FINALLY:dispatch")
    if operation in ("revert", "revert_subclass", "revert_replaced"):
        try:
            _mark(3)
            if operation == "revert_subclass":
                raise ProbeRevert(65536 + 46)
            runtime.revert(65536 + 43)
        except Exception:
            _mark(99)
            print("CAUGHT:Exception")
        finally:
            _mark(17)
            print("FINALLY:revert")
            if operation == "revert_replaced":
                runtime.revert(65536 + 44)
        print("AFTER:revert")
    if operation == "caught_revert":
        try:
            runtime.revert(65536 + 43)
        except Revert as error:
            if error.code != 65536 + 43:
                raise
            _mark(7)
        finally:
            _mark(17)
            print("FINALLY:caught_revert")
        key = runtime.get_key("dispatch_trace")
        if not isinstance(key, URef):
            raise MissingKey()
        return CLU32(storage.read_or_revert(key, U32))
    if operation in ("api_caught", "user_caught"):
        try:
            if operation == "api_caught":
                raise ApiError(5)
            raise UserError(44)
        except Exception as error:
            if not isinstance(error, ApiError):
                raise
            _mark(7)
        finally:
            _mark(17)
        key = runtime.get_key("dispatch_trace")
        if not isinstance(key, URef):
            raise MissingKey()
        return CLU32(storage.read_or_revert(key, U32))
    if operation in ("host_error_caught", "host_error_uncaught", "bridge_error_caught",
                     "dictionary_policy_caught", "crypto_error_caught"):
        caught = 0
        try:
            if operation in ("host_error_caught", "host_error_uncaught"):
                runtime.get_named_arg("missing", U32)
            elif operation == "bridge_error_caught":
                runtime.call_contract(runtime.get_caller(), "get", {}, U32)
            elif operation == "dictionary_policy_caught":
                seed = storage.new_dictionary("policy_dictionary")
                try:
                    storage.new_dictionary("policy_dictionary")
                except InvalidArgument:
                    caught += 1
                assert runtime.get_key("policy_dictionary") == seed
                storage.new_dictionary("")
            else:
                public = Ed25519PublicKey(bytes.fromhex("d75a980182b10ab7d54bfed3c964073a0ee172f3daa62325af021a68f707511a"))
                signature = Ed25519Signature(bytes.fromhex("e5564300c360ac729086e2cc806e828a84877f1eb8e5d974d873e06522490155"
                                                         "5fb8821590a33bacc61e39701cf9b46bd25bf5f0595bbe24655141438e7a100b"))
                cryptography.verify_signature(b"wrong message", signature, public)
        except ApiError as error:
            if operation == "host_error_uncaught":
                raise
            assert error.code == (2 if operation == "host_error_caught" else 3)
            assert isinstance(error, MissingArgument if error.code == 2 else InvalidArgument)
            caught += 1
        finally:
            _mark(17)
            print("FINALLY:host_error")
        assert caught == (2 if operation == "dictionary_policy_caught" else 1)
        return CLU32(caught)
    if operation == "wire_types":
        caller = runtime.get_caller()
        keys = storage.new_uref(CLKeyList([caller]))
        weights = storage.new_uref(CLSecurityMap({caller: 7}))
        assert storage.read_or_revert(keys, list[Key]) == [caller]
        assert storage.read_or_revert(weights, dict[Key, U8]) == {caller: 7}
        assert wire_type(type(None)) == "Unit"
        assert runtime.try_get_named_arg("missing", U32) is None
        assert runtime.try_get_named_arg("operation", U32) is None
        assert wire_type("Map<Key,U8>") == "Map<Key,U8>"
        try:
            wire_type("Unknown")
        except TypeError:
            return CLU32(1)
        raise User(60)
    if operation in ("storage_decode", "caught_read_then_abi"):
        key = storage.new_uref(CLString("bad"))
        try:
            storage.read_or_revert(key, U32)
        except Read as error:
            if operation != "caught_read_then_abi" or error.code != 5:
                raise
            print("CAUGHT:Read")
        finally:
            _mark(17)
            print("FINALLY:storage_decode")
        runtime.get_named_arg("operation", U32)
    if operation in ("storage_missing", "value_not_found", "dictionary_key_too_long"):
        try:
            if operation == "storage_missing":
                storage.read_or_revert(URef(bytes([255]) * 32), U32)
            elif operation == "value_not_found":
                raise ValueNotFound()
            else:
                seed = storage.new_dictionary("oversize_dictionary")
                storage.dictionary_put(seed, "x" * 65, CLU32(1))
        finally:
            _mark(17)
            print("FINALLY:storage_failure")
    if operation == "storage_errors_caught":
        key = storage.new_uref(CLString("bad"))
        seed = storage.new_dictionary("caught_dictionary")
        caught = 0
        for name, code in (("missing", 6), ("decode", 5), ("get", 36), ("put", 36)):
            try:
                if name == "missing":
                    # A hash key can be missing without forging a URef capability.
                    if storage.read_from_key(Hash(bytes([255]) * 32), U32) is None:
                        raise ValueNotFound()
                elif name == "decode":
                    storage.read_or_revert(key, U32)
                elif name == "get":
                    storage.dictionary_get(seed, "x" * 65, U32)
                else:
                    storage.dictionary_put(seed, "x" * 65, CLU32(1))
            except Exception as error:
                if not isinstance(error, ApiError) or error.code != code:
                    raise
                caught += 1
            finally:
                _mark(caught)
        key = runtime.get_key("dispatch_trace")
        if not isinstance(key, URef):
            raise MissingKey()
        return CLU32(storage.read_or_revert(key, U32))
    if operation == "invalid_revert_code":
        runtime.revert(-1)
    if operation == "unexpected":
        raise ValueError("unexpected contract error")
    if operation == "api":
        raise MissingKey()
    if operation == "invalid_return":
        return cast(CLValue, 7)
    if operation == "invalid_serialized":
        return BrokenReturn(7)
    if operation == "invalid_code":
        raise ApiError(-1)
    if operation == "native_escape":
        values: list[int] = []
        return CLU32(values[0])
    if operation == "explicit_ret":
        runtime.ret(CLU32(11))
    if operation == "assertion":
        assert runtime.get_named_arg("expected", U32) == 7, "assertions remain enabled"
        return CLU32(7)
    if operation == "debug":
        return CLU32(1 if __debug__ else 0)
    return None
