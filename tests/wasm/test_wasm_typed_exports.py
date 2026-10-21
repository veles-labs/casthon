"""Independent wire fixtures for frozen typed-argument/return dispatch."""

from test_wasm_basic import WasmTestCase
from wasm_harness import Harness, Revert, build_file, envelope, payload, u32


def option(value):
    return b"\0" if value is None else b"\x01" + payload("U32", value)


def option_envelope(data, tag):
    return u32(len(data)) + data + bytes([13, tag])


def variants():
    for suffix in (".wasm", ".metered.wasm"):
        yield Harness(build_file("typed_exports" + suffix))


def cleanup(host):
    key = host.contract.get("typed_cleanup")
    return host.cells.get(key[1:33].hex()) if key else None


class TypedExportWasmTests(WasmTestCase):
    def test_argument_presence_is_independent_of_nullable_encoding_and_defaults(self):
        for host in variants():
            self.assertEqual(host.invoke("presence"), envelope("String", "missing"))
            self.assertEqual(host.invoke("presence_default"), envelope("String", "none"))
            self.assertEqual(host.invoke("presence_number"), envelope("String", "7"))
            for value in (None, 0, 7, 0xffffffff):
                for entry in ("presence", "presence_default"):
                    expected = "none" if value is None else str(value)
                    self.assertEqual(host.invoke(entry, {"value": option(value)}), envelope("String", expected))
            self.assertEqual(host.invoke("presence_number", {"value": payload("U32", 0)}), envelope("String", "0"))
            for raw in (b"", b"\2", b"\0\0", b"\1", b"\1\0\0\0"):
                for entry in ("presence", "presence_default"):
                    self.assert_reverts(host, entry, {"value": raw}, 3)
            self.assert_reverts(host, "presence_number", {"value": b"\0"}, 3)

    def test_multiple_arguments_and_ordinary_imported_calls(self):
        for host in variants():
            self.assertEqual(host.invoke("calculate", {"amount": payload("U32", 5), "label": payload("String", "abc")}), envelope("U32", 8))
            self.assertEqual(host.invoke("internal", {"amount": payload("U32", 5)}), envelope("U32", 9))
            self.assert_reverts(host, "calculate", {"amount": payload("U32", 5)}, 2)
            self.assert_reverts(host, "calculate", {"amount": bytes(3), "label": payload("String", "abc")}, 3)
            self.assert_reverts(host, "calculate", {"amount": payload("U32", 0xffffffff), "label": payload("String", "x")}, 3)

    def test_nullable_values_and_strict_option_tags(self):
        for host in variants():
            for value in (None, 0, 7, 0xffffffff):
                data = option(value)
                self.assertEqual(host.invoke("nullable", {"amount": data}), option_envelope(data, 4))
            self.assert_reverts(host, "nullable", {}, 2)
            for data in (b"", b"\x02", b"\0\0", b"\x01", b"\x01\0\0\0", b"\x01\0\0\0\0\0"):
                self.assert_reverts(host, "nullable", {"amount": data}, 3)

    def test_defaults_only_apply_to_absent_arguments_including_keyword_only(self):
        for host in variants():
            self.assertEqual(host.invoke("defaults"), envelope("String", "default:7"))
            self.assertEqual(host.invoke("defaults", {"amount": option(None)}), envelope("String", "default:None"))
            self.assertEqual(host.invoke("defaults", {"amount": option(0), "label": payload("String", "custom")}), envelope("String", "custom:0"))
            self.assert_reverts(host, "defaults", {"amount": b"\x02"}, 3)
            self.assert_reverts(host, "defaults", {"label": b"\x01\0\0\0\xff"}, 3)
            with self.assertRaises(Revert) as error:
                host.invoke("defaults", {}, {"casper_get_named_arg_size": lambda *args: 5})
            self.assertEqual(error.exception.code, 5)

    def test_optional_key_arguments_and_typed_key_return_variants(self):
        for host in variants():
            account = b"\0" + host.caller
            some_account = b"\x01" + account
            self.assertEqual(host.invoke("owner", {"value": b"\0"}), option_envelope(b"\0", 11))
            self.assertEqual(host.invoke("owner", {"value": some_account}), option_envelope(some_account, 11))
            self.assert_reverts(host, "owner", {"value": b"\x01\x01" + bytes(32)}, 3)
            self.assertEqual(host.invoke("key_return", {"valid": b"\x01"}), u32(len(account)) + account + b"\x0b")
            self.assert_reverts(host, "key_return", {"valid": b"\0"}, 3)

    def test_return_validation_follows_finally_and_rolls_back_invalid_returns(self):
        for host in variants():
            def invoke(operation):
                return host.invoke("checked_return", {"operation": payload("String", operation)})
            self.assertEqual(invoke("plain"), envelope("U32", 7))
            self.assertEqual(cleanup(host), envelope("U32", 1))
            self.assertEqual(invoke("explicit"), envelope("U32", 11))
            self.assertEqual(cleanup(host), envelope("U32", 2))
            for operation in ("overflow", "negative", "bool", "none", "wrong_cl_type", "bad_payload"):
                self.assert_reverts(host, "checked_return", {"operation": payload("String", operation)}, 3)
                self.assertEqual(cleanup(host), envelope("U32", 2))
            self.assertEqual(host.invoke("early_ret", {"amount": payload("U32", 13)}), envelope("U32", 13))
            self.assertEqual(cleanup(host), envelope("U32", 3))
            self.assert_reverts(host, "failure", {"code": payload("U32", 42)}, 65578)
            self.assertEqual(cleanup(host), envelope("U32", 3))
            self.assertEqual(host.invoke("unit"), envelope("Unit"))
            self.assertEqual(cleanup(host), envelope("U32", 4))

    def test_stored_metadata_remains_explicit_with_option_cltypes(self):
        for host in variants():
            self.assertEqual(host.invoke("call"), envelope("Unit"))
            self.assertEqual(sorted(host.account), ["py_typed_exports", "py_typed_exports_access", "py_typed_exports_package"])
            data, offset = host.entry_points, 0

            def uint():
                nonlocal offset
                value = int.from_bytes(data[offset:offset + 4], "little")
                offset += 4
                return value

            def text():
                nonlocal offset
                size = uint()
                value = data[offset:offset + size].decode()
                offset += size
                return value

            def cltype():
                nonlocal offset
                tag = data[offset]
                offset += 1
                self.assertIn(tag, (4, 10, 11, 13))
                return [tag, *cltype()] if tag == 13 else [tag]

            entries = []
            for _ in range(uint()):
                name = text()
                self.assertEqual(text(), name)
                args = {}
                for _ in range(uint()):
                    label = text()
                    args[label] = cltype()
                returns = cltype()
                entries.append((name, args, returns, list(data[offset:offset + 3])))
                offset += 3
            self.assertEqual(offset, len(data))
            self.assertEqual(entries, [
                ("calculate", {"amount": [4], "label": [10]}, [4], [1, 1, 0]),
                ("nullable", {"amount": [13, 4]}, [13, 4], [1, 1, 0]),
                ("owner", {"value": [13, 11]}, [13, 11], [1, 1, 0]),
                ("presence", {}, [10], [1, 1, 0]),
                ("presence_default", {}, [10], [1, 1, 0]),
                ("presence_number", {}, [10], [1, 1, 0]),
            ])
