"""Event schema composition, structural codecs and native/frozen parity."""

import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from casthon import ABIError, AccountHash, CLValue, Event, Key, Map, U8, U32, U256, URef, Bytesrepr, Json, JsonBytes, MessageEncoder, MessageString, MessageBytes
from casthon.codec import encode, decode, cl_type, valid_payload
from casthon.contracts import Contract
from casthon.events import event_schema, event_schemas
from casthon.messages import MessagePayload
from casthon import ces, emit
from casthon.testing import MockHost, use_host
from casthon.contract_api import storage, runtime
from casthon.testing.values import inspect_value, runtime_args, from_json
from test_class_contracts import class_pair

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from bundle import lower, load_contract


class Opened(Event, Bytesrepr):
    owner: Key


class Credited(Event, Bytesrepr):
    recipient: Key
    amount: U256


class LedgerChanged(Event, Json):
    amounts: Map[Key, U256]
    memo: str | None


class OwnEvents(Contract):
    events = (Opened,)


class Credits(OwnEvents):
    events = (Credited, Opened)


class Memos(OwnEvents):
    events = (LedgerChanged,)


class Ledger(Credits, Memos):
    events = (Credited,)


class EventTests(unittest.TestCase):
    def setUp(self):
        self.owner = AccountHash(bytes([1]) * 32)

    def test_record_constructor_keywords_equality_repr_and_no_state_access(self):
        record = Credited(self.owner, amount=42)
        self.assertEqual(record, Credited(recipient=self.owner, amount=42))
        self.assertNotEqual(record, Opened(self.owner))
        self.assertIn('amount=42', repr(record))
        for args, kwargs in (((self.owner,), {}), ((self.owner, 1, 2), {}),
                             ((self.owner, 1), {'amount': 2}), ((), {'bogus': 3})):
            with self.subTest(args=args), self.assertRaises(TypeError):
                Credited(*args, **kwargs)
        self.assertEqual(record.to_message().value, encode(Key, self.owner) + encode(U256, 42))

    def test_registry_combines_mixins_and_deduplicates_the_same_class(self):
        self.assertEqual(Ledger.event_types(), (Opened, LedgerChanged, Credited))
        host = MockHost()
        with use_host(host):
            instance = Ledger()
            package, _ = storage.create_contract_package_at_hash()
            keys = dict(instance.named_keys)
            keys.update(ces.initial_named_keys(Ledger.event_types()))
            storage.add_contract_version(package, Ledger.entry_points(), keys)
            self.assertEqual(inspect_value(host.cells[keys['__events_length'].address])[1], 0)
            schema_key = keys['__events_schema']
            self.assertEqual(host.cells[schema_key.address], event_schemas(Ledger.event_types()).to_bytes())
            self.assertFalse(any(host.accounts.values()))
            ces.emit(Credited(self.owner, 42), events=Ledger.event_types(), named_keys=keys)
            data = host.dictionaries[keys['__events'].address]['0']
            self.assertEqual(inspect_value(data)[1], encode(str, 'event_Credited') + Credited(self.owner, 42).to_message().value)
            self.assertFalse(hasattr(instance, 'emit'))

    def test_undeclared_and_invalid_payload_fail_before_writing(self):
        host = MockHost()
        with use_host(host):
            instance = Ledger()
            keys = ces.initial_named_keys(Ledger.event_types())
            for record, error in ((Event(), TypeError), (Credited(self.owner, -1), ABIError),
                                  (Credited(self.owner, 1 << 256), ABIError)):
                before = dict(host.cells)
                with self.assertRaises(error):
                    ces.emit(record, events=Ledger.event_types(), named_keys=keys)
                self.assertEqual(host.cells, before)
                self.assertFalse(host.dictionaries[keys['__events'].address])

    def test_distinct_event_classes_cannot_share_a_wire_name(self):
        class Other(Event):
            __event_name__ = 'Opened'
            amount: U32
        class Bad(OwnEvents):
            events = (Other,)
        with self.assertRaisesRegex(ValueError, 'wire name'):
            Bad.event_types()
        with self.assertRaisesRegex(ValueError, 'wire name'):
            event_schemas((Opened, Other))

    def test_structural_nested_maps_round_trip_storage_and_rpc(self):
        annotation = Map[Key, list[Map[str, U32 | None]]]
        value = {self.owner: [{'zero': 0, 'none': None}]}
        self.assertEqual(cl_type(annotation), bytes([17, 11, 14, 17, 10, 13, 4]))
        payload = encode(annotation, value)
        self.assertEqual(decode(annotation, payload), value)
        self.assertTrue(valid_payload(annotation, payload))
        for malformed in (payload[:-1], payload + b'\0', b'\xff' * 4):
            self.assertFalse(valid_payload(annotation, malformed))
            with self.assertRaises(ABIError):
                decode(annotation, malformed)
        with use_host(MockHost()):
            binding = runtime.named_keys.reference('nested', URef[annotation])
            binding.set(binding.create(value))
            self.assertEqual(binding.read(), value)
            binding.write({})
            self.assertEqual(binding.read(), {})
        explicit = CLValue(annotation, value)
        self.assertEqual(inspect_value(explicit.to_bytes())[1], value)
        rpc = runtime_args({'value': explicit})[0][1]
        self.assertEqual(from_json(rpc).to_bytes(), explicit.to_bytes())
        with self.assertRaises(ABIError):
            encode(annotation, {self.owner: [{'bad': -1}]})

    def test_json_escaping_nullable_and_map_field_values(self):
        record = LedgerChanged({self.owner: 12}, 'quote"\n\\\t€')
        self.assertEqual(json.loads(record.to_message().value), {'amounts': {str(self.owner): '12'}, 'memo': record.memo})
        self.assertIsNone(json.loads(LedgerChanged({}, None).to_message().value)['memo'])

    def test_frozen_event_inheritance_composition_and_constructors(self):
        source = '''from casthon import Event, Bytesrepr, U32, Key, Map, export
from casthon.contracts import Contract, export_contract
class Started(Event, Bytesrepr):
    actor: Key
class Added(Started):
    values: Map[str, U32]
@export
def call() -> None: pass
class First(Contract):
    events = (Started,)
class Second(First):
    events = (Added,)
@export_contract
class Example(Second, First):
    events = (Started,)
'''
        with class_pair(source) as (author, frozen, exports):
            for module in (author, frozen):
                self.assertEqual([owner.__name__ for owner in module.Example.event_types()], ['Started', 'Added'])
                record = module.Added(self.owner, {'a': 3})
                self.assertEqual(record.to_message().value, encode(Key, self.owner) + encode(Map[str, U32], {'a': 3}))
                self.assertEqual(module.Added(actor=self.owner, values={}), module.Added(self.owner, {}))
                with self.assertRaises(TypeError):
                    module.Added(self.owner)
            self.assertEqual(event_schemas(author.Example.event_types()).to_bytes(), event_schemas(frozen.Example.event_types()).to_bytes())

    def test_builder_does_not_execute_source_and_rejects_bad_declarations(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'event_fixture.py'
            prefix = 'from casthon import Event, U32, export\nfrom casthon.contracts import Contract, export_contract\n@export\ndef call() -> None: pass\n'
            path.write_text(prefix + 'raise RuntimeError("must not run")\nclass Changed(Event):\n    value: U32\n@export_contract\nclass Token(Contract):\n    events = (Changed,)\n')
            load_contract(path)
            self.assertIn('_bind_event(Changed', lower(path))
            cases = ('class Changed(Event):\n    value: int\n',
                     'class Changed(Event):\n    value: U32 = 1\n',
                     'class Changed(Event):\n    def __init__(self): pass\n',
                     'class Changed(Event):\n    to_message: U32\n')
            for case in cases:
                path.write_text(prefix + case + '@export_contract\nclass Token(Contract):\n    events = (Changed,)\n')
                with self.subTest(case=case), self.assertRaises((ValueError, TypeError)):
                    load_contract(path)

    def test_single_encoder_defaults_and_explicit_carrier_selection(self):
        class Plain(Event):
            value: U32
        class Binary(Event, Bytesrepr):
            value: U32
        class Text(Event, Json):
            value: U32
        class Utf8(Event, JsonBytes):
            value: U32
        self.assertIsInstance(Plain(7).to_message(), MessageBytes)
        self.assertEqual(Plain(7).to_message().value, encode(U32, 7))
        self.assertEqual(Json.to_message(Plain(7)).value, '{"value":7}')
        self.assertIsInstance(Binary(7).to_message(), MessageBytes)
        self.assertEqual(Binary(7).to_message().value, encode(U32, 7))
        self.assertEqual(Text(7).to_message().value, '{"value":7}')
        self.assertEqual(Utf8(7).to_message().value, b'{"value":7}')
        self.assertEqual(len(event_schema(Utf8).encoders), 1)
        with self.assertRaisesRegex(TypeError, 'no message encoder'):
            Event().to_message()

    def test_multiple_encoders_require_explicit_choice_or_an_event_default(self):
        class Multiple(Event, Bytesrepr, Json):
            value: U32
        class Default(Multiple):
            def to_message(self):
                return Json.to_message(self)
        record = Multiple(7)
        with self.assertRaisesRegex(TypeError, 'Multiple event encoders'):
            record.to_message()
        self.assertEqual(Bytesrepr.to_message(record).value, encode(U32, 7))
        self.assertEqual(Json.to_message(record).value, '{"value":7}')
        self.assertEqual(Default(7).to_message().value, '{"value":7}')

    def test_custom_encoder_mixin_and_invalid_encoder_result(self):
        class Custom(MessageEncoder):
            def to_message(self):
                return MessageString('custom')
        class Encoded(Event, Custom):
            value: U32
        class Bad(MessageEncoder):
            def to_message(self):
                return b'not a message'
        class Invalid(Event, Bad):
            value: U32
        self.assertEqual(Encoded(7).to_message().value, 'custom')
        with self.assertRaisesRegex(TypeError, 'MessageString or MessageBytes'):
            Invalid(7).to_message()

    def test_json_validation_does_not_serialize_binary_fields(self):
        record = LedgerChanged({self.owner: 12}, 'memo')
        with patch('casthon.events.encode', side_effect=AssertionError('binary serialization')), \
             patch.object(Key, 'to_bytes', side_effect=AssertionError('binary Key serialization')):
            self.assertIn('memo', record.to_message().value)
        with self.assertRaises(ABIError):
            LedgerChanged({self.owner: -1}, None).to_message()

    def test_ces_initialization_is_explicit_idempotent_and_preserves_history(self):
        host = MockHost()
        with use_host(host):
            self.assertNotIn('__events', runtime.named_keys)
            ces.initialize(Ledger.event_types())
            first = dict(runtime.named_keys)
            ces.emit(Credited(self.owner, 1), events=Ledger.event_types())
            ces.initialize(Ledger.event_types())
            self.assertEqual(dict(runtime.named_keys), first)
            self.assertEqual(runtime.named_keys['__events_length'].read(U32), 1)
            record = LedgerChanged({}, None)
            ces.emit(record)
            self.assertEqual(runtime.named_keys['__events_length'].read(U32), 2)
            seed = runtime.named_keys['__events']
            self.assertEqual(inspect_value(host.dictionaries[seed.address]['1'])[1],
                             encode(str, 'event_LedgerChanged') + Bytesrepr.to_message(record).value)

    def test_emit_uses_event_defaults_on_the_default_topic(self):
        class Plain(Event):
            value: U32
        host = MockHost()
        with use_host(host):
            host.message_topics[host.caller] = {'events'}
            emit(Plain(7))
            emit(Plain(8), encoder=Json.to_message)
            emit(Credited(self.owner, 1))
            emit(LedgerChanged({}, None))
        expected = [MessageBytes(encode(U32, 7)), MessageString('{"value":8}'),
                    MessageBytes(encode(Key, self.owner) + encode(U256, 1)),
                    MessageString('{"amounts":{},"memo":null}')]
        self.assertEqual([message[2] for message in host.messages], [message.to_bytes() for message in expected])

    def test_emit_accepts_an_explicit_topic(self):
        host = MockHost()
        with use_host(host):
            host.message_topics[host.caller] = {'audit'}
            emit(Credited(self.owner, 1), topic='audit')
        self.assertEqual(host.messages[0][1], 'audit')

    def test_emit_selects_an_encoder_or_an_explicit_event_default(self):
        class Multiple(Event, Bytesrepr, Json):
            value: U32
        class Default(Multiple):
            def to_message(self):
                return Json.to_message(self)
        with patch('casthon.contract_api.runtime._call') as call:
            for record, encoder, expected in (
                (Multiple(7), Json.to_message, MessageString('{"value":7}')),
                (Multiple(7), Bytesrepr.to_message, MessageBytes(encode(U32, 7))),
                (Default(7), None, MessageString('{"value":7}')),
                (Default(7), Bytesrepr.to_message, MessageBytes(encode(U32, 7))),
                (Multiple(7), lambda event: MessageString(str(event.value)), MessageString('7')),
            ):
                emit(record, encoder=encoder)
                call.assert_called_with('emit_message', 'events', expected.to_bytes())

    def test_emit_rejects_missing_ambiguous_or_invalid_encoders_before_host_call(self):
        class Multiple(Event, Bytesrepr, Json):
            value: U32
        class BadDefault(Event):
            def to_message(self):
                return b'wrong carrier'
        with patch('casthon.contract_api.runtime._call') as call:
            for record, encoder, error in (
                (Event(), None, 'no message encoder'),
                (Multiple(7), None, 'Multiple event encoders'),
                (BadDefault(), None, 'MessageString or MessageBytes'),
                (Multiple(7), lambda event: b'wrong carrier', 'MessageString or MessageBytes'),
                (Multiple(7), lambda event: 'wrong carrier', 'MessageString or MessageBytes'),
                (Multiple(7), lambda event: MessagePayload(), 'MessageString or MessageBytes'),
            ):
                with self.subTest(record=type(record), encoder=encoder), self.assertRaisesRegex(TypeError, error):
                    emit(record, encoder=encoder)
            call.assert_not_called()

    def test_emit_rejects_non_events_and_empty_topic_before_encoding(self):
        with patch('casthon.contract_api.runtime._call') as call, \
             patch.object(Json, 'to_message', side_effect=AssertionError('must not encode')) as encoder:
            for payload in (MessageString('payload'), MessageBytes(b'payload'), b'\0\0\0\0\0', object()):
                with self.subTest(payload=payload), self.assertRaisesRegex(TypeError, 'Expected Event'):
                    emit(payload, encoder=encoder)
            with self.assertRaisesRegex(ValueError, 'topic must not be empty'):
                emit(LedgerChanged({}, None), topic='', encoder=encoder)
            with self.assertRaisesRegex(TypeError, 'Expected MessagePayload'):
                runtime.emit_message('events', LedgerChanged({}, None))
            encoder.assert_not_called()
            call.assert_not_called()

    def test_emit_preserves_catchable_encoding_errors_and_finally(self):
        cleanup = []
        def failing_encoder(event):
            try:
                raise ValueError('encoding failed')
            finally:
                cleanup.append(event)
        record = Credited(self.owner, 1)
        with patch('casthon.contract_api.runtime._call') as call:
            with self.assertRaisesRegex(ValueError, 'encoding failed'):
                emit(record, encoder=failing_encoder)
            with self.assertRaises(ABIError):
                emit(Credited(self.owner, -1))
            self.assertEqual(cleanup, [record])
            call.assert_not_called()

    def test_encoder_selection_native_and_frozen_parity(self):
        source = '''from casthon import Event, MessageEncoder, MessageString, MessageBytes, Bytesrepr, Json, JsonBytes, U32, export
from casthon.contracts import Contract, export_contract
class Custom(MessageEncoder):
    def to_message(self) -> MessageString | MessageBytes:
        return MessageString('custom')
class Binary(Event, Bytesrepr):
    value: U32
class Plain(Event):
    value: U32
class Text(Event, Json):
    value: U32
class Utf8(Event, JsonBytes):
    value: U32
class Multiple(Event, Bytesrepr, Json):
    value: U32
class Default(Multiple):
    def to_message(self) -> MessageString | MessageBytes:
        return Json.to_message(self)
class CustomEvent(Event, Custom):
    value: U32
@export
def call() -> None: pass
@export_contract
class Example(Contract):
    events = (Binary, Plain, Text, Utf8, Multiple, Default, CustomEvent)
'''
        with class_pair(source) as (author, frozen, exports):
            for module in (author, frozen):
                self.assertEqual(module.Plain(7).to_message().value, encode(U32, 7))
                self.assertEqual(module.Binary(7).to_message().value, encode(U32, 7))
                self.assertEqual(module.Text(7).to_message().value, '{"value":7}')
                self.assertEqual(module.Utf8(7).to_message().value, b'{"value":7}')
                self.assertEqual(module.Default(7).to_message().value, '{"value":7}')
                self.assertEqual(module.CustomEvent(7).to_message().value, 'custom')
                with self.assertRaisesRegex(TypeError, 'Multiple'):
                    module.Multiple(7).to_message()
                self.assertEqual(Json.to_message(module.Multiple(7)).value, '{"value":7}')

    def test_encoder_inheritance_with_different_micropython_lookup_is_rejected(self):
        source = '''from casthon import Event, Json, U32, export
from casthon.contracts import Contract, export_contract
class First(Json):
    pass
class Second(Json):
    def json_field(self, name, annotation, value):
        return '"second"'
class Bad(Event, First, Second):
    value: U32
@export
def call() -> None: pass
@export_contract
class Example(Contract):
    events = (Bad,)
'''
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'bad_event.py'
            path.write_text(source)
            with self.assertRaisesRegex(ValueError, 'resolve differently'):
                load_contract(path)
        class First(Json):
            pass
        class Second(Json):
            def json_field(self, name, annotation, value):
                return '"second"'
        class Bad(Event, First, Second):
            value: U32
        with self.assertRaisesRegex(ValueError, 'resolve differently'):
            Bad(7)
