"""Read-only local execution through the casper-cli simulator."""

from dataclasses import dataclass
import json
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
from typing import Any, Mapping

from ..key import ContractEntity, Hash, Key, URef
from ..values import CLValue, SerializedCLValue
from .devnet import DevnetError, DevnetNetwork, TestAccount
from .values import from_json, inspect_value, runtime_args


@dataclass(frozen=True)
class SimulationResult:
    raw: dict[str, Any]

    @property
    def error(self) -> str | None:
        return self.raw["error"]  # type: ignore[no-any-return]

    @property
    def consumed(self) -> int:
        return int(self.raw["gasConsumed"])

    @property
    def block_height(self) -> int:
        return self.raw["blockHeight"]  # type: ignore[no-any-return]

    @property
    def state_root_hash(self) -> str:
        return self.raw["stateRootHash"]  # type: ignore[no-any-return]

    @property
    def cl_value(self) -> SerializedCLValue | None:
        value = self.raw["returnValue"]
        return None if value is None else from_json(value)

    @property
    def value(self) -> Any:
        self.assert_success()
        value = self.cl_value
        return None if value is None else inspect_value(value.to_bytes())[1]

    def assert_success(self) -> "SimulationResult":
        if self.error is not None:
            raise AssertionError(f"Simulation failed: {self.error}")
        return self

    def assert_failure(self, pattern: str) -> "SimulationResult":
        if self.error is None or re.search(pattern, self.error) is None:
            raise AssertionError(f"Expected simulation error matching {pattern!r}, got {self.error!r}")
        return self


def _kind_name(kind: Any) -> str:
    if isinstance(kind, str):
        return kind
    name, children = next(iter(kind.items()))
    if name == "ByteArray":
        return f"ByteArray[{children}]"
    if name in ("Option", "List"):
        children = [children]
    elif name in ("Map", "Result"):
        children = list(children.values())
    return str(name) + "<" + ",".join(_kind_name(child) for child in children) + ">"


def _arguments(args: Mapping[str, CLValue]) -> list[str]:
    result: list[str] = []
    for name, value in runtime_args(dict(args)):
        kind, payload = value["cl_type"], bytes.fromhex(value["bytes"])
        if kind == "Bool":
            text = "true" if payload == b"\1" else "false"
        elif kind in ("I32", "I64", "U8", "U32", "U64"):
            text = str(int.from_bytes(payload, "little", signed=kind.startswith("I")))
        elif kind in ("U128", "U256", "U512"):
            text = str(int.from_bytes(payload[1:], "little"))
        elif kind == "String":
            text = payload[4:].decode("utf-8")
        elif kind == "Key":
            text = str(Key.from_bytes(payload))
        elif kind == "URef":
            text = str(URef(payload[:32], payload[32]))
        elif kind == "PublicKey":
            text = payload.hex()
        elif kind == "Unit":
            text = "()"
        else:
            text = "0x" + payload.hex()
        escaped = name.replace("\\", "\\\\").replace(":", "\\:").replace("=", "\\=")
        result.extend(("--arg", f"{escaped}:{_kind_name(kind)}={text}"))
    return result


def simulate(network: DevnetNetwork, contract: Key | str, entry: str, *, caller: TestAccount,
             args: Mapping[str, CLValue] | None) -> SimulationResult:
    if not network._started or network._stopped:
        raise DevnetError("Network is not running")
    binary = shutil.which(network.casper_cli)
    if binary is None:
        raise DevnetError(f"Simulation requires Veles Labs casper-cli: {network.casper_cli}")
    if isinstance(contract, (Hash, ContractEntity)):
        target = bytes(contract)[-32:].hex()
    elif isinstance(contract, str):
        target = contract.removeprefix("hash-")
    else:
        raise TypeError("Simulation requires a contract hash or contract entity")
    arguments = _arguments(args or {})
    endpoint = network.rpc_endpoint
    if endpoint is None:
        if network.port_offset is None:
            raise DevnetError("Attached-network simulation requires rpc_endpoint or port_offset")
        endpoint = f"http://127.0.0.1:{11101 + network.port_offset}/rpc"
    chain_name = network.rpc("info_get_status").get("chainspec_name")
    if not isinstance(chain_name, str) or not chain_name:
        raise DevnetError("info_get_status has no chainspec_name for simulation")
    cache = network.diagnostics.resolve() / "simulation-cache"
    config = (f'active = "live"\n[storage]\ntype = "file"\nroot_path = {json.dumps(str(cache))}\n'
              f'[networks.live]\nchain_name = {json.dumps(chain_name)}\nrpc = {json.dumps(endpoint)}\n'
              'rest = ""\nsse = ""\nbinary_port = ""\n')
    with network._simulation_lock, tempfile.TemporaryDirectory(prefix="casthon-simulation-") as directory:
        path = Path(directory) / "config.toml"
        path.write_text(config)
        try:
            process = subprocess.run([binary, "--no-interactive", "--config-path", str(path),
                "transaction", "call", target, entry, "--simulate", "--raw",
                "--initiator", str(caller.account_hash), *arguments],
                stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=network.timeout)
        except (OSError, subprocess.TimeoutExpired) as error:
            raise DevnetError(f"Could not run casper-cli simulation: {error}") from error
    try:
        raw = json.loads(process.stdout)
        if (not isinstance(raw, dict) or type(raw.get("schemaVersion")) is not int or raw["schemaVersion"] != 1
                or type(raw.get("success")) is not bool or "error" not in raw or "returnValue" not in raw
                or type(raw.get("blockHeight")) is not int or raw["blockHeight"] < 0
                or not isinstance(raw.get("stateRootHash"), str)
                or re.fullmatch(r"[0-9a-fA-F]{64}", raw["stateRootHash"]) is None
                or not isinstance(raw.get("gasConsumed"), str) or not raw["gasConsumed"].isascii()
                or not raw["gasConsumed"].isdecimal()
                or (raw["returnValue"] is not None and (not isinstance(raw["returnValue"], dict)
                    or not isinstance(raw["returnValue"].get("cl_type"), (str, dict))
                    or not isinstance(raw["returnValue"].get("bytes"), str)))
                or not (raw["error"] is None or isinstance(raw["error"], str))
                or raw["success"] != (raw["error"] is None)
                or (process.returncode == 0) != raw["success"]):
            raise ValueError("invalid simulation result")
    except (ValueError, TypeError) as error:
        raise DevnetError(f"casper-cli simulation did not return a valid result: {process.stderr.strip()}") from error
    result = SimulationResult(raw)
    network.simulations.append(result)
    return result
