import contextlib
import io
import unittest

from casthon import CLU32, Ret, Revert
from casthon.codec import encode
from casthon.testing import use_host
from contracts import native_unwind
from test_contract_api import MemoryHost


class NativeUnwindSourceTests(unittest.TestCase):
    def test_failure_matrix_agrees_with_normal_python(self):
        host = MemoryHost()
        host.args = {"operation": encode("String", "matrix")}
        with use_host(host), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(native_unwind.call().value, len(native_unwind.EXPECTED))
        self.assertEqual(host.cells[host.keys["native_matrix_ok"]], CLU32(len(native_unwind.EXPECTED)).to_bytes())

    def test_completion_signals_unwind_through_properties_and_constructors(self):
        for case in ("property", "constructor", "sort", "map"):
            for kind, error_type in (("ret", Ret), ("revert", Revert)):
                host = MemoryHost()
                host.args = {name: encode("String", value) for name, value in
                             (("operation", "uncaught"), ("case", case), ("kind", kind))}
                with use_host(host), contextlib.redirect_stdout(io.StringIO()), self.assertRaises(error_type):
                    native_unwind.call()
                self.assertEqual(host.cells[host.keys["native_trace"]], CLU32(19).to_bytes())
                self.assertEqual(host.cells[host.keys["native_inner_trace"]], CLU32(12).to_bytes())
