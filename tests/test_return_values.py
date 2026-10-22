"""Completion signals unwind Python before the host receives a return value."""

import unittest

from casthon import CLU32, CLUnit, InvalidArgument, Ret, Revert, UserError, SerializedCLValue
from casthon.contract_api import runtime
from casthon.return_value import serialize_return, validate_return_payload


class LiveReturn(CLU32):
    def to_bytes(self):
        return CLU32(self.value).to_bytes()


class MalformedReturn(CLU32):
    def to_bytes(self):
        return b"bad"


class ReturnTests(unittest.TestCase):
    def test_ret_unwinds_helpers_without_broad_catches_and_snapshots_payload(self):
        events = []
        value = LiveReturn(7)

        def helper():
            try:
                runtime.ret(value)
            finally:
                events.append("inner")

        with self.assertRaises(Ret) as outcome:
            try:
                helper()
                events.append("after")
            except Exception:
                events.append("caught")
            finally:
                value.value = 9
                events.append("outer")
        self.assertEqual(events, ["inner", "outer"])
        self.assertEqual(outcome.exception.payload, CLU32(7).to_bytes())

    def test_ret_is_explicitly_catchable_including_unit(self):
        events = []
        try:
            runtime.ret(CLUnit())
        except Ret as outcome:
            events.append(outcome.payload)
        finally:
            events.append("finally")
        self.assertEqual(events, [CLUnit().to_bytes(), "finally"])

    def test_finally_can_replace_success_with_failure_or_failure_with_success(self):
        with self.assertRaises(UserError) as error:
            try:
                runtime.ret(CLU32(7))
            finally:
                raise UserError(48)
        self.assertEqual(error.exception.code, 65536 + 48)
        with self.assertRaises(Revert) as error:
            try:
                runtime.ret(CLU32(7))
            finally:
                runtime.revert(65536 + 47)
        self.assertEqual(error.exception.code, 65536 + 47)
        with self.assertRaises(Ret) as outcome:
            try:
                runtime.revert(65536 + 47)
            finally:
                runtime.ret(CLU32(23))
        self.assertEqual(outcome.exception.payload, CLU32(23).to_bytes())

    def test_validation_errors_are_catchable_at_the_ret_call(self):
        events = []
        try:
            runtime.ret(MalformedReturn(7))
        except InvalidArgument:
            events.append("caught")
        finally:
            events.append("finally")
        self.assertEqual(events, ["caught", "finally"])
        with self.assertRaises(InvalidArgument):
            serialize_return(7)

    def test_serializer_rejects_malformed_envelopes_and_cltypes(self):
        for data in (
            b"", b"bad", b"\5\0\0\0\0\4", b"\0\0\0\0\xff",
            b"\0\0\0\0\x0d", b"\0\0\0\0\x09\0",
            b"\0\0\0\0" + b"\x0d" * 34 + b"\x04",
            bytearray(CLUnit().to_bytes()),
        ):
            with self.subTest(data=data), self.assertRaises(InvalidArgument):
                validate_return_payload(data)

    def test_serializer_preserves_complete_recursive_cltypes(self):
        # Option<U32>, beyond the simple authoring constructors.
        payload = b"\1" + (7).to_bytes(4, "little")
        data = len(payload).to_bytes(4, "little") + payload + b"\x0d\x04"
        self.assertEqual(serialize_return(SerializedCLValue(data)), data)


if __name__ == "__main__":
    unittest.main()
