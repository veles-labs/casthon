from casthon import CLBool
from casthon.testing import ContractHarness, MockHost, use_host

from contracts import flipper


def test_flipper_is_ordinary_python():
    with use_host(MockHost()):
        contract = flipper.Flipper(value=False)
        assert contract.get() is False
        contract.flip()
        assert contract.get() is True


def test_install_and_invoke_through_the_contract_boundary():
    host = MockHost(strict_arguments=True)
    installer = ContractHarness(flipper, host=host)
    installer.invoke("call", {"initial": CLBool(True)})

    contract_hash = host.accounts[host.caller]["flipper"]
    contract = ContractHarness(flipper.Flipper, host=host, contract=contract_hash)
    assert contract.invoke("get").value is True
    contract.invoke("flip")
    assert contract.invoke("get").value is False
