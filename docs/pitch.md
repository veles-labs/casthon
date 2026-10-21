# Casthon, in a minute

Casthon brings Python to Casper smart contracts. Write a class, annotate its
arguments and state, then build it into Wasm. The SDK handles Casper values and
host calls; your methods keep ordinary Python control flow.

That matters when contracts grow past a single function. Ownership and pause
controls can live in reusable classes. A token can inherit CEP-18. A session can
import a contract's Python ABI to call its deployed hash. You can test that code
with a mock host on CPython, then run the compiled contract and a local devnet.

Exceptions behave like Python exceptions. Contract code can catch a failure and
recover, and `finally` runs before completion. If an API error escapes the
invocation, the outer adapter turns it into a Casper revert and rolls back state.

The compiler freezes Python with MicroPython and produces Casper-compatible
Wasm. The Rust `casthon` command handles builds, templates and artifact inspection;
`test` and `check` run pytest and mypy.

## A short demo

Open [hello.py](../contracts/hello.py). Its class has one persistent counter and
one typed entrypoint. Point out the normal return, the caught empty-name error,
and the uncaught user error. The installer is an ordinary top-level function.

From a configured checkout:

```sh
./target/release/casthon build hello
./target/release/casthon inspect build/hello.wasm
```

For a quick native demonstration, run this with the checkout's Python environment:

```python
from cspr.testing import MockHost, use_host
from contracts.hello import Hello

with use_host(MockHost()):
    hello = Hello(calls=0)
    assert hello.greet("World") == "Hello, World!"
    assert hello.greet("") == "Hello, stranger!"
    assert hello.calls.read() == 2
```

Those are ordinary method calls. Use `ContractHarness` when demonstrating
argument decoding or transaction rollback; the [testing guide](testing.md)
shows that boundary. The `finally` write after an escaping error is rolled back
only when there is an invocation/transaction boundary around the call.

Then open [Counter](../contracts/counter.py) to show mixins, or
[MyToken](../contracts/my_token.py) for a fuller CEP-18 contract.

## Where it stands

This is a developer preview with native, compiled-Wasm and live-network tests.
The default port uses pristine MicroPython with Asyncify. Builds include an
interpreter, and Python support follows the documented authoring profile.

The next milestone is distribution: install the CLI and SDK, generate a project,
and deploy a contract without needing this repository checked out. The
[architecture guide](architecture.md) records the current boundaries and the
remaining work.
