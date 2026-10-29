"""Build-on-demand support for live tests, with a source-keyed artifact cache."""

import fcntl
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from typing import Sequence


def _casthon(sdk: Path) -> str | None:
    selected = os.environ.get("CASTHON_BIN")
    if selected:
        found = shutil.which(selected)
        if found is None:
            raise RuntimeError("CASTHON_BIN does not identify an executable: " + selected)
        return str(Path(found).resolve())
    found = shutil.which("casthon")
    if found:
        return str(Path(found).resolve())
    candidates = [sdk / "target" / profile / "casthon" for profile in ("release", "debug")]
    available = [path for path in candidates if path.is_file() and os.access(path, os.X_OK)]
    return str(max(available, key=lambda path: path.stat().st_mtime_ns)) if available else None


def build_contract(source: str | Path, *, project_root: str | Path | None = None,
                   runtime: str = "asyncify", minify: bool = False,
                   profile: str = "debug",
                   cache: str | Path | None = None, command: Sequence[str] | None = None,
                   timeout: float = 600) -> Path:
    if runtime not in ("asyncify", "native-errors"):
        raise ValueError("Unknown runtime")
    if profile not in ("debug", "release"):
        raise ValueError("Unknown build profile")
    project = Path(project_root or Path.cwd()).resolve()
    source = (project / source).resolve()
    sdk = Path(__file__).resolve().parents[3]
    builder = sdk / "scripts/build.py"
    checkout = builder.is_file() and (sdk / "native/toolchain.json").is_file()
    casthon = _casthon(sdk) if command is None else None
    if command is None and not casthon and not checkout:
        raise RuntimeError("Building requires the casthon CLI; install it with cargo install casthon")
    driver = list(command) if command is not None else (
        [casthon, "--project-root", str(project),
         *(["--sdk-root", str(sdk)] if checkout else []),
         "--python", sys.executable, "build"]
        if casthon else [sys.executable, str(builder)])
    inputs = {source}
    inputs.update(Path(arg).resolve() for arg in command or () if Path(arg).is_file())
    inputs.update((project / "contracts").rglob("*.py"))
    inputs.update(path for path in (project / "pyproject.toml", sdk / "Cargo.toml", sdk / "Cargo.lock") if path.is_file())
    inputs.update((sdk / "cli").rglob("*.rs"))
    inputs.update((sdk / "tools/wasm-softfloat/src").rglob("*.rs"))
    inputs.update(path for path in (sdk / "tools/wasm-softfloat/Cargo.toml", sdk / "tools/wasm-softfloat/Cargo.lock")
                  if path.is_file())
    for folder in (sdk / "src/casthon", sdk / "runtime", sdk / "native", sdk / "scripts"):
        inputs.update(path for path in folder.rglob("*") if path.is_file()
                      and (path.suffix in (".py", ".c", ".h", ".S", ".patch", ".json") or path.name == "Makefile")
                      and "__pycache__" not in path.parts
                      and not (folder == sdk / "src/casthon" and
                               ("testing" in path.relative_to(folder).parts or path.name == "_context.py")))
    tools = {}
    for name in ("emcc", "wasm-opt", "cargo", "node"):
        located = shutil.which(name)
        if located:
            path = Path(located).resolve()
            stat = path.stat()
            tools[name] = [str(path), stat.st_size, stat.st_mtime_ns]
    environment = {name: os.environ.get(name) for name in
                   ("EMSCRIPTEN_ROOT", "EMSCRIPTEN_LLVM_ROOT", "BINARYEN_ROOT", "RUSTFLAGS")}
    if casthon:
        stat = Path(casthon).stat()
        tools["casthon"] = [casthon, stat.st_size, stat.st_mtime_ns]
    fingerprint = hashlib.sha256(json.dumps([runtime, minify, profile, driver, sys.version,
                                             sys.executable, tools, environment], sort_keys=True).encode())
    for path in sorted(inputs):
        fingerprint.update(str(path).encode())
        fingerprint.update(path.read_bytes())
    output = Path(cache or project / ".cache/casthon-testing/build").resolve() / fingerprint.hexdigest()
    output.mkdir(parents=True, exist_ok=True)
    folder = output if runtime == "asyncify" else output / "native-errors"
    if profile == "release":
        folder /= "release"
    if minify:
        folder /= "minified"
    artifact = folder / (source.stem + ".wasm")
    report = folder / (source.stem + "-build-report.json")
    with (output / "build.lock").open("a+") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        if artifact.exists() and report.exists():
            recorded = json.loads(report.read_text())
            if hashlib.sha256(artifact.read_bytes()).hexdigest() == recorded["sha256"]:
                return artifact
        arguments = [*driver, str(source), "--runtime", runtime, "--profile", profile, "--output-dir", str(output)]
        if not casthon:
            arguments.extend(("--project-root", str(project)))
        if minify:
            arguments.append("--minify")
        if casthon:
            arguments.append("--json")
        log = output / "build.log"
        with log.open("w") as stream:
            result = subprocess.run(arguments, cwd=project, stdout=subprocess.PIPE if casthon else stream,
                                    stderr=stream if casthon else subprocess.STDOUT, text=True, timeout=timeout)
        if result.returncode:
            raise RuntimeError(f"Contract build failed; see {log}")
        if casthon:
            try:
                built = json.loads(result.stdout)["artifacts"]
                if (len(built) != 1 or Path(built[0]["wasm"]).resolve() != artifact.resolve()
                        or Path(built[0]["report"]).resolve() != report.resolve()):
                    raise ValueError("Unexpected artifact paths")
            except (KeyError, TypeError, ValueError) as error:
                raise RuntimeError(f"Invalid casthon artifact manifest; see {log}") from error
        if not artifact.is_file() or not report.is_file():
            raise RuntimeError(f"Builder did not produce the expected Wasm and report; see {log}")
        recorded = json.loads(report.read_text())
        if hashlib.sha256(artifact.read_bytes()).hexdigest() != recorded["sha256"]:
            raise RuntimeError("Built artifact does not match its report")
    return artifact
