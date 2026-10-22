"""Enum member identity across frozen dispatch, URefs and dictionaries."""

from casthon.testing import build_contract

from test_wasm_basic import WasmTestCase
from wasm_harness import Harness, ROOT, envelope


class EnumWasmTests(WasmTestCase):
    @classmethod
    def setUpClass(cls):
        cls.wasm = build_contract(ROOT / "tests/fixtures/enum_contract.py")

    def hosts(self):
        for suffix in (".wasm", ".metered.wasm"):
            host = Harness(self.wasm.with_name("enum_contract" + suffix))
            host.invoke("call")
            yield host

    def test_enum_members_survive_storage_dispatch_and_return_encoding(self):
        for host in self.hosts():
            self.assertEqual(host.invoke("local", {"mode": b"\1"}), envelope("U8", 1))
            self.assert_reverts(host, "local", {"mode": b"\2"}, 3)
            self.assertEqual(host.invoke("get"), envelope("U8", 1))
            for value, previous in ((2, 1), (3, 2), (0, 3), (1, 0)):
                self.assertEqual(host.invoke("set", {"mode": bytes([value])}), envelope("U8", previous))
                self.assertEqual(host.invoke("get"), envelope("U8", value))
            self.assert_reverts(host, "set", {"mode": b"\4"}, 65536 + 60006)
            self.assert_reverts(host, "set", {"mode": b""}, 3)
            self.assert_reverts(host, "set", {"mode": b"\1\0"}, 3)
            self.assertEqual(host.invoke("get"), envelope("U8", 1))

    def test_nullable_presence_and_dictionary_values_keep_enum_identity(self):
        for host in self.hosts():
            self.assertEqual(host.invoke("optional"), b"\1\0\0\0\0\x0d\3")
            self.assertEqual(host.invoke("optional", {"mode": b"\1\3"}), b"\2\0\0\0\1\3\x0d\3")
            self.assertEqual(host.invoke("optional"), b"\2\0\0\0\1\3\x0d\3")
            self.assert_reverts(host, "optional", {"mode": b"\1\4"}, 65536 + 60006)
            self.assertEqual(host.invoke("optional", {"mode": b"\0"}), b"\1\0\0\0\0\x0d\3")
