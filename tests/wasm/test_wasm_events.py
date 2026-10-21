"""Typed event freezing, inheritance, CES writes and exception rollback in Wasm."""

import sys
from cspr import AccountHash, Map, U32, MessageString, MessageBytes
from cspr.codec import cl_value
from cspr.events import event_schemas
from cspr.testing import build_contract
from test_wasm_basic import WasmTestCase
from wasm_harness import Harness, ROOT, envelope, unwrap

sys.path.insert(0, str(ROOT / 'tests/fixtures'))
from event_contract import Events, Started, Added


class EventWasmTests(WasmTestCase):
    @classmethod
    def setUpClass(cls):
        cls.wasm = build_contract(ROOT / 'tests/fixtures/event_contract.py')

    def test_composed_schemas_emit_and_typed_map_return(self):
        for suffix in ('.wasm', '.metered.wasm'):
            with self.subTest(suffix=suffix):
                host = Harness(self.wasm.with_name('event_contract' + suffix))
                host.invoke('call')
                self.assertEqual(host.stored('__events_schema'), event_schemas(Events.event_types()).to_bytes())
                seed = host.contract['__events'][1:33].hex()
                owner = AccountHash(bytes([0x11]) * 32)
                self.assertEqual(unwrap(host.dictionaries[seed]['0'])[4:], b'\x0d\0\0\0event_Started' + Started(owner).to_message().value)
                values = {'count': 7, 'empty': None}
                self.assertEqual(host.invoke('add', {'amount': (7).to_bytes(4, 'little')}), cl_value(Map[str, U32 | None], values))
                self.assertEqual(unwrap(host.dictionaries[seed]['1'])[4:], b'\x0b\0\0\0event_Added' + Added(owner, values).to_message().value)
                self.assertEqual(host.invoke('caught'), envelope('U32', 7))
                self.assertEqual(host.invoke('undeclared'), envelope('Bool', True))
                self.assert_reverts(host, 'fail', {}, 3)
                self.assertEqual(host.invoke('caught'), envelope('U32', 7))
                self.assertEqual(len(host.dictionaries[seed]), 2)

    def test_native_message_carriers_defaults_and_ambiguity(self):
        for suffix in ('.wasm', '.metered.wasm'):
            with self.subTest(suffix=suffix):
                host = Harness(self.wasm.with_name('event_contract' + suffix))
                host.invoke('call')
                host.invoke('messages', {'value': (7).to_bytes(4, 'little')})
                expected = [MessageString('{"value":7}'), MessageBytes((7).to_bytes(4, 'little')),
                            MessageString('{"value":7}'), MessageBytes(b'{"value":7}'),
                            MessageString('{"value":7}'), MessageString('custom'),
                            MessageString('{"value":7}')]
                self.assertEqual([message for topic, message in host.messages], [message.to_bytes() for message in expected])
                self.assertEqual([topic for topic, message in host.messages], ['events'] * 6 + ['audit'])
                self.assertEqual(host.invoke('ambiguous'), envelope('Bool', True))
                self.assertEqual(host.invoke('invalid_encoder'), envelope('Bool', True))
                self.assertEqual(len(host.messages), len(expected))
