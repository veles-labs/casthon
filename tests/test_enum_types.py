"""Closed enum domains survive serialization, storage, dispatch and freezing."""

import sys
import tempfile
import types
import unittest
from pathlib import Path
from typing import Optional
from unittest.mock import patch

from casthon import ABIError, CLValue, CLU8, CLU32, InvalidArgument, URef, WireEnum, wire_type
from casthon._dispatch import invoke
from casthon._wire_types import _EnumRef
from casthon.contract_api import runtime
from casthon.return_value import serialize_typed_return, typed_value
from casthon.testing import ContractHarness, MockHost, use_host
from contracts.cep18 import SecurityBadge
from contracts.cep18_errors import InvalidEventsMode
from contracts.cep18_events import EventsMode

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "tests/fixtures"))
from bundle import generate_exports, load_contract, lower, lower_enums
import enum_contract


class EnumTypeTests(unittest.TestCase):
    def test_enum_wire_values_and_closed_discriminants(self):
        self.assertEqual(wire_type(EventsMode), "U8")
        self.assertEqual(wire_type(Optional[EventsMode]), "Option<U8>")
        self.assertEqual(wire_type(_EnumRef("not_imported_yet", "Mode")), "U8")
        for mode in EventsMode:
            self.assertEqual(CLValue(EventsMode, mode).to_bytes(), CLU8(mode.value).to_bytes())
            self.assertIs(runtime._decode(EventsMode, bytes([mode.value])), mode)
        with self.assertRaises(InvalidEventsMode):
            runtime._decode(EventsMode, b"\4")
        class Other(WireEnum):
            OFF = 0
        with self.assertRaises(ABIError):
            runtime._decode(Other, b"\1")
        for value in (1, True, "CES", SecurityBadge.MINTER):
            with self.subTest(value=value), self.assertRaises((TypeError, ABIError)):
                CLValue(EventsMode, value)

    def test_typed_storage_preserves_enum_members_and_rejects_wrong_values(self):
        host = MockHost()
        with use_host(host):
            schema = URef[EventsMode]
            key = schema.create(EventsMode.CES)
            self.assertIs(key.read(), EventsMode.CES)
            key.write(EventsMode.NATIVE)
            self.assertIs(key.read(), EventsMode.NATIVE)
            key.write(CLU8(3))
            self.assertIs(key.read(), EventsMode.NATIVE_BYTES)
            before = host.cells.copy()
            for value in (1, True, "CES", SecurityBadge.MINTER, CLU32(1)):
                with self.subTest(value=value), self.assertRaises((TypeError, ABIError)):
                    key.write(value)
            with self.assertRaises(InvalidEventsMode):
                key.write(CLU8(4))
            self.assertEqual(host.cells, before)

    def test_nullable_enum_values_and_explicit_returns_validate_the_domain(self):
        for value in (None, EventsMode.CES):
            payload = CLValue(Optional[EventsMode], value)
            self.assertIs(runtime._decode(Optional[EventsMode], payload._payload), value)
            self.assertEqual(serialize_typed_return(Optional[EventsMode], value), payload.to_bytes())
        self.assertEqual(typed_value(EventsMode, CLU8(1)).to_bytes(), CLU8(1).to_bytes())
        for value in (1, SecurityBadge.MINTER):
            with self.assertRaises(InvalidArgument):
                serialize_typed_return(EventsMode, value)
        with self.assertRaises(InvalidEventsMode):
            typed_value(EventsMode, CLU8(4))

    def test_contract_state_and_typed_remote_calls_keep_enum_identity(self):
        host = MockHost(strict_arguments=True)
        session = ContractHarness(enum_contract, host=host)
        session.invoke("call")
        contract = host.accounts[host.caller]["py_modes"]
        session.invoke("call", {"contract": CLValue("Key", contract)})
        with use_host(host), host.context(contract=contract):
            state = enum_contract.Modes.bind()
            self.assertIs(state.mode, EventsMode.NATIVE)
            self.assertIs(state.previous["last"], EventsMode.CES)
            self.assertIsNone(state.nullable)
        with self.assertRaises(InvalidEventsMode):
            session.at(contract).invoke("set", {"mode": CLU8(4)})

    def test_freezing_root_enum_annotations_does_not_execute_source(self):
        source = '''from casthon import WireEnum, URef, OptionalArg, MISSING, export
from typing import Optional
class Mode(WireEnum):
    OFF = 0
    ON = 1
Alias = Optional[Mode]
@export
def echo(mode: OptionalArg[Alias] = MISSING) -> Alias:
    return Mode.ON if mode is MISSING else mode
raise RuntimeError("build must not execute this")
'''
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "root_mode.py"
            path.write_text(source)
            declaration, _ = load_contract(path)
            table = generate_exports(path, declaration["exports"])
            self.assertEqual(declaration["signatures"]["echo"]["returns"], "Option<U8>")
            self.assertIn("_EnumRef('contract', 'Mode')", table)
            self.assertNotIn("import contract", table)

    def test_frozen_enum_identity_optional_aliases_and_dispatch_match_native(self):
        source = '''from casthon.enums import WireEnum
from casthon import OptionalArg, MISSING, export
from typing import Optional
class Mode(WireEnum):
    OFF = 0
    ON = 1
Alias = Optional[Mode]
@export
def echo(mode: OptionalArg[Alias] = MISSING) -> Alias:
    return Mode.ON if mode is MISSING else mode
'''
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "root_mode.py"
            path.write_text(source)
            declaration, _ = load_contract(path)
            lowered, table = lower(path), generate_exports(path, declaration["exports"])
        frozen = types.ModuleType("casthon.enums")
        exec(lower_enums(ROOT / "src/casthon/enums.py"), vars(frozen))
        contract = types.ModuleType("contract")
        tables = {}
        host = MockHost()
        with patch.dict(sys.modules, {"casthon.enums": frozen, "contract": contract}), \
                patch("casthon._wire_types.WireEnum", frozen.WireEnum), use_host(host):
            exec(lowered, vars(contract))
            exec(table, tables)
            self.assertIs(contract.Mode(1), contract.Mode.ON)
            self.assertEqual(str(contract.Mode.ON), "1")
            self.assertEqual(invoke(contract.echo, tables["SIGNATURES"]["echo"]), b"\2\0\0\0\1\1\x0d\3")
            host.args["mode"] = b"\0"
            self.assertEqual(invoke(contract.echo, tables["SIGNATURES"]["echo"]), b"\1\0\0\0\0\x0d\3")

    def test_enum_definitions_reject_aliases_and_out_of_range_discriminants(self):
        for members in ({"A": -1}, {"A": 256}, {"A": 1, "B": 1}):
            with self.subTest(members=members), self.assertRaises(ValueError):
                WireEnum("Invalid", members)

