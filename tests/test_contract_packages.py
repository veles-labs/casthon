"""Package-owned version management with initialized contract state."""

import unittest

from casthon import ApiError, CLString, ContractHash, ContractPackageHash, MessageTopicOperation, UserError
from casthon.contract_api import storage
from casthon.contract_api.runtime import named_keys
from casthon.entry_points import serialize_entry_points
from casthon.testing import ContractHarness, MockHost, use_host
from contracts import hello
from contracts.counter import Counter


class ContractPackageTests(unittest.TestCase):
    def setUp(self):
        self.host = MockHost(strict_arguments=True)

    def test_add_version_preserves_inherited_abi_and_instance_state(self):
        with use_host(self.host):
            package, _ = storage.create_contract_package_at_hash()
            named_keys['session_only'] = package
            state = Counter(7)
            contract, version = package.add_contract_version(state, message_topics=('events',))
        self.assertIsInstance(contract, ContractHash)
        self.assertEqual(version, 1)
        self.assertEqual(self.host.contracts[contract], state.named_keys)
        self.assertEqual(set(self.host.accounts[self.host.caller]), {'session_only'})
        self.assertEqual(
            serialize_entry_points(list(self.host.entry_points[contract].values())),
            serialize_entry_points(Counter.entry_points()))
        self.assertEqual(self.host.message_topics[contract], {'events'})
        harness = ContractHarness(Counter, host=self.host, contract=contract)
        self.assertEqual(harness.invoke('get').value, 7)
        harness.invoke('pause')
        self.assertTrue(harness.invoke('is_paused').value)

    def test_versions_keep_separate_state_and_inherit_message_topics(self):
        with use_host(self.host):
            package, _ = storage.create_contract_package_at_hash()
            first, first_version = package.add_contract_version(Counter(1), message_topics=('events',))
            second, second_version = package.add_contract_version(
                Counter(2), message_topics={'audit': MessageTopicOperation.ADD})
        self.assertEqual((first_version, second_version), (1, 2))
        self.assertEqual(self.host.packages[bytes(package)], [first, second])
        self.assertEqual(self.host.message_topics[first], {'events'})
        self.assertEqual(self.host.message_topics[second], {'events', 'audit'})
        for contract, count in ((first, 1), (second, 2)):
            harness = ContractHarness(Counter, host=self.host, contract=contract)
            self.assertEqual(harness.invoke('get').value, count)

    def test_named_reference_restores_package_methods_and_controls_its_version(self):
        with use_host(self.host):
            package, _ = storage.create_contract_package_at_hash()
            stored = named_keys.reference('package', ContractPackageHash)
            stored.set(package)
            restored = stored.get()
            self.assertIsInstance(restored, ContractPackageHash)
            contract, _ = restored.add_contract_version(Counter())
            restored.disable_contract_version(contract)
            self.assertIn(contract, self.host.disabled)
            restored.enable_contract_version(contract)
            self.assertNotIn(contract, self.host.disabled)

    def test_package_errors_remain_catchable_and_run_finally(self):
        with use_host(self.host):
            package, _ = storage.create_contract_package_at_hash()
            state = Counter()
            contract, _ = package.add_contract_version(state)
            for operation, argument in (
                ('add_contract_version', state),
                ('disable_contract_version', contract),
                ('enable_contract_version', contract),
            ):
                cleanup = []
                failure = ApiError(17)
                self.host.fail_next(operation, failure)
                with self.subTest(operation=operation), self.assertRaises(ApiError) as error:
                    try:
                        getattr(package, operation)(argument)
                    finally:
                        cleanup.append('done')
                self.assertEqual(error.exception.code, failure.code)
                self.assertEqual(cleanup, ['done'])
            self.assertEqual(self.host.packages[bytes(package)], [contract])
            self.assertEqual(self.host.disabled, set())

    def test_add_version_rejects_uninitialized_or_unrelated_objects_before_host_calls(self):
        package = ContractPackageHash(bytes(32))
        with use_host(self.host):
            for value in (Counter, ContractHash(bytes(32)), object()):
                with self.subTest(value=value), self.assertRaises(TypeError):
                    package.add_contract_version(value)
        self.assertEqual(self.host.calls, [])

    def test_hello_installer_binds_typed_references_and_runs_cleanup(self):
        session = ContractHarness(hello, host=self.host)
        session.invoke('call')
        with use_host(self.host):
            contract = hello.installed.get()
            package = hello.installed_package.get()
            self.assertIsInstance(package, ContractPackageHash)
            self.assertEqual(self.host.packages[bytes(package)], [contract])
        self.assertEqual(set(self.host.accounts[self.host.caller]),
                         {'hello', 'hello_package', 'hello_access'})
        harness = ContractHarness(hello.Hello, host=self.host, contract=contract)
        self.assertEqual(harness.invoke('greet', {'name': CLString('World')}).value, 'Hello, World!')
        self.assertEqual(harness.invoke('greet', {'name': CLString('')}).value, 'Hello, stranger!')
        with self.assertRaises(UserError):
            harness.invoke('greet', {'name': CLString('x' * 65)})
        with self.host.context(contract=contract), use_host(self.host):
            self.assertEqual(hello.Hello.bind().calls, 2)


if __name__ == '__main__':
    unittest.main()
