"""Collection semantics, lazy host-result decoding and URef storage access."""

import unittest
from unittest.mock import patch

import cspr
from cspr import AccountHash, Hash, Key, URef, CLU256, U256
from cspr.codec import encode
from cspr.contract_api import runtime, storage
from cspr.testing import use_host
from test_contract_api import MemoryHost


class NamedKeysTests(unittest.TestCase):
    def setUp(self):
        self.host = MemoryHost()
        self.enterContext(use_host(self.host))
        self.keys = runtime.named_keys

    def test_bindings_are_live_and_missing_items_follow_mapping_semantics(self):
        self.assertEqual(len(self.keys), 0)
        self.assertEqual(list(self.keys.items()), [])
        self.assertEqual(list(self.keys.values()), [])
        self.assertNotIn("count", self.keys)
        self.assertIsNone(self.keys.get("count"))
        default = object()
        self.assertIs(self.keys.get("count", default), default)
        with self.assertRaises(KeyError):
            self.keys["count"]
        with self.assertRaises(KeyError):
            del self.keys["count"]

        count = storage.new_uref(CLU256(7))
        self.keys["count"] = count
        self.keys["owner"] = self.host.owner
        self.assertEqual(len(self.keys), 2)
        self.assertIsInstance(self.keys["count"], URef)
        self.assertIsInstance(self.keys["owner"], AccountHash)
        self.assertEqual(self.keys.get("count", default), count)
        self.assertEqual(dict(self.keys), {"count": count, "owner": self.host.owner})
        del self.keys["count"]
        self.assertNotIn("count", self.keys)
        self.assertEqual(count.read(U256), 7)

    def test_uref_operations_change_storage_and_assignment_changes_bindings(self):
        first = storage.new_uref(CLU256(7))
        second = storage.new_uref(CLU256(99))
        self.keys["balance"] = first
        self.keys["balance"].write(CLU256(10))
        self.keys["balance"].add(CLU256(2))
        self.assertEqual(first.read(U256), 12)
        self.assertEqual(self.keys["balance"], first)
        self.keys["balance"] = second
        self.assertEqual(self.keys["balance"].read(U256), 99)
        self.assertEqual(first.read(U256), 12)
        self.assertIsNone(URef(bytes([255]) * 32).read(U256))
        for name in ("read", "write", "add"):
            self.assertFalse(hasattr(self.host.owner, name))

    def test_invalid_storage_keys_and_bindings_fail_before_calling_host(self):
        def unexpected(*args):
            self.fail("Invalid key reached the host")

        self.host.read_value = self.host.write = self.host.add = unexpected
        self.host.put_key = unexpected
        for key in (self.host.owner, Hash(bytes(32)), Key(bytes(URef(bytes(32)))),
                    bytes(URef(bytes(32))), None):
            for operation in (
                lambda: storage.read(key, U256),
                lambda: storage.read_or_revert(key, U256),
                lambda: storage.write(key, CLU256(1)),
                lambda: storage.add(key, CLU256(1)),
            ):
                with self.subTest(key=key), self.assertRaises(TypeError):
                    operation()
        for value in (bytes(self.host.owner), "owner", None):
            with self.assertRaises(TypeError):
                self.keys["owner"] = value
        # The deliberately broader read_from_key operation still accepts a Key.
        self.host.read_value = lambda key: encode("U256", 42)
        self.assertEqual(storage.read_from_key(self.host.owner, U256), 42)

    def test_uref_methods_preserve_host_errors_and_access_rights(self):
        readonly = URef(bytes(32), 1)
        calls = []

        def denied(key, value=None):
            calls.append(key)
            raise cspr.ApiError(23)  # ApiError::PermissionDenied.

        self.host.read_value = self.host.write = self.host.add = denied
        for operation in (lambda: readonly.read(U256),
                          lambda: readonly.write(CLU256(1)),
                          lambda: readonly.add(CLU256(1))):
            with self.assertRaises(cspr.ApiError) as error:
                operation()
            self.assertEqual(error.exception.code, 23)
        self.assertEqual(calls, [bytes(readonly)] * 3)

    def test_iterators_capture_one_snapshot_and_decode_only_consumed_entries(self):
        first, second = URef(bytes(32)), self.host.owner
        self.keys["a"] = first
        self.keys["b"] = second
        with patch.object(self.host, "list_named_keys", wraps=self.host.list_named_keys) as load:
            with patch.object(Key, "from_bytes", wraps=Key.from_bytes) as decode:
                iterator = self.keys.items()
                self.assertIs(iter(iterator), iterator)
                load.assert_called_once_with()
                decode.assert_not_called()
                del self.keys["a"]
                self.keys["b"] = first
                self.keys["c"] = first
                self.assertEqual(next(iterator), ("a", first))
                self.assertEqual(decode.call_count, 1)
                self.assertEqual(list(iterator), [("b", second)])
                self.assertEqual(decode.call_count, 2)
                load.assert_called_once_with()
        self.assertNotIn("a", self.keys)
        self.assertEqual(self.keys["b"], first)
        self.assertEqual(runtime.list_named_keys(), {"b": first, "c": first})

    def test_names_do_not_construct_keys_and_values_are_lazy_typed_keys(self):
        self.keys["a"] = URef(bytes(32))
        self.keys["b"] = self.host.owner
        with patch.object(Key, "from_bytes", side_effect=AssertionError("Eager key decoding")):
            self.assertEqual(list(self.keys), ["a", "b"])
            self.assertEqual(list(self.keys.keys()), ["a", "b"])
        with patch.object(Key, "from_bytes", wraps=Key.from_bytes) as decode:
            values = self.keys.values()
            decode.assert_not_called()
            self.assertIsInstance(next(values), URef)
            self.assertEqual(decode.call_count, 1)
            self.assertIsInstance(next(values), AccountHash)
            self.assertEqual(decode.call_count, 2)
            for _ in range(2):
                with self.assertRaises(StopIteration):
                    next(values)

    def test_malformed_later_entries_are_rejected_only_when_consumed(self):
        first = encode("String", "a") + bytes(self.host.owner)
        bad = encode("String", "b") + b"\xff" + bytes(32)
        self.host.list_named_keys = lambda: encode("U32", 2) + first + bad
        for make_iterator in (self.keys.keys, self.keys.items, self.keys.values):
            iterator = make_iterator()
            next(iterator)
            with self.assertRaises(cspr.ABIError):
                next(iterator)

    def test_named_key_decoding_checks_lengths_utf8_and_trailing_bytes(self):
        malformed = (
            b"", b"\xff" * 4,
            encode("U32", 1) + encode("String", "x") + bytes(URef(bytes(32)))[:-1],
            encode("U32", 1) + b"\xff" * 4 + bytes(self.host.owner),
            encode("U32", 1) + b"\1\0\0\0\xff" + bytes(self.host.owner),
            encode("U32", 1) + encode("String", "x") + bytes(self.host.owner) + b"x",
            encode("U32", 0) + b"x",
        )
        for data in malformed:
            self.host.list_named_keys = lambda: data
            for operation in (lambda: list(self.keys.keys()),
                              lambda: list(self.keys.values()), runtime.list_named_keys):
                with self.subTest(data=data), self.assertRaises(cspr.ABIError):
                    operation()

    def test_lazy_decoder_handles_every_key_variant_in_upstream_fixtures(self):
        import json
        from pathlib import Path

        fixtures = json.loads((Path(__file__).resolve().parents[1] /
                               "reference/cep18/fixtures.json").read_text())["keys"]
        expected = {}
        for index, fixture in enumerate(fixtures):
            name = f"{index:02}"
            self.host.keys[name] = bytes.fromhex(fixture["input"])
            expected[name] = Key.from_bytes(bytes.fromhex(fixture["bytes"]))
        self.assertEqual(list(self.keys.keys()), sorted(expected))
        self.assertEqual(dict(self.keys.items()), expected)
        self.assertEqual(list(self.keys.values()), [expected[name] for name in sorted(expected)])
