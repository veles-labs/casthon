import os

from cspr import CLU32
from cspr.testing import ContractHarness, MockHost
from contracts import bench_counter


def deploy() -> ContractHarness:
    host = MockHost(strict_arguments=True)
    ContractHarness(bench_counter, host=host).invoke("call")
    return ContractHarness(
        bench_counter.BenchCounter,
        host=host,
        contract=host.accounts[host.caller]["bench_counter"],
    )


def test_initial_value() -> None:
    assert deploy().invoke("get").value == 0


def test_set() -> None:
    counter = deploy()
    counter.invoke("set", {"value": CLU32(42)})
    assert counter.invoke("get").value == 42


def test_increment() -> None:
    counter = deploy()
    counter.invoke("increment_by", {"amount": CLU32(7)})
    assert counter.invoke("get").value == 7


def test_repeated_increments() -> None:
    counter = deploy()
    for _ in range(10):
        counter.invoke("increment_by", {"amount": CLU32(3)})
    assert counter.invoke("get").value == 30


def test_independent_deployments() -> None:
    first, second = deploy(), deploy()
    first.invoke("set", {"value": CLU32(99)})
    assert first.invoke("get").value == 99
    assert second.invoke("get").value == 0


def test_version() -> None:
    assert deploy().invoke("version").value == int(os.environ.get("BENCHMARK_EXPECTED_VERSION", "1"))
