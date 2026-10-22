"""Plain optional arguments, explicit validation and guarded class dispatch."""

import ast
from functools import wraps
from pathlib import Path
import unittest

from casthon import ABIError, CLU32, U32
from casthon._signatures import function_signature
from casthon.contract_api import runtime
from casthon.contracts import EntryPointReference
from casthon.testing import ContractHarness, MockHost, use_host
from test_class_contracts import class_pair

ROOT = Path(__file__).resolve().parents[1]


class ArgumentLoadingTests(unittest.TestCase):
    def test_wraps_resolves_annotations_in_the_original_functions_globals(self):
        namespace = {"Amount": U32}
        exec('def read(value: "Amount") -> "Amount": return value', namespace)
        original = namespace["read"]

        @wraps(original)
        def wrapped(*args, **kwargs):
            return original(*args, **kwargs)

        self.assertEqual(function_signature(wrapped), function_signature(original))

    def test_ordinary_decorators_run_once_after_decoding_and_on_local_calls(self):
        source = '''from functools import wraps
from casthon import OptionalArg, MISSING, U32, UserError
from casthon.contract_api.runtime import named_keys
from casthon.contracts import Contract, entry_point, export_contract
TRACE = []
class Denied(UserError):
    def __init__(self): super().__init__(90)
class BadInput(UserError):
    def __init__(self): super().__init__(91)
def require_ready(function):
    @wraps(function)
    def guarded(self, *args, **kwargs):
        TRACE.append("guard")
        if "ready" not in named_keys: raise Denied()
        return function(self, *args, **kwargs)
    return guarded
@export_contract
class Example(Contract):
    @entry_point
    @require_ready
    def read(self, value: OptionalArg[U32] = MISSING) -> U32:
        TRACE.append("body")
        if value is MISSING: raise BadInput()
        return value + 1
'''
        with class_pair(source) as (author, frozen, exports):
            for module in (author, frozen):
                host = MockHost()
                # Frozen functions use the generated schema, not function attributes.
                harness = ContractHarness(module.Example, host=host,
                    exports={"read": EntryPointReference(module.Example, "read")})
                module.TRACE.clear()
                with self.assertRaises(ABIError):
                    harness.invoke('read', raw_args={'value': b'bad'})
                self.assertEqual(module.TRACE, [])
                with self.assertRaises(module.Denied):
                    harness.invoke('read', {'value': CLU32(5)})
                self.assertEqual(module.TRACE, ['guard'])
                with use_host(host):
                    runtime.named_keys['ready'] = host.caller
                module.TRACE.clear()
                with self.assertRaises(ABIError):
                    harness.invoke('read', raw_args={'value': b'bad'})
                self.assertEqual(module.TRACE, [])
                module.TRACE.clear()
                with self.assertRaises(module.BadInput):
                    harness.invoke('read')
                self.assertEqual(module.TRACE, ['guard', 'body'])
                module.TRACE.clear()
                self.assertEqual(harness.invoke('read', {'value': CLU32(5)}).value, 6)
                self.assertEqual(module.TRACE, ['guard', 'body'])
                module.TRACE.clear()
                before = len(host.calls)
                with use_host(host):
                    self.assertEqual(module.Example.bind().read(7), 8)
                self.assertEqual(module.TRACE, ['guard', 'body'])
                self.assertFalse(any(name == 'get_named_arg' for name, args in host.calls[before:]))

    def test_cep18_and_installer_have_no_manual_argument_reads(self):
        for name in ('cep18.py', 'my_token.py'):
            tree = ast.parse((ROOT / 'contracts' / name).read_text())
            reads = [node for node in ast.walk(tree) if isinstance(node, ast.Call)
                     and ((isinstance(node.func, ast.Attribute) and node.func.attr in ('get_named_arg', 'try_get_named_arg'))
                          or isinstance(node.func, ast.Name) and node.func.id in ('get_named_arg', 'try_get_named_arg'))]
            self.assertEqual(reads, [], name)
