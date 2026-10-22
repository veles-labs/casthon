"""unittest integration; the same network owner also works in pytest fixtures."""

import os
from pathlib import Path
from typing import Any, ClassVar, cast
import unittest

from .build import build_contract
from .devnet import DevnetNetwork, TestAccount


class _PrintResult:
    """Decorate errors before unittest/pytest formats their tracebacks."""

    def __init__(self, result: unittest.TestResult, network: DevnetNetwork) -> None:
        self.result, self.network, self.cursor = result, network, network.print_cursor

    def __getattr__(self, name: str) -> Any:
        return getattr(self.result, name)

    def _note(self, error: tuple[Any, Any, Any]) -> None:
        if isinstance(error[1], BaseException):
            self.network.note_prints(error[1], since=self.cursor)

    def addError(self, test: unittest.TestCase, error: tuple[Any, Any, Any]) -> None:
        self._note(error)
        self.result.addError(test, error)

    def addFailure(self, test: unittest.TestCase, error: tuple[Any, Any, Any]) -> None:
        self._note(error)
        self.result.addFailure(test, error)

    def addSubTest(self, test: unittest.TestCase, subtest: unittest.TestCase,
                   error: tuple[Any, Any, Any] | None) -> None:
        if error is not None:
            self._note(error)
        self.result.addSubTest(test, subtest, error)


class LiveNetworkTest(unittest.TestCase):
    protocol_version: ClassVar[str] = "2.2.0"
    network_seed: ClassVar[str] = "cspr-py-tests"
    node_count: ClassVar[int] = 4
    user_count: ClassVar[int] = 2
    network_timeout: ClassVar[float] = 120
    port_offset: ClassVar[int | None] = None
    project_root: ClassVar[Path] = Path.cwd()
    runtime: ClassVar[str] = "asyncify"
    profile: ClassVar[str] = "debug"
    binary: ClassVar[str] = "casper-devnet"
    custom_asset: ClassVar[str | None] = None
    network: ClassVar[DevnetNetwork]

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        if os.environ.get("CSPR_LIVE_TESTS") != "1":
            raise unittest.SkipTest("Live tests require CSPR_LIVE_TESTS=1 (or make test-live)")
        cls.network = DevnetNetwork(protocol_version=cls.protocol_version, seed=cls.network_seed,
                                   binary=os.environ.get("CSPR_DEVNET_BIN", cls.binary), custom_asset=cls.custom_asset,
                                   nodes=cls.node_count, users=cls.user_count,
                                   port_offset=cls.port_offset, timeout=cls.network_timeout,
                                   diagnostics=cls.project_root / ".cache/cspr-testing/live" /
                                   (cls.__module__ + "." + cls.__qualname__))
        cls.addClassCleanup(cls.network.stop)
        cls.network.start()

    def run(self, result: unittest.TestResult | None = None) -> unittest.TestResult:
        original = result
        if result is None:
            result = self.defaultTestResult()
            result.startTestRun()
        try:
            network = getattr(self, "network", None)
            wrapped = cast(unittest.TestResult, _PrintResult(result, network)) if isinstance(network, DevnetNetwork) else result
            super().run(wrapped)
            return result
        finally:
            if original is None:
                result.stopTestRun()

    def funded_account(self, alias: str, *, motes: int = 10_000 * 10**9) -> TestAccount:
        return self.network.funded_account(alias, scope=self.id(), motes=motes)

    @classmethod
    def build(cls, source: str | Path) -> Path:
        return build_contract(source, project_root=cls.project_root, runtime=cls.runtime, profile=cls.profile)
