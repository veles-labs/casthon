"""Return, revert, host failures and cleanup through the actual C boundary."""

from wasm_harness import Harness, build_file, envelope, payload
from test_wasm_basic import WasmTestCase


def invoke(host, operation, overrides=None):
    return host.invoke("call", {"operation": payload("String", operation)}, overrides)


def trace(host):
    return host.cells.get(host.account["dispatch_trace"][1:33].hex())


class DispatchWasmTests(WasmTestCase):
    def test_ordinary_return_raise_and_explicit_signals_at_export_boundary(self):
        for suffix in (".wasm", ".metered.wasm"):
            path = build_file("dispatch_smoke" + suffix)
            for operation, expected in (
                ("internal_return", 8), ("caught", 13), ("explicit_ret", 11),
                ("caught_revert", 17), ("api_caught", 17), ("user_caught", 17), ("storage_errors_caught", 4),
            ):
                with self.subTest(suffix=suffix, operation=operation):
                    host = Harness(path)
                    self.assertEqual(invoke(host, operation), envelope("U32", expected))
                    output = "".join(host.prints)
                    if operation == "explicit_ret":
                        self.assertIn("C_DISPATCH_RET:Ret", output)
                    else:
                        self.assertNotIn("C_DISPATCH_", output)
                    if operation in ("caught", "caught_revert", "api_caught", "user_caught", "storage_errors_caught"):
                        self.assertEqual(trace(host), envelope("U32", expected))
                    if operation == "caught_revert":
                        self.assertIn("FINALLY:caught_revert", output)
            for operation, code, marker in (
                ("uncaught", 65578, "C_DISPATCH_API:ProbeError"),
                ("unexpected", 66146, "C_DISPATCH_UNEXPECTED:ValueError"),
                ("api", 24, "C_DISPATCH_API:MissingKey"),
                ("invalid_return", 3, "C_DISPATCH_API:InvalidArgument"),
                ("invalid_serialized", 3, "C_DISPATCH_API:InvalidArgument"),
                ("invalid_code", 3, "C_DISPATCH_INVALID_API_CODE"),
                ("native_escape", 66146, "C_DISPATCH_UNEXPECTED:IndexError"),
                ("revert", 65579, "C_DISPATCH_REVERT:Revert"),
                ("revert_subclass", 65582, "C_DISPATCH_REVERT:ProbeRevert"),
                ("revert_replaced", 65580, "C_DISPATCH_REVERT:Revert"),
                ("invalid_revert_code", 3, "C_DISPATCH_INVALID_API_CODE"),
                ("storage_decode", 5, "C_DISPATCH_API:Read"),
                ("caught_read_then_abi", 3, "C_DISPATCH_ABI:ABIError"),
                ("storage_missing", 6, "C_DISPATCH_API:ValueNotFound"),
                ("value_not_found", 6, "C_DISPATCH_API:ValueNotFound"),
                ("dictionary_key_too_long", 36, "C_DISPATCH_API:DictionaryItemKeyExceedsLength"),
            ):
                with self.subTest(suffix=suffix, operation=operation):
                    host = Harness(path)
                    self.assert_reverts(host, "call", {"operation": payload("String", operation)}, code)
                    output = "".join(host.prints)
                    self.assertIn(marker, output)
                    if operation == "uncaught":
                        self.assertIn("FINALLY:dispatch", output)
                    if operation in ("revert", "revert_subclass", "revert_replaced"):
                        self.assertIn("FINALLY:revert", output)
                        self.assertNotIn("CAUGHT:Exception", output)
                        self.assertNotIn("AFTER:revert", output)
                    if operation in ("storage_decode", "caught_read_then_abi"):
                        self.assertIn("FINALLY:storage_decode", output)
                        if operation == "caught_read_then_abi":
                            self.assertIn("CAUGHT:Read", output)
                    if operation in ("storage_missing", "value_not_found", "dictionary_key_too_long"):
                        self.assertIn("FINALLY:storage_failure", output)
                    self.assertEqual((host.account, host.cells, host.dictionaries), ({}, {}, {}))
            host = Harness(path)
            self.assertEqual(host.invoke("value"), envelope("U32", 7))
            self.assertIsNone(invoke(host, "none"))
            self.assertEqual(invoke(host, "debug"), envelope("U32", 1))
            args = {"operation": payload("String", "assertion"), "expected": payload("U32", 7)}
            self.assertEqual(host.invoke("call", args), envelope("U32", 7))
            args["expected"] = payload("U32", 8)
            self.assert_reverts(host, "call", args, 66146)
            self.assertIn("C_DISPATCH_UNEXPECTED:AssertionError", "".join(host.prints))

    def test_ret_unwinds_to_success_and_validates_pending_outcomes(self):
        for suffix in (".wasm", ".metered.wasm"):
            path = build_file("dispatch_smoke" + suffix)
            for operation, value, signal in (
                ("ret_finally", 11, True), ("normal_return_finally", 99, False),
                ("ret_replaced", 23, True), ("revert_then_ret", 23, True),
                ("ret_then_return", 29, False), ("ret_caught", 37, False),
                ("ret_subclass", 31, True), ("ret_native_escape", 11, True),
            ):
                with self.subTest(suffix=suffix, operation=operation):
                    host = Harness(path)
                    self.assertEqual(invoke(host, operation), envelope("U32", value))
                    output = "".join(host.prints)
                    self.assertEqual("C_DISPATCH_RET:" in output, signal)
                    self.assertNotIn("CAUGHT:ret", output)
                    self.assertNotIn("AFTER:ret", output)
                    self.assertEqual(trace(host), envelope("U32", 19))
                    if operation == "ret_native_escape":
                        self.assertIn("FINALLY:native_ret", output)
                    elif operation != "ret_caught":
                        self.assertIn("FINALLY:ret", output)
                    if operation in ("ret_finally", "ret_replaced", "ret_then_return", "ret_caught"):
                        self.assertIn("FINALLY:ret_helper", output)
            host = Harness(path)
            self.assertEqual(invoke(host, "ret_unit"), envelope("Unit"))
            self.assertIn("C_DISPATCH_RET:Ret", "".join(host.prints))
            for operation, code, marker in (
                ("ret_then_revert", 65583, "C_DISPATCH_REVERT:Revert"),
                ("ret_then_error", 65584, "C_DISPATCH_API:User"),
                ("ret_invalid_payload", 3, "C_DISPATCH_INVALID_RET_PAYLOAD"),
                ("ret_invalid_type", 3, "C_DISPATCH_INVALID_RET_PAYLOAD"),
                ("ret_missing_payload", 3, "C_DISPATCH_INVALID_RET_PAYLOAD"),
                ("ret_bad_property", 3, "C_DISPATCH_INVALID_RET_PAYLOAD"),
                ("ret_invalid_value", 3, "C_DISPATCH_API:InvalidArgument"),
                ("ret_invalid_serialized", 3, "C_DISPATCH_API:InvalidArgument"),
            ):
                with self.subTest(suffix=suffix, operation=operation):
                    host = Harness(path)
                    self.assert_reverts(host, "call", {"operation": payload("String", operation)}, code)
                    output = "".join(host.prints)
                    self.assertIn(marker, output)
                    invalid = operation.startswith(("ret_invalid", "ret_missing")) or operation == "ret_bad_property"
                    self.assertIn("FINALLY:invalid_ret" if invalid else "FINALLY:ret", output)
                    self.assertEqual((host.account, host.cells), ({}, {}))

    def test_host_status_and_dictionary_policy_errors_unwind_in_python(self):
        for suffix in (".wasm", ".metered.wasm"):
            path = build_file("dispatch_smoke" + suffix)
            for operation, expected in (
                ("host_error_caught", 1), ("bridge_error_caught", 1),
                ("dictionary_policy_caught", 2), ("crypto_error_caught", 1),
            ):
                with self.subTest(suffix=suffix, operation=operation):
                    host = Harness(path)
                    overrides = {"casper_verify_signature": lambda *args: 3} if operation == "crypto_error_caught" else {}
                    self.assertEqual(invoke(host, operation, overrides), envelope("U32", expected))
                    self.assertIn("FINALLY:host_error", "".join(host.prints))
                    self.assertNotIn("NATIVE_ESCAPE", "".join(host.prints))
                    self.assertEqual(trace(host), envelope("U32", 17))
            host = Harness(path)
            self.assert_reverts(host, "call", {"operation": payload("String", "host_error_uncaught")}, 2)
            self.assertIn("FINALLY:host_error", "".join(host.prints))
            self.assertIn("C_DISPATCH_API:MissingArgument", "".join(host.prints))
            self.assertNotIn("dispatch_trace", host.account)

    def test_wire_annotations_and_optional_reads_in_frozen_python(self):
        for suffix in (".wasm", ".metered.wasm"):
            host = Harness(build_file("dispatch_smoke" + suffix))
            self.assertEqual(invoke(host, "wire_types"), envelope("U32", 1))

    def test_host_buffer_failures_raise_before_decoding(self):
        from wasm_harness import Revert
        for status, written in ((5, None), (0, 31)):
            with self.subTest(status=status, written=written):
                host = Harness(build_file("dispatch_smoke.metered.wasm"))

                def corrupt(out, size, actual):
                    if written is not None:
                        host.write_u32(actual, written)
                    return status

                with self.assertRaises(Revert) as error:
                    invoke(host, "wire_types", {"casper_read_host_buffer": corrupt})
                self.assertEqual(error.exception.code, status or 3)
                self.assertIn("C_DISPATCH_API:", "".join(host.prints))
                self.assertNotIn("NATIVE_ESCAPE", "".join(host.prints))
