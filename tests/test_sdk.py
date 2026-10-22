import ast
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from bundle import check_profile, contract_modules, load_contract, lower
from casthon import U8, U32, U64, U256, Key, wire_type
from casthon.codec import ABIError, cl_value, decode, encode, valid_payload


class CodecTests(unittest.TestCase):
    def test_unsigned_bounds(self):
        for kind, bits in (("U8", 8), ("U32", 32), ("U64", 64), ("U256", 256)):
            for n in (0, 1, (1 << bits) - 1):
                self.assertEqual(decode(kind, encode(kind, n)), n)
            for n in (-1, 1 << bits, True, 1.0, "1"):
                with self.assertRaises(ABIError):
                    encode(kind, n)

    def test_rust_wire_fixtures(self):
        self.assertEqual(cl_value("U32", 0x12345678).hex(), "040000007856341204")
        self.assertEqual(cl_value("U256", 0).hex(), "010000000007")
        self.assertEqual(cl_value("U256", 256).hex(), "0300000002000107")
        self.assertEqual(cl_value("Unit", None).hex(), "0000000009")
        self.assertEqual(cl_value("String", "A").hex(), "0500000001000000410a")
        self.assertEqual(encode("String", "ż🐍"), bytes.fromhex("06000000c5bcf09f908d"))

    def test_all_codecs_reject_malformed_payloads(self):
        for kind, data in (
            ("U8", b""),
            ("U32", b"\0" * 5),
            ("U64", b"\0" * 7),
            ("U256", b"\x21" + b"\0" * 33),
            ("U256", b"\0\0"),
            ("Bool", b"\x02"),
            ("Bool", b""),
            ("Unit", b"\0"),
            ("String", b"\1\0\0\0"),
        ):
            with self.subTest(kind=kind, data=data), self.assertRaises(ABIError):
                decode(kind, data)

    def test_utf8_validates_in_both_python_implementations(self):
        for s in (
            "",
            "hello",
            "ż🐍",
            "\0",
            "\u007f\u0080\u07ff\u0800\uffff\U00010000\U0010ffff",
        ):
            self.assertEqual(decode("String", encode("String", s)), s)
        for b in (
            b"\xff",
            b"\xc0\x80",
            b"\xed\xa0\x80",
            b"\xf4\x90\x80\x80",
            b"\xe2",
            b"\x80",
        ):
            with self.assertRaises(ABIError):
                decode("String", len(b).to_bytes(4, "little") + b)

    def test_explicit_clvalue_classes_and_fallback_validation(self):
        import casthon

        for value, kind, plain in (
            (casthon.CLU8(7), "U8", 7),
            (casthon.CLU32(7), "U32", 7),
            (casthon.CLU64(7), "U64", 7),
            (casthon.CLU256(7), "U256", 7),
            (casthon.CLString("ż🐍"), "String", "ż🐍"),
            (casthon.CLBool(True), "Bool", True),
            (casthon.CLBytes(b"abc"), "Bytes", b"abc"),
            (casthon.CLUnit(), "Unit", None),
            (
                casthon.CLKey(casthon.AccountHash(bytes(32))),
                "Key",
                casthon.AccountHash(bytes(32)),
            ),
            (
                casthon.CLKeyList([casthon.AccountHash(bytes(32))]),
                "List<Key>",
                [casthon.AccountHash(bytes(32))],
            ),
            (
                casthon.CLSecurityMap({casthon.AccountHash(bytes(32)): 0}),
                "Map<Key,U8>",
                {casthon.AccountHash(bytes(32)): 0},
            ),
        ):
            self.assertEqual(value.to_bytes(), cl_value(kind, plain))
            self.assertTrue(valid_payload(kind, encode(kind, plain)))
            self.assertFalse(valid_payload(kind, encode(kind, plain) + b"\xff"))
        for payload in (b"", b"\1\0\0\0\xff", b"\2\0\0\0\xc0\x80", b"\0\0\0\0x"):
            self.assertFalse(valid_payload("String", payload))
        for payload in (b"", b"\xff" + bytes(32), b"\x02" + bytes(32) + b"\x08"):
            self.assertFalse(valid_payload("Key", payload))
        for value in (-1, 1 << 256, True, "1"):
            with self.assertRaises(ABIError):
                casthon.CLU256(value)


class BundleTests(unittest.TestCase):
    def test_entry_points_and_explicit_session_export_without_executing_source(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "example.py"
            source.write_text(
                'from casthon import EntryPoint, U32, export\n'
                'raise RuntimeError("must not execute")\n'
                'ENTRY_POINTS = [EntryPoint("get", {}, U32)]\n'
                'def helper(): pass\ndef get() -> None: pass\n'
                '@export\ndef call() -> None: pass\n'
            )
            config, path = load_contract(source)
            self.assertEqual(config["exports"], ["call"])
            self.assertNotIn("entry_points", config)
            self.assertEqual(path, source.resolve())
            self.assertIn("def call():", lower(path))
            self.assertNotIn("@export", lower(path))
            self.assertNotIn("import EntryPoint, U32, export", lower(path))
            self.assertNotIn("_dispatch", lower(path))

    def test_rejects_invalid_export_signatures_and_markers(self):
        for function in (
            "@export\ndef get(amount): pass",
            "@decorator\n@export\ndef get(): pass",
            "get = export(1)",
            "def helper(amount): pass\nget = export(helper)",
            "def helper(): pass\nget = export(helper, helper)",
            "def helper(): pass\nget = export(function=helper)",
            "def helper(): pass\nfirst = second = export(helper)",
            "@export\ndef ż(): pass",
            "@export\ndef __sf_custom(): pass",
            "@export\ndef asyncify_start_unwind(): pass",
            "def call(): pass",
        ):
            with (
                self.subTest(function=function),
                tempfile.TemporaryDirectory() as directory,
            ):
                root = Path(directory)
                (root / "x.py").write_text('from casthon import export, U32\n' + function + '\n')
                with self.assertRaises(ValueError):
                    load_contract(root / "x.py")

    def test_does_not_require_or_implicitly_export_call(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "x.py"
            source.write_text('from casthon import EntryPoint, export\nENTRY_POINTS = [EntryPoint("get", {})]\n'
                              '@export\ndef get(): pass\ndef call(): pass\n')
            self.assertEqual(load_contract(source)[0]["exports"], ["get"])
            source.write_text('from casthon import export\n@export\ndef call(): pass\n')
            self.assertEqual(load_contract(source)[0]["exports"], ["call"])
            source.write_text('from casthon import EntryPoint\nENTRY_POINTS = [EntryPoint("get", {})]\n'
                              'def get(): pass\n')
            with self.assertRaisesRegex(ValueError, "explicitly"):
                load_contract(source)

    def test_marker_aliases_are_erased_and_export_marker_must_be_outermost(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "x.py"
            source.write_text('import casthon as sdk\nfrom casthon import export as expose\n'
                              '@sdk.export\ndef call(): pass\n@expose\ndef read(): pass\n')
            self.assertEqual(load_contract(source)[0]["exports"], ["call", "read"])
            code = lower(source)
            self.assertNotIn("@", code)
            self.assertNotIn("expose", code)
            source.write_text('from casthon import export\n@other\n@export\ndef call(): pass\n')
            with self.assertRaises(ValueError):
                load_contract(source)

    def test_shared_entry_points_and_imported_function_bindings(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            package = root / "contracts"
            package.mkdir()
            (package / "__init__.py").write_text("")
            shared = package / "shared.py"
            shared.write_text('from casthon import EntryPoint, U32\n'
                              'ENTRY_POINTS = [EntryPoint("get", {}, U32)]\n'
                              'def get() -> None: pass\ndef helper(amount): pass\n')
            source = package / "token.py"
            source.write_text('from casthon import EntryPoint, export\n'
                              'from contracts.shared import ENTRY_POINTS as SHARED, get as implementation\n'
                              'ENTRY_POINTS = [*SHARED, EntryPoint("local", {})]\n'
                              'get = export(implementation)\n@export\ndef local(): pass\n')
            with patch("bundle.ROOT", root):
                self.assertEqual(load_contract(source)[0]["exports"], ["get", "local"])
                self.assertEqual(set(contract_modules(source)),
                                 {"contract.py", "contracts/shared.py", "contracts/__init__.py"})
                # Re-exporting a function under another root binding uses an identity call.
                source.write_text('from casthon import export\nfrom contracts import shared\n'
                                  'read = export(shared.get)\n')
                self.assertEqual(load_contract(source)[0]["exports"], ["read"])
                self.assertIn("read = shared.get", lower(source))
                self.assertNotIn("export", lower(source))
                self.assertIn("contracts/shared.py", contract_modules(source))
                source.write_text('from casthon import export\nfrom contracts import shared\n'
                                  'bad = export(shared.helper)\n')
                with self.assertRaises(ValueError):
                    load_contract(source)

    def test_computed_metadata_is_ordinary_python_data(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "x.py"
            source.write_text('from casthon import EntryPoint as EP, U32, export\n'
                              'FIRST = (EP(name="get", args={}, returns=U32),)\n'
                              'def describe(name): return (EP(name, {"value": U32}),)\n'
                              'ENTRY_POINTS = FIRST + describe("external")\n'
                              '@export\ndef get(): pass\n')
            self.assertEqual(load_contract(source)[0]["exports"], ["get"])
            namespace = {}
            exec(lower(source), namespace)
            self.assertEqual([entry.name for entry in namespace["ENTRY_POINTS"]], ["get", "external"])

    def test_starred_sequences_lower_to_micropython_and_keep_copy_semantics(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "x.py"
            source.write_text('items = [1, 2]\nvalues = [0, *items, 3]\n'
                              'as_tuple = (*items, 4)\ncopy = [*items]\n'
                              '[first, *rest] = items\n')
            code = lower(source)
            namespace = {}
            exec(code, namespace)
            self.assertEqual(namespace["values"], [0, 1, 2, 3])
            self.assertEqual(namespace["as_tuple"], (1, 2, 4))
            self.assertIsNot(namespace["copy"], namespace["items"])
            self.assertEqual((namespace["first"], namespace["rest"]), (1, [2]))
            self.assertFalse(any(isinstance(node, ast.Starred) and isinstance(node.ctx, ast.Load)
                                 for node in ast.walk(ast.parse(code))))

    def test_rejects_cycles_and_nonfunction_bindings(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "x.py"
            source.write_text('from casthon import export\nA = B\nB = A\nget = export(A)\n')
            with self.assertRaisesRegex(ValueError, "Cyclic"):
                load_contract(source)
            source.write_text('from casthon import export\nget = export(1)\n')
            with self.assertRaisesRegex(ValueError, "function"):
                load_contract(source)

    def test_metadata_can_be_mutated_without_affecting_exports(self):
        for mutation in ('ENTRY_POINTS.append(EntryPoint("other", {}))',
                         'ENTRY_POINTS += [EntryPoint("other", {})]',
                         'ENTRY_POINTS[0] = EntryPoint("other", {})'):
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as directory:
                source = Path(directory) / "x.py"
                source.write_text('from casthon import EntryPoint, export\n'
                                  'ENTRY_POINTS = [EntryPoint("get", {})]\n'
                                  'def get(): pass\n@export\ndef call(): pass\n' + mutation + '\n')
                self.assertEqual(load_contract(source)[0]["exports"], ["call"])
                namespace = {}
                exec(lower(source), namespace)
                self.assertIn("other", [entry.name for entry in namespace["ENTRY_POINTS"]])

    def test_profile_limits(self):
        for source in (
            "try:\n pass\nexcept* Exception:\n pass",
            "with x:\n pass",
            "async def f(): pass",
            "x = 1.5j",
            "exec('x = 1')",
            "import os",
        ):
            with self.subTest(source=source), self.assertRaises(ValueError):
                check_profile(ast.parse(source))

    def test_export_accepts_clvalue_returns_and_catchable_code(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "x.py"
            source.write_text('from casthon import CLU32, User, export\n'
                              '@export\ndef get() -> CLU32:\n'
                              ' try:\n  raise User(1)\n except User:\n  return CLU32(7)\n')
            self.assertEqual(load_contract(source)[0]["exports"], ["get"])
            namespace = {}
            exec(lower(source), namespace)
            self.assertEqual(namespace["get"]().value, 7)

    def test_float_literals_and_true_division_are_preserved(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "x.py"
            source.write_text('def calculate(value: int) -> int:\n'
                              ' return int(float(value) + float(3) / 2.0)\n')
            namespace = {}
            exec(lower(source), namespace)
            self.assertEqual(namespace["calculate"](6), 7)

    def test_data_annotations_are_independent_of_exports(self):
        for annotation, kind in (
            (U8, "U8"),
            (U32, "U32"),
            (U64, "U64"),
            (U256, "U256"),
            (str, "String"),
            (Key, "Key"),
        ):
            self.assertEqual(wire_type(annotation), kind)
        with self.assertRaises(TypeError):
            wire_type(int)
