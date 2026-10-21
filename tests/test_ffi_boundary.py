"""Check transport errors and annotation parity across authoring and freezing."""

import sys
import tempfile
import unittest
from pathlib import Path

import cspr
from cspr._ffi import call
from cspr.contract_api import runtime, storage, system, account
from cspr.testing import use_host
from test_contract_api import MemoryHost

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from bundle import lower


class Transport:
    def __init__(self, status, value=None):
        self.status, self.value = status, value
        self.calls = []

    def __getattr__(self, name):
        def invoke(*args):
            self.calls.append((name, args))
            return self.status, self.value
        return invoke


class FfiBoundaryTests(unittest.TestCase):
    def test_host_status_is_catchable_and_cleanup_runs(self):
        events = []
        with use_host(Transport(2), raw=True):
            try:
                runtime.get_named_arg("missing", cspr.U32)
            except cspr.MissingArgument as error:
                events.append(error.code)
            finally:
                events.append("finally")
        self.assertEqual(events, [2, "finally"])

    def test_error_subclasses_and_unknown_codes_preserve_host_status(self):
        for code, error_type in ((3, cspr.InvalidArgument), (5, cspr.Read),
                                 (6, cspr.ValueNotFound), (12, cspr.InvalidPurse),
                                 (24, cspr.MissingKey),
                                 (36, cspr.DictionaryItemKeyExceedsLength),
                                 (65543, cspr.User), (12345, cspr.ApiError)):
            with self.subTest(code=code), use_host(Transport(code), raw=True):
                with self.assertRaises(error_type) as error:
                    call("probe")
                self.assertEqual(error.exception.code, code)

    def test_optional_policy_handles_only_the_expected_status(self):
        for code, operation, expected in (
            (2, lambda: runtime.try_get_named_arg("missing", cspr.U32), None),
            (24, lambda: runtime.get_key("missing"), None),
            (6, lambda: storage.read_from_key(cspr.Hash(bytes(32)), cspr.U32), None),
            (6, lambda: storage.dictionary_get(cspr.URef(bytes(32)), "missing", cspr.U32), None),
            (6, lambda: storage.dictionary_read(cspr.DictionaryAddress(bytes(32)), cspr.U32), None),
            (12, lambda: system.get_purse_balance(cspr.URef(bytes(32))), None),
        ):
            with self.subTest(code=code), use_host(Transport(code), raw=True):
                self.assertIs(operation(), expected)
            with use_host(Transport(5), raw=True):
                with self.assertRaises(cspr.Read):
                    operation()

    def test_account_domain_statuses_remain_values(self):
        with use_host(Transport(0, 2), raw=True):
            self.assertIs(account.add_associated_key(cspr.AccountHash(bytes(32)), 1),
                          cspr.AddKeyFailure.DUPLICATE_KEY)

    def test_dictionary_policy_runs_before_allocation_and_installs_seed(self):
        host = MemoryHost()
        with use_host(host):
            with self.assertRaises(cspr.InvalidArgument):
                storage.new_dictionary("")
            self.assertEqual(host.next, 1)
            seed = storage.new_dictionary("balances")
            self.assertEqual(runtime.get_key("balances"), seed)
            with self.assertRaises(cspr.InvalidArgument):
                storage.new_dictionary("balances")
            self.assertEqual(host.next, 2)
            self.assertEqual(runtime.get_key("balances"), seed)

    def test_frozen_resolver_uses_shared_rules_and_rejects_unknown_descriptors(self):
        namespace = {"__package__": "cspr"}
        exec((ROOT / "runtime/types.py").read_text(), namespace)
        for author, frozen in ((cspr.U8, namespace["U8"]), (cspr.U512, namespace["U512"]),
                               (None, None), (type(None), type(None)), (cspr.URef, cspr.URef),
                               (bytes, bytes), (bool, bool), (str, str),
                               (list[cspr.Key], "List<Key>"),
                               (dict[cspr.Key, cspr.U8], "Map<Key,U8>")):
            self.assertEqual(cspr.wire_type(author), namespace["wire_type"](frozen))
        for invalid in (int, "Bogus", "List<U32>", object()):
            for resolver in (cspr.wire_type, namespace["wire_type"]):
                with self.assertRaises(TypeError):
                    resolver(invalid)

    def test_frozen_key_methods_keep_type_only_imports_out_of_runtime(self):
        source = ROOT / "src/cspr/key.py"
        code = lower(source, sdk=True)
        self.assertNotIn("TYPE_CHECKING", code)
        namespace = {"__package__": "cspr"}
        exec(code, namespace)
        self.assertNotIn("CLValue", namespace)
        self.assertTrue(callable(namespace["URef"].write))

    def test_builder_lowers_imported_generic_aliases_without_executing_source(self):
        source = '''from cspr import Key as Address, U8 as Weight, wire_type
from typing import Annotated as A, List as L, Dict as D
import typing as T
Addresses = list[Address]
Weights = D[Address, Weight]
def descriptors():
    return [wire_type(Addresses), wire_type(Weights), wire_type(L[Address]),
            wire_type(A[int, "U32"]), wire_type(type(None)),
            wire_type(T.List[Address]), T.cast(str, "Unit")]
'''
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "types_probe.py"
            path.write_text(source)
            author, frozen = {}, {}
            exec(source, author)
            code = lower(path)
            self.assertNotIn("typing", code)
            self.assertNotIn("list[", code)
            exec(code, frozen)
            self.assertEqual(author["descriptors"](), frozen["descriptors"]())
            self.assertEqual(frozen["descriptors"](),
                             ["List<Key>", "Map<Key,U8>", "List<Key>", "U32", "Unit", "List<Key>", "Unit"])

    def test_rejected_generic_annotations_fail_during_build(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "types_probe.py"
            for annotation in ("list[int]", "dict[Key, int]", "Optional[int]", "T.Tuple[Key]"):
                path.write_text("from cspr import Key, U32\nfrom typing import Optional\nimport typing as T\nvalue = " + annotation + "\n")
                with self.assertRaises(TypeError):
                    lower(path)
