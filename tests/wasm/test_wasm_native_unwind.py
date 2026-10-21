"""C-origin failures and Python cleanup across native callback families."""

from test_wasm_basic import WasmTestCase
from wasm_harness import Harness, build_file, envelope, payload

CASES = (
    "list_load", "tuple_load", "str_load", "unicode_load", "bytes_load", "bytearray_load",
    "list_store", "list_delete", "bytearray_store", "list_pop", "dict_load", "dict_delete",
    "set_remove", "list_index", "int_parse", "float_parse", "utf8_decode", "wrong_index",
    "wrong_add", "wrong_int", "missing_attr", "float_divide", "float_modulo", "float_floor",
    "int_true_divide", "negative_shift", "missing_arg", "extra_arg", "duplicate_arg",
    "unexpected_keyword", "bad_star", "constructor", "property", "property_store",
    "property_delete", "getitem", "getattr", "callable", "truth", "length", "hash", "compare",
    "string", "iterate", "next", "sort", "sorted", "map", "filter", "max", "int_callback", "import",
)
CALLBACKS = CASES[CASES.index("constructor"):CASES.index("import")]


def arguments(operation, name, kind="error"):
    return {label: payload("String", value) for label, value in
            (("operation", operation), ("case", name), ("kind", kind))}


def stored(host, name):
    key = host.account.get(name)
    return host.cells.get(key[1:33].hex()) if key else None


class NativeUnwindWasmTests(WasmTestCase):
    def test_c_origin_failures_are_catchable_and_run_cleanup(self):
        for suffix in (".wasm", ".metered.wasm"):
            for name in CASES:
                with self.subTest(suffix=suffix, case=name):
                    host = Harness(build_file("native_unwind" + suffix))
                    self.assertEqual(host.invoke("call", arguments("caught", name)), envelope("U32", 1))
                    self.assertEqual(stored(host, "native_trace"), envelope("U32", 19))
                    self.assertIn("FINALLY:outer", "".join(host.prints))
                    if name in CALLBACKS:
                        self.assertEqual(stored(host, "native_inner_trace"), envelope("U32", 12))
                        self.assertIn("FINALLY:inner", "".join(host.prints))
                    self.assertNotIn("NATIVE_ESCAPE", "".join(host.prints))
            host = Harness(build_file("native_unwind" + suffix))
            self.assertEqual(host.invoke("call", arguments("matrix", "")), envelope("U32", len(CASES)))
            self.assertEqual(stored(host, "native_matrix_ok"), envelope("U32", len(CASES)))
            self.assertEqual(sum("FINALLY:failed_import" in line for line in host.prints), 2)

    def test_ret_and_revert_through_c_callbacks_preserve_cleanup(self):
        for suffix in (".wasm", ".metered.wasm"):
            for name in CALLBACKS:
                for kind in ("ret", "revert"):
                    with self.subTest(suffix=suffix, case=name, kind=kind):
                        host = Harness(build_file("native_unwind" + suffix))
                        self.assertEqual(host.invoke("call", arguments("caught", name, kind)), envelope("U32", 1))
                        self.assertEqual(stored(host, "native_trace"), envelope("U32", 19))
                        self.assertEqual(stored(host, "native_inner_trace"), envelope("U32", 12))
                        self.assertNotIn("C_DISPATCH_", "".join(host.prints))
                returned = Harness(build_file("native_unwind" + suffix))
                self.assertEqual(returned.invoke("call", arguments("uncaught", name, "ret")), envelope("U32", 11))
                self.assertEqual(stored(returned, "native_trace"), envelope("U32", 19))
                self.assertEqual(stored(returned, "native_inner_trace"), envelope("U32", 12))
                self.assertIn("C_DISPATCH_RET:Ret", "".join(returned.prints))

    def test_uncaught_errors_and_revert_clean_up_then_roll_back(self):
        cases = [("list_load", "error", 66146)]
        cases += [(name, kind, code) for name in CALLBACKS
                  for kind, code in (("error", 65607), ("revert", 65609))]
        cases += [("import", "error", 65608)]
        for suffix in (".wasm", ".metered.wasm"):
            for name, kind, code in cases:
                with self.subTest(suffix=suffix, case=name, kind=kind):
                    host = Harness(build_file("native_unwind" + suffix))
                    self.assert_reverts(host, "call", arguments("uncaught", name, kind), code)
                    self.assertIn("FINALLY:outer", "".join(host.prints))
                    self.assertNotIn("NATIVE_ESCAPE", "".join(host.prints))
                    self.assertEqual((host.account, host.cells), ({}, {}))
