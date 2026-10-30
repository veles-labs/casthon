"""Verify literal bytes in MicroPython .mpy bytecode and actual Casper Wasm."""
import ast
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from casthon.testing import build_contract
from wasm_harness import Harness, ROOT

EXPECTED = bytes.fromhex("dd447248098c38a03c5790245a36ba2c246a69c3aef44e271fc87717b25ea9ed")


class CompileTimeHashWasmTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.artifact = build_contract(ROOT / "tests/fixtures/const_hash_contract.py", project_root=ROOT)

    def test_micropython_bytecode_loads_literal_bytes_without_hash_calls(self):
        sys.path.insert(0, str(ROOT / "scripts"))
        from bundle import lower
        compiler_root = ROOT / ".cache/procedural/compiler/micropython-1.29.0"
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "constant_hash.py"
            source.write_text(lower(ROOT / "tests/fixtures/const_hash_contract.py"))
            subprocess.run([str(compiler_root / "mpy-cross/build/mpy-cross"),
                            "-msmall-int-bits=31", str(source)], check=True)
            output = subprocess.check_output([sys.executable, str(compiler_root / "tools/mpy-tool.py"),
                                               "-d", str(source.with_suffix(".mpy"))], text=True)
        objects = next(line.removeprefix("obj_table: ") for line in output.splitlines()
                       if line.startswith("obj_table: "))
        self.assertEqual(ast.literal_eval(objects), [EXPECTED])
        self.assertIn("LOAD_CONST_OBJ", output)
        self.assertNotIn("const_blake2b", output)
        self.assertNotIn("CALL_FUNCTION", output)
        self.assertNotIn("CALL_METHOD", output)
        inline = output.split("simple_name: inline", 1)[1]
        self.assertIn("LOAD_CONST_OBJ", inline)
        self.assertNotIn("LOAD_GLOBAL", inline)

    def test_wasm_returns_same_bytes_without_a_hash_host_call(self):
        def hash_must_not_run(*args):
            raise AssertionError("const_blake2b attempted runtime hashing")
        for suffix in (".wasm", ".metered.wasm"):
            with self.subTest(suffix=suffix):
                host = Harness(self.artifact.with_name(self.artifact.stem + suffix))
                for entry in ("call", "inline"):
                    self.assertEqual(host.invoke(entry, overrides={"casper_blake2b": hash_must_not_run}),
                                     # CLValue: 36-byte payload, List<U8> CLType.
                                     b"\x24\0\0\0\x20\0\0\0" + EXPECTED + b"\x0e\x03")
