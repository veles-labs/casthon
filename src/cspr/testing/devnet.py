"""Synchronous Python client and resource owner for casper-devnet's MCP API."""

from collections import deque
from dataclasses import asdict, dataclass, field
import fcntl
from functools import partial
import hashlib
import json
import os
from pathlib import Path
import queue
import re
import shutil
import socket
import subprocess
import tempfile
import threading
import time
from typing import Any, Callable, ClassVar, Mapping, Protocol, Sequence, TextIO
import uuid

from ..crypto import PublicKey
from ..key import AccountHash, Key, URef
from ..values import CLValue, SerializedCLValue
from .values import from_json, inspect_value, parse_key, runtime_args
from .prints import ContractPrint, _PrintCapture, _print_note


class DevnetError(RuntimeError):
    """A transport, RPC, submission or network lifecycle failure."""


class DevnetTransport(Protocol):
    def initialize(self) -> None: ...
    def call(self, name: str, arguments: Mapping[str, Any], *, timeout: float = 60) -> Any: ...
    def close(self) -> None: ...


class DevnetClient:
    """A bounded stdio JSON-RPC client; notifications do not block responses."""

    def __init__(self, command: Sequence[str] = ("casper-devnet", "mcp", "--transport", "stdio"),
                 *, print_capture: _PrintCapture | None = None) -> None:
        self._prints = print_capture if print_capture is not None else _PrintCapture()
        self.process = subprocess.Popen(list(command), stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                        stderr=subprocess.PIPE, text=True, bufsize=1)
        self.stderr: deque[str] = deque(maxlen=200)
        self._lock = threading.Lock()
        self._pending: dict[int, queue.Queue[Any]] = {}
        self._next = 0
        self._error: BaseException | None = None
        self._closed = False
        self._reader = threading.Thread(target=self._read, daemon=True)
        self._errors = threading.Thread(target=self._read_errors, daemon=True)
        self._reader.start()
        self._errors.start()

    def _fail(self, error: BaseException) -> None:
        with self._lock:
            self._error = error
            for pending in self._pending.values():
                pending.put(error)
            self._pending.clear()

    def _read(self) -> None:
        assert self.process.stdout is not None
        try:
            for line in self.process.stdout:
                if not line.strip():
                    continue
                message = json.loads(line)
                with self._lock:
                    pending = self._pending.pop(message.get("id"), None)
                if pending is not None:
                    pending.put(message)
            self._fail(DevnetError("casper-devnet closed its response stream"))
        except BaseException as error:
            self._fail(error)

    def _read_errors(self) -> None:
        assert self.process.stderr is not None
        try:
            for line in self.process.stderr:
                self._prints.feed(line)
                self.stderr.append(line[-2000:])
        finally:
            self._prints.close()

    @property
    def print_output(self) -> tuple[ContractPrint, ...]:
        return self._prints.snapshot()

    def request(self, method: str, params: Mapping[str, Any] | None = None, *, timeout: float = 60) -> Any:
        pending: queue.Queue[Any] = queue.Queue()
        with self._lock:
            if self._closed or self._error is not None:
                raise DevnetError("casper-devnet transport is closed") from self._error
            self._next += 1
            identifier = self._next
            self._pending[identifier] = pending
            assert self.process.stdin is not None
            try:
                self.process.stdin.write(json.dumps({"jsonrpc": "2.0", "id": identifier,
                                                     "method": method, "params": dict(params or {})}) + "\n")
                self.process.stdin.flush()
            except BaseException:
                self._pending.pop(identifier, None)
                raise
        try:
            response = pending.get(timeout=timeout)
        except queue.Empty:
            raise TimeoutError(f"casper-devnet {method} timed out after {timeout}s") from None
        finally:
            with self._lock:
                self._pending.pop(identifier, None)
        if isinstance(response, BaseException):
            raise DevnetError("casper-devnet transport failed") from response
        if "error" in response:
            raise DevnetError(str(response["error"]))
        return response["result"]

    def initialize(self) -> None:
        self.request("initialize", {"protocolVersion": "2024-11-05", "capabilities": {},
                                    "clientInfo": {"name": "cspr-py-testing", "version": "0.1.0"}})
        with self._lock:
            assert self.process.stdin is not None
            self.process.stdin.write(json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}) + "\n")
            self.process.stdin.flush()

    def call(self, name: str, arguments: Mapping[str, Any], *, timeout: float = 60) -> Any:
        response = self.request("tools/call", {"name": name, "arguments": dict(arguments)}, timeout=timeout)
        if response.get("isError"):
            raise DevnetError(f"{name}: {response.get('content')}")
        if response.get("structuredContent") is not None:
            return response["structuredContent"]
        content = "\n".join(item["text"] for item in response.get("content", []) if item["type"] == "text")
        return json.loads(content) if content else response

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        if self.process.stdin is not None:
            try:
                self.process.stdin.close()
            except BrokenPipeError:
                pass
        try:
            self.process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self.process.terminate()
            try:
                self.process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=2)
        self._reader.join(timeout=1)
        self._errors.join(timeout=1)
        for stream in (self.process.stdout, self.process.stderr):
            if stream is not None:
                stream.close()

    def __enter__(self) -> "DevnetClient":
        try:
            self.initialize()
        except BaseException:
            self.close()
            raise
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()


class _PortLease:
    """Coordinate the supported devnet port blocks across test processes."""

    def __init__(self, offset: int | None, nodes: int, *, directory: Path | None = None) -> None:
        self.directory = directory or Path(tempfile.gettempdir()) / f"cspr-py-ports-{os.getuid()}"
        self.directory.mkdir(parents=True, exist_ok=True)
        self.files: list[TextIO] = []
        self.offset = -1
        for candidate in ((offset,) if offset is not None else (0, 1000, 2000)):
            if not 0 <= candidate <= 2900:
                raise ValueError("Devnet port offset must be between 0 and 2900")
            handles: list[TextIO] = []
            try:
                ports = [11100 + candidate, 32000 + candidate]
                ports += [base + 100 + node + candidate for base in (11000, 14000, 18000, 22000, 28000)
                          for node in range(1, nodes + 1)]
                for port in sorted(set(ports)):
                    handle = (self.directory / f"{port}.lock").open("a+")
                    handles.append(handle)
                    fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
                sockets = []
                try:
                    for port in ports:
                        sock = socket.socket()
                        sockets.append(sock)
                        sock.bind(("127.0.0.1", port))
                finally:
                    for sock in sockets:
                        sock.close()
            except (BlockingIOError, OSError):
                for opened in handles:
                    opened.close()
                continue
            self.files, self.offset = handles, candidate
            return
        raise DevnetError("No free devnet port block; wait for another test class to finish or set port_offset")

    def close(self) -> None:
        for handle in self.files:
            handle.close()
        self.files.clear()


@dataclass(frozen=True)
class TestAccount:
    __test__: ClassVar[bool] = False
    alias: str
    path: str
    account_hash: AccountHash
    public_key: PublicKey
    _load_secret: Callable[[], bytes] = field(repr=False, compare=False)

    @property
    def secret_key(self) -> bytes:
        """PEM bytes, derived lazily by casper-devnet; never included in repr."""
        return self._load_secret()


@dataclass(frozen=True)
class TransactionReceipt:
    transaction_hash: str
    raw: dict[str, Any]
    print_output: tuple[ContractPrint, ...] = field(default=(), repr=False)

    def _assertion(self, message: str) -> AssertionError:
        error = AssertionError(message)
        start = self.print_output[0].sequence - 1 if self.print_output else 0
        note = _print_note(self.print_output, start)
        if note:
            error.add_note(note)
        return error

    @property
    def execution(self) -> dict[str, Any]:
        value = self.raw.get("execution_info", {}).get("execution_result")
        if not isinstance(value, dict):
            raise DevnetError("Transaction has no execution result")
        result = value.get("Version2", value.get("V2", value))
        if not isinstance(result, dict) or "error_message" not in result:
            raise DevnetError("Unsupported transaction execution result")
        return result

    @property
    def error(self) -> str | None:
        return self.execution["error_message"]  # type: ignore[no-any-return]

    @property
    def consumed(self) -> int:
        return int(self.execution["consumed"])

    @property
    def cost(self) -> int:
        return int(self.execution["cost"])

    @property
    def block_hash(self) -> str | None:
        return self.raw.get("execution_info", {}).get("block_hash")  # type: ignore[no-any-return]

    def assert_success(self) -> "TransactionReceipt":
        if self.error is not None:
            raise self._assertion(f"Transaction {self.transaction_hash} failed: {self.error}")
        return self

    def assert_failure(self, pattern: str) -> "TransactionReceipt":
        if self.error is None or re.search(pattern, self.error) is None:
            raise self._assertion(f"Expected execution error matching {pattern!r}, got {self.error!r}")
        return self


@dataclass(frozen=True)
class QueryResult:
    raw: dict[str, Any]

    @property
    def stored_value(self) -> dict[str, Any]:
        return self.raw["stored_value"]  # type: ignore[no-any-return]

    @property
    def cl_value(self) -> SerializedCLValue:
        if "CLValue" not in self.stored_value:
            raise TypeError("Query does not contain a CLValue; inspect stored_value")
        return from_json(self.stored_value["CLValue"])

    @property
    def value(self) -> Any:
        return inspect_value(self.cl_value.to_bytes())[1]

    @property
    def named_keys(self) -> dict[str, Key]:
        for kind in ("Account", "Contract", "AddressableEntity"):
            if kind in self.stored_value:
                fields = self.stored_value[kind]
                if "named_keys" not in fields:
                    raise NotImplementedError("This entity stores named keys separately; use query()/rpc()")
                return {item["name"]: parse_key(item["key"]) for item in fields["named_keys"]}
        raise TypeError("Query does not contain an account or contract")


class DevnetNetwork:
    def __init__(self, *, name: str | None = None, protocol_version: str = "2.2.0",
                 seed: str = "cspr-py-tests", nodes: int = 4, users: int = 2,
                 port_offset: int | None = None, timeout: float = 120,
                 diagnostics: Path | str | None = None, owned: bool = True,
                 client: DevnetTransport | None = None, binary: str = "casper-devnet",
                 custom_asset: str | None = None) -> None:
        if not 1 <= nodes <= 16 or users < 1 or timeout <= 0:
            raise ValueError("Require 1–16 nodes, at least one user and a positive timeout")
        self.name = name or "cspr-py-test-" + uuid.uuid4().hex[:12]
        self.protocol_version, self.seed = protocol_version, seed
        self.nodes, self.users, self.port_offset = nodes, users, port_offset
        self.timeout, self.owned, self.binary = timeout, owned, binary
        self.custom_asset = custom_asset
        self._prints = client._prints if isinstance(client, DevnetClient) else _PrintCapture()
        self.diagnostics = Path(diagnostics or Path.cwd() / ".cache/cspr-testing/live" / self.name)
        self.accounts: dict[str, TestAccount] = {}
        self.transactions: list[TransactionReceipt] = []
        self._client, self._owns_client = client, client is None
        self._lease: _PortLease | None = None
        self._attempted = self._started = self._stopped = False
        self._derived: dict[tuple[str, str], TestAccount] = {}
        self._funded: set[str] = set()

    def tool(self, name: str, **arguments: Any) -> Any:
        if self._client is None:
            raise DevnetError("Network is not started")
        return self._client.call(name, {"network_name": self.name, **arguments}, timeout=self.timeout + 10)

    def start(self) -> "DevnetNetwork":
        if self._started:
            return self
        if self._stopped:
            raise DevnetError("Create a new network owner after stop()")
        try:
            if self.owned:
                self._lease = _PortLease(self.port_offset, self.nodes)
                self.port_offset = self._lease.offset
            if self._client is None:
                if shutil.which(self.binary) is None:
                    raise DevnetError(f"Required executable is missing: {self.binary}")
                self._client = DevnetClient((self.binary, "mcp", "--transport", "stdio"), print_capture=self._prints)
                self._client.initialize()
            if self.owned:
                existing = self._client.call("list_networks", {}, timeout=self.timeout)
                if any(row["network_name"] == self.name for row in existing.get("networks", [])):
                    raise DevnetError("Refusing to replace an existing network; attach with owned=False")
                self._attempted = True
                selector = {"custom_asset": self.custom_asset} if self.custom_asset else {"asset": self.protocol_version}
                response = self.tool("spawn_network", **selector, seed=self.seed,
                                     node_count=self.nodes, users=self.users, port_offset=self.port_offset,
                                     delay=3, force_setup=True)
                if response.get("already_running"):
                    self._attempted = False
                    raise DevnetError("Refusing to claim ownership of an already-running network")
            ready = self.tool("wait_network_ready", timeout_seconds=int(self.timeout))
            if not ready.get("ready"):
                raise DevnetError("Devnet did not become ready")
            deadline = time.monotonic() + self.timeout
            while True:
                try:
                    self.rpc("chain_get_state_root_hash")
                    break
                except DevnetError:
                    if time.monotonic() >= deadline:
                        raise
                    time.sleep(0.2)
            for row in self.tool("list_derived_accounts"):
                key = row.get("public_key") or self._derive(row["path"], "public-key")
                path = row["path"]
                self.accounts[row["alias"]] = TestAccount(row["alias"], path,
                    AccountHash(bytes.fromhex(row["account_hash"].removeprefix("account-hash-"))),
                    PublicKey.from_bytes(bytes.fromhex(key)), partial(self._load_secret, path))
            self._started = True
            return self
        except BaseException as error:
            try:
                self.stop()
            except BaseException as cleanup:
                error.add_note(f"Devnet cleanup also failed: {cleanup}")
            raise

    def _derive(self, path: str, material: str) -> str:
        result = subprocess.run([self.binary, "derive", self.name, "--path", path,
                                 "--seed", self.seed, "--" + material], capture_output=True,
                                text=True, timeout=self.timeout)
        if result.returncode:
            raise DevnetError(f"Account derivation failed: {result.stderr.strip()}")
        return result.stdout.strip()

    def _load_secret(self, path: str) -> bytes:
        return self._derive(path, "secret-key").encode()

    def account(self, alias: str, *, scope: str = "") -> TestAccount:
        """Derive a stable identity from seed, scope and alias, independent of order."""
        key = scope, alias
        if key not in self._derived:
            digest = hashlib.sha256(json.dumps(key).encode()).digest()
            first, second = (int.from_bytes(digest[index:index + 4], "big") & 0x7fffffff for index in (0, 4))
            path = f"m/44'/506'/0'/1/{first}/{second}"
            account = AccountHash(bytes.fromhex(self._derive(path, "account-hash").removeprefix("account-hash-")))
            public = PublicKey.from_bytes(bytes.fromhex(self._derive(path, "public-key")))
            self._derived[key] = TestAccount(alias, path, account, public, partial(self._load_secret, path))
        return self._derived[key]

    def funded_account(self, alias: str, *, scope: str, motes: int = 10_000 * 10**9) -> TestAccount:
        account = self.account(alias, scope=scope)
        if account.path not in self._funded:
            faucet = self.accounts.get("user-1")
            if faucet is None:
                raise DevnetError("Network has no user-1 funding account")
            self.transfer(faucet, account, motes=motes).assert_success()
            self._funded.add(account.path)
        return account

    def rpc(self, method: str, params: Mapping[str, Any] | None = None) -> dict[str, Any]:
        response = self.tool("rpc_query", node_id=1, method=method, params=dict(params or {}))
        if response.get("error") is not None:
            raise DevnetError(f"{method}: {response['error']}")
        return response.get("result", response)  # type: ignore[no-any-return]

    @property
    def print_output(self) -> tuple[ContractPrint, ...]:
        """Recent node prints in arrival order; the stream has no transaction IDs."""
        return self._prints.snapshot()

    @property
    def print_cursor(self) -> int:
        return self._prints.cursor

    def prints_since(self, cursor: int) -> tuple[ContractPrint, ...]:
        return self._prints.snapshot(cursor)

    def wait_for_print(self, pattern: str, *, since: int = 0, node_id: int | None = None,
                       timeout: float = 5) -> ContractPrint:
        try:
            return self._prints.wait(pattern, since=since, node_id=node_id, timeout=timeout)
        except TimeoutError as error:
            self.note_prints(error, since=since)
            raise

    def note_prints(self, error: BaseException, *, since: int = 0) -> None:
        note = _print_note(self.prints_since(since), since)
        if note and not any(existing.startswith("Captured Casper prints")
                            for existing in getattr(error, "__notes__", ())):
            error.add_note(note + "\nCapture file: " + str(self.diagnostics / "contract-prints.jsonl"))

    def _wait(self, transaction_hash: str, *, print_since: int = 0) -> TransactionReceipt:
        response = self.tool("wait_transaction", node_id=1, transaction_hash=transaction_hash,
                             timeout_seconds=int(self.timeout), poll_interval_millis=500)
        receipt = TransactionReceipt(transaction_hash, response, self.prints_since(print_since))
        receipt.execution
        self.transactions.append(receipt)
        return receipt

    def submit(self, transaction: Mapping[str, Any], *, signer: TestAccount) -> TransactionReceipt:
        cursor = self.print_cursor
        response = self.tool("send_transaction_signed", node_id=1, signer_path=signer.path,
                             transaction=dict(transaction))
        return self._wait(response["transaction_hash"], print_since=cursor)

    def deploy(self, wasm: Path | str, *, signer: TestAccount,
               args: Mapping[str, CLValue] | None = None, install: bool = True,
               payment: int = 800_000_000_000) -> TransactionReceipt:
        made = self.tool("make_transaction_session_wasm", node_id=1, signer_path=signer.path,
                         wasm_path=str(Path(wasm).resolve()), session_args=runtime_args(dict(args or {})),
                         is_install_upgrade=install, payment_amount=payment)
        return self.submit(made["transaction"], signer=signer)

    def call(self, contract: Key | str, entry: str, *, signer: TestAccount,
             args: Mapping[str, CLValue] | None = None, payment: int = 100_000_000_000) -> TransactionReceipt:
        made = self.tool("make_transaction_contract_call", node_id=1, signer_path=signer.path,
                         transaction_contract_hash=str(contract), session_entry_point=entry,
                         session_args=runtime_args(dict(args or {})), payment_amount=payment)
        return self.submit(made["transaction"], signer=signer)

    def transfer(self, sender: TestAccount, recipient: TestAccount, *, motes: int,
                 payment: int = 100_000_000) -> TransactionReceipt:
        if type(motes) is not int or motes <= 0:
            raise ValueError("Transfer motes must be a positive integer")
        cursor = self.print_cursor
        sent = self.tool("transfer_tokens", node_id=1, from_path=sender.path, to_path=recipient.path,
                         amount=str(motes), payment_amount=payment)
        return self._wait(sent["transaction_hash"], print_since=cursor)

    def query(self, key: Key | str | TestAccount, *, path: Sequence[str] = (),
              state_root_hash: str | None = None, block_id: str | None = None) -> QueryResult:
        if isinstance(key, TestAccount):
            key = key.account_hash
        value = self.tool("rpc_query_global_state", node_id=1, key=str(key), path=list(path),
                          state_root_hash=state_root_hash, block_id=block_id)
        return QueryResult(value)

    def named_keys(self, key: Key | str | TestAccount) -> dict[str, Key]:
        return self.query(key).named_keys

    def dictionary(self, seed: URef, item: str, *, state_root_hash: str | None = None) -> QueryResult:
        state_root_hash = state_root_hash or self.rpc("chain_get_state_root_hash")["state_root_hash"]
        response = self.rpc("state_get_dictionary_item", {"state_root_hash": state_root_hash,
            "dictionary_identifier": {"URef": {"seed_uref": str(seed), "dictionary_item_key": item}}})
        return QueryResult(response)

    def balance(self, key: Key | str | TestAccount, *, state_root_hash: str | None = None) -> int:
        if isinstance(key, TestAccount):
            key = key.account_hash
        response = self.tool("rpc_query_balance", node_id=1, purse_identifier=str(key), state_root_hash=state_root_hash)
        for name in ("available_balance", "total_balance", "balance"):
            if name in response:
                return int(response[name])
        raise DevnetError("Balance response has no recognized balance field")

    def stop(self) -> None:
        if self._stopped:
            return
        self._stopped = True
        errors = []
        report: dict[str, Any] = {"network": self.name, "protocolVersion": self.protocol_version,
            "owned": self.owned, "portOffset": self.port_offset,
            "transactions": [{"hash": receipt.transaction_hash, "response": receipt.raw} for receipt in self.transactions]}
        try:
            self.diagnostics.mkdir(parents=True, exist_ok=True)
            if self._attempted and self._client is not None:
                for node in range(1, self.nodes + 1):
                    try:
                        logs = self.tool("get_node_logs", node_id=node, stream="stdout", limit=100)
                        (self.diagnostics / f"node-{node}.json").write_text(json.dumps(logs, indent=2) + "\n")
                    except Exception:
                        pass
        finally:
            try:
                if self.owned and self._attempted and self._client is not None:
                    # Stop first and retain runtime files for inspection. The
                    # launcher's purge path races child file removal on exit.
                    self.tool("despawn_network", purge=False)
                    report["networkStopped"] = True
                    report["networkFilesRetained"] = True
            except Exception as error:
                errors.append(str(error))
            finally:
                if self._lease is not None:
                    self._lease.close()
                if self._owns_client and self._client is not None:
                    if isinstance(self._client, DevnetClient):
                        report["transportStderr"] = list(self._client.stderr)
                    self._client.close()
                lines = self.print_output
                report["contractPrintLines"] = len(lines)
                report["contractPrintDropped"] = self.print_cursor - len(lines)
                report["contractPrintOutput"] = "contract-prints.jsonl"
                report["cleanupErrors"] = errors
                self.diagnostics.mkdir(parents=True, exist_ok=True)
                (self.diagnostics / "contract-prints.jsonl").write_text(
                    "".join(json.dumps(asdict(line), ensure_ascii=False) + "\n" for line in lines))
                (self.diagnostics / "report.json").write_text(json.dumps(report, indent=2) + "\n")
        if errors:
            raise DevnetError("; ".join(errors))

    def __enter__(self) -> "DevnetNetwork":
        return self.start()

    def __exit__(self, kind: Any, error: BaseException | None, traceback: Any) -> None:
        try:
            self.stop()
        except Exception as cleanup:
            if error is None:
                raise
            error.add_note(f"Devnet cleanup also failed: {cleanup}")
