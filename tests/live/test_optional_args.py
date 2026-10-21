"""Installed node metadata and typed remote omission versus encoded Option::None."""

from cspr import CLKey, CLString, CLU32
from cspr.testing import LiveNetworkTest


class TestOptionalArgs(LiveNetworkTest):
    def test_optional_arguments_are_dynamic_and_typed_calls_preserve_none(self):
        alice = self.funded_account("presence")
        self.network.deploy(self.build("contracts/typed_exports.py"), signer=alice).assert_success()
        contract = self.network.named_keys(alice)["py_typed_exports"]
        points = self.network.query(contract).stored_value["Contract"]["entry_points"]
        for point in points:
            if point["name"].startswith("presence"):
                self.assertEqual(point["args"], [])
        self.network.deploy(self.build("tests/fixtures/optional_arg_session.py"), signer=alice, install=False,
                            args={"contract": CLKey(contract)}).assert_success()
        self.network.call(contract, "presence_number", signer=alice,
                          args={"value": CLU32(0)}).assert_success()
        self.network.call(contract, "presence", signer=alice,
                          args={"value": CLString("bad")}).assert_failure("InvalidArgument|invalid argument")
