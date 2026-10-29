"""Run explicitly with casthon test --live."""

from casthon import CLBool
from casthon.testing import LiveNetworkTest


class TestFlipperOnCasper(LiveNetworkTest):
    def test_deploy_flip_and_query_state(self):
        alice = self.funded_account("alice")
        wasm = self.build("contracts/flipper.py")
        self.network.deploy(
            wasm,
            signer=alice,
            args={"initial": CLBool(False)},
        ).assert_success()

        contract = self.network.named_keys(alice)["flipper"]
        self.assertIs(self.network.query(contract, path=["value"]).value, False)
        self.network.call(contract, "flip", signer=alice).assert_success()
        self.assertIs(self.network.query(contract, path=["value"]).value, True)
