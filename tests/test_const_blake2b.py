"""Native hash parity and proof that lowered Python loads literal bytes."""
import ast
import dis
import hashlib
from pathlib import Path
import sys
import tempfile
import types
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from bundle import lower
from casthon import const_blake2b

ROOT = Path(__file__).resolve().parents[1]
EXPECTED = bytes.fromhex("dd447248098c38a03c5790245a36ba2c246a69c3aef44e271fc87717b25ea9ed")


class ConstantHashTests(unittest.TestCase):
    def lowered(self, source):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "contract.py"
            path.write_text(source)
            return lower(path)

    def test_native_matches_casper_blake2b_256_without_host(self):
        self.assertEqual(const_blake2b("MINTER_ROLE"), EXPECTED)
        self.assertEqual(const_blake2b(b"MINTER_ROLE"), EXPECTED)
        for value in (b"", b"\0\xff", b"x" * 1000):
            self.assertEqual(const_blake2b(value), hashlib.blake2b(value, digest_size=32).digest())
        self.assertEqual(const_blake2b("ż🐍"), const_blake2b("ż🐍".encode("utf-8")))
        for invalid in (None, 1, True, bytearray(b"a")):
            with self.assertRaises(TypeError):
                const_blake2b(invalid)

    def test_literal_bytes_are_present_in_actual_python_bytecode(self):
        code = lower(ROOT / "tests/fixtures/const_hash_contract.py")
        compiled = compile(code, "lowered_contract.py", "exec")
        self.assertIn(EXPECTED, compiled.co_consts)
        inline = next(item for item in compiled.co_consts
                      if isinstance(item, types.CodeType) and item.co_name == "inline")
        self.assertIn(EXPECTED, inline.co_consts)
        instructions = list(dis.get_instructions(inline))
        self.assertTrue(any(item.opname == "LOAD_CONST" and item.argval == EXPECTED for item in instructions))
        self.assertFalse(any("CALL" in item.opname for item in instructions))
        self.assertNotIn("const_blake2b", compiled.co_names)
        self.assertNotIn("hashlib", compiled.co_names)
        scope = {}
        exec(compiled, scope)
        self.assertEqual(scope["call"](), EXPECTED)
        self.assertEqual(scope["inline"](), EXPECTED)

    def test_import_aliases_and_qualified_calls_fold(self):
        for imported, call in (("from casthon import const_blake2b", "const_blake2b"),
                               ("from casthon import const_blake2b as digest", "digest"),
                               ("import casthon", "casthon.const_blake2b"),
                               ("import casthon as sdk", "sdk.const_blake2b")):
            with self.subTest(imported=imported):
                code = self.lowered(imported + '\nROLE = ' + call + '("MINTER_ROLE")\n')
                assignment = next(node for node in ast.parse(code).body if isinstance(node, ast.Assign))
                self.assertIsInstance(assignment.value, ast.Constant)
                self.assertEqual(assignment.value.value, EXPECTED)
                self.assertNotIn("const_blake2b", code)

    def test_cross_module_constants_and_intrinsic_reexports(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "contracts").mkdir()
            (root / "contracts/__init__.py").touch()
            helper = root / "contracts/roles.py"
            helper.write_text('from casthon import const_blake2b\nROLE = const_blake2b("MINTER_ROLE")\n')
            source = root / "contract.py"
            source.write_text('from contracts.roles import ROLE, const_blake2b as digest\nOTHER = digest("MINTER_ROLE")\n')
            self.assertNotIn("const_blake2b", lower(helper, project_root=root))
            lowered = lower(source, project_root=root)
            self.assertIn("import ROLE", lowered)
            self.assertNotIn("digest", lowered)
            self.assertIn(repr(EXPECTED), lowered)

    def test_nonliteral_arguments_and_escaping_intrinsic_are_rejected(self):
        expressions = ('const_blake2b(value)', 'const_blake2b("x" + "y")',
                       'const_blake2b(12)', 'const_blake2b()', 'const_blake2b(*["x"])',
                       'const_blake2b(value="x")', 'const_blake2b("x", "y")',
                       'const_blake2b', '[const_blake2b]')
        for expression in expressions:
            with self.subTest(expression=expression), self.assertRaisesRegex(ValueError, "const_blake2b"):
                self.lowered('from casthon import const_blake2b\ndef f(value):\n return ' + expression + '\n')

    def test_shadowed_imports_and_local_intrinsic_imports_are_rejected(self):
        for body in ('def f(const_blake2b):\n return const_blake2b("x")',
                     'def f():\n const_blake2b = str\n return const_blake2b("x")',
                     'def f():\n from casthon import const_blake2b\n return const_blake2b("x")'):
            with self.subTest(body=body), self.assertRaisesRegex(ValueError, "const_blake2b"):
                self.lowered('from casthon import const_blake2b\n' + body + '\n')

    def test_rebound_global_intrinsic_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "cannot be rebound"):
            self.lowered('from casthon import const_blake2b\nconst_blake2b = const_blake2b("x")\n')

    def test_unrelated_method_with_same_name_is_not_an_intrinsic(self):
        code = self.lowered('def run(obj):\n return obj.const_blake2b("x")\n')
        self.assertIn('obj.const_blake2b', code)

    def test_native_only_hash_helper_is_absent_from_frozen_sdk(self):
        code = lower(ROOT / "src/casthon/__init__.py", sdk=True)
        self.assertNotIn("const_blake2b", code)
        self.assertNotIn("hashlib", code)
