#!/usr/bin/env python3
r"""Benchmark Casthon and Odra without cleaning or building in either source checkout.

Prerequisites: this checkout's Python dev environment and Wasm build tools,
cargo-odra 0.1.8, and the Rust toolchain pinned by benchmarks/tooling/odra.
Tool installation and dependency downloads are excluded from the measurements.

Example:
    .venv/bin/python scripts/benchmark_tooling.py --repeats 3

Results and compressed logs default to the ignored .experiments/tooling-benchmarks/
directory. Use --output to choose another new JSON file. The default run reproduces
the full comparison using the current SDK snapshot and the pinned counter fixtures;
--clippy-all-targets additionally includes test targets in Clippy's scope. Timings
depend on the machine, background load, and installed toolchain versions.

The temporary workspace and raw logs are retained. Each repetition starts with
empty compilation/check caches, then measures an unchanged rerun and a small
semantic source edit. Build, check, and test use independent project directories.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import shutil
import statistics
import subprocess
import sys
import tarfile
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
IGNORE = shutil.ignore_patterns(
    ".git", ".cache", ".venv", "target", "build", "node_modules",
    "__pycache__", ".mypy_cache", ".pytest_cache", "*.egg-info",
    ".experiments", "output", "tmp", ".env", ".DS_Store",
)


def fingerprint(root: Path) -> dict[str, str]:
    return {
        str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(root.rglob("*")) if path.is_file()
    }


def capture(command: list[str], cwd: Path, env: dict[str, str]) -> str:
    result = subprocess.run(command, cwd=cwd, env=env, text=True,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    if result.returncode:
        raise RuntimeError(f"{command!r} failed:\n{result.stdout}")
    return result.stdout.strip()


def positive(value: str) -> int:
    number = int(value)
    if number < 1:
        raise argparse.ArgumentTypeError("must be at least 1")
    return number


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--repeats", type=positive, default=3)
    parser.add_argument("--operations", nargs="+", choices=("build", "check", "test"),
                        default=["build", "check", "test"])
    parser.add_argument("--clippy-all-targets", action="store_true",
                        help="also lint test targets (default: Cargo's normal contract/build targets)")
    parser.add_argument("--sdk-root", type=Path, default=ROOT,
                        help="SDK source to snapshot (may be a previously frozen copy)")
    parser.add_argument("--casthon-bin", type=Path,
                        help="prebuilt CLI; otherwise compile the snapshot before timing")
    parser.add_argument("--odra-bin", type=Path,
                        help="cargo-odra executable; otherwise find it on PATH")
    parser.add_argument("--python", type=Path, default=Path(sys.executable))
    parser.add_argument("--work-dir", type=Path,
                        help="new, nonexistent directory; default: a fresh temporary directory")
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    parser.add_argument("--output", type=Path,
                        default=ROOT / ".experiments/tooling-benchmarks" / f"{stamp}.json",
                        help="new JSON result file (default: timestamped file under .experiments/tooling-benchmarks)")
    args = parser.parse_args()

    output = args.output.resolve()
    logs = output.with_name(output.stem + "-logs")
    logs_archive = output.with_name(output.stem + "-logs.tar.gz")
    if output.exists() or logs.exists() or logs_archive.exists():
        parser.error("output or logs already exist; choose a new output name")
    if args.work_dir:
        work = args.work_dir.resolve()
        work.mkdir(parents=True, exist_ok=False)
    else:
        work = Path(tempfile.mkdtemp(prefix="casthon-odra-tooling-"))
    output.parent.mkdir(parents=True, exist_ok=True)
    logs.mkdir()
    (logs / ".gitignore").write_text("*\n!.gitignore\n")
    python = args.python.absolute()
    source = args.sdk_root.resolve()
    if work.is_relative_to(source):
        parser.error("the benchmark workspace must be outside the SDK source directory")
    odra_bin = args.odra_bin or shutil.which("cargo-odra")
    if not odra_bin:
        parser.error("cargo-odra is required; install it or pass --odra-bin")
    odra_bin = Path(odra_bin).absolute()
    (work / "bin").mkdir()
    shutil.copy2(odra_bin, work / "bin/cargo-odra")
    odra_bin = work / "bin/cargo-odra"

    # Environment changes apply only to subprocesses. Builds and cache cleaning
    # stay in the new workspace; Cargo's downloaded package cache may be shared.
    env = dict(os.environ)
    for key in ("CARGO_TARGET_DIR", "CARGO_BUILD_TARGET", "CARGO_INCREMENTAL",
                "RUSTUP_TOOLCHAIN", "RUSTFLAGS", "CARGO_ENCODED_RUSTFLAGS",
                "RUSTC_WRAPPER", "RUSTC_WORKSPACE_WRAPPER", "ODRA_MODULE",
                "ODRA_BACKEND", "MYPY_CACHE_DIR", "PYTHONPATH",
                "PYTHONPYCACHEPREFIX", "PYTHONDONTWRITEBYTECODE", "EM_CONFIG"):
        env.pop(key, None)
    env.update(CARGO_BUILD_JOBS="6", CARGO_TERM_COLOR="never",
               PYTEST_DISABLE_PLUGIN_AUTOLOAD="1", EMSDK_PYTHON=str(python))
    env["PATH"] = os.pathsep.join((str(odra_bin.parent), str(python.parent), env["PATH"]))
    emdir = Path(shutil.which("emcc", path=env["PATH"]) or "emcc").resolve().parent
    emroot = Path(env.get("EMSCRIPTEN_ROOT", emdir if (emdir / "emcc.py").exists()
                          else emdir / "../libexec")).resolve()
    binaryen = Path(env.get("BINARYEN_ROOT", str(emroot / "binaryen")))
    # Match the builder's Binaryen selection; an unrelated old wasm-opt on PATH
    # must not make the Odra command fail or change the comparison.
    if (binaryen / "bin/wasm-opt").is_file():
        env["PATH"] = str(binaryen / "bin") + os.pathsep + env["PATH"]

    def prepare(name: str, command: list[str], cwd: Path) -> None:
        print(f"Preparing {name} (excluded from timing)", flush=True)
        with (logs / (name + ".log")).open("w") as stream:
            subprocess.run(command, cwd=cwd, env=env, stdout=stream,
                           stderr=subprocess.STDOUT, check=True)

    sdk = work / "sdk"
    shutil.copytree(source, sdk, ignore=IGNORE)
    env["MYPYPATH"] = str(sdk / "src")
    sdk_hashes = fingerprint(sdk)
    archives = work / "source-archives"
    archives.mkdir()
    recipe = json.loads((sdk / "native/toolchain.json").read_text())
    for name in (f"micropython-v{recipe['micropython']['version']}.tar.gz", "softfloat.tar.gz"):
        source_archive = source / ".cache" / name
        if not source_archive.is_file():
            parser.error(f"prefetch this SDK source archive before benchmarking: {source_archive}")
        shutil.copy2(source_archive, archives / name)

    casthon = args.casthon_bin
    if casthon:
        # Freeze the executable too, in case another session rebuilds its source.
        shutil.copy2(casthon, work / "casthon")
        casthon = work / "casthon"
    else:
        # A separate stable toolchain may be selected for CLI setup if Odra's
        # older nightly cannot compile the current Casthon dependencies.
        prepare("casthon-cli", ["cargo", "+stable", "build", "--release", "--locked",
                               "--target-dir", str(work / "cli-target")], sdk)
        casthon = work / "cli-target/release/casthon"

    fixtures = ROOT / "benchmarks/tooling"
    projects: dict[tuple[str, str], Path] = {}
    baselines: dict[tuple[str, str], str] = {}
    for tool in ("casthon", "odra"):
        for operation in ("build", "check", "test"):
            project = work / f"{tool}-{operation}"
            shutil.copytree(fixtures / tool, project, ignore=IGNORE)
            projects[tool, operation] = project
            relative = "contracts/bench_counter.py" if tool == "casthon" else "src/lib.rs"
            baselines[tool, operation] = (project / relative).read_text()

    odra_build = projects["odra", "build"]
    prepare("odra-fetch", ["cargo", "fetch", "--locked"], odra_build)
    # Require the exact same resolution across all three independent projects.
    for operation in ("check", "test"):
        shutil.copy2(odra_build / "Cargo.lock", projects["odra", operation] / "Cargo.lock")
    env["CARGO_NET_OFFLINE"] = "true"

    # Like the builder, avoid an unrelated ~/.emscripten configuration when
    # inspecting the installed toolchain. This does not warm the build cache.
    version_config = work / "emscripten-version-config.py"
    version_config.write_text(
        f"LLVM_ROOT = {env.get('EMSCRIPTEN_LLVM_ROOT', str(emroot / 'llvm/bin'))!r}\n"
        f"BINARYEN_ROOT = {env.get('BINARYEN_ROOT', str(emroot / 'binaryen'))!r}\n"
        f"NODE_JS = [{shutil.which('node', path=env['PATH'])!r}]\n"
        f"CACHE = {str(work / 'emscripten-version-cache')!r}\n"
    )

    def commands(tool: str, operation: str, project: Path) -> list[str]:
        if tool == "casthon":
            base = [str(casthon), "--sdk-root", str(sdk), "--python", str(python),
                    "--project-root", str(project)]
            return base + {
                "build": ["build", "--release", "--no-progress"],
                "check": ["check", "contracts"],
                "test": ["test", "--", "-q", "-p", "no:cacheprovider"],
            }[operation]
        return {
            "build": ["cargo", "odra", "build"],
            "check": ["cargo", "clippy", "--locked"]
                     + (["--all-targets"] if args.clippy_all_targets else [])
                     + ["--", "-D", "warnings"],
            "test": ["cargo", "odra", "test"],
        }[operation]

    report = {
        "schema_version": 1,
        "started_utc": datetime.now(timezone.utc).isoformat(),
        "workspace": str(work),
        "logs_archive": logs_archive.name,
        "repetitions": args.repeats,
        "operations": args.operations,
        "machine": {"platform": platform.platform(), "processor": platform.processor(),
                    "cpu_count": os.cpu_count()},
        "versions": {
            "casthon": capture([str(casthon), "--version"], sdk, env),
            "python": capture([str(python), "--version"], sdk, env),
            "mypy": capture([str(python), "-m", "mypy", "--version"], sdk, env),
            "pytest": capture([str(python), "-m", "pytest", "--version"], sdk, env),
            "rustc_odra": capture(["rustc", "--version"], odra_build, env),
            "cargo_odra_toolchain": capture(["cargo", "--version"], odra_build, env),
            "cargo_odra": capture([str(odra_bin), "odra", "--version"], odra_build, env),
            "wasm_opt": capture(["wasm-opt", "--version"], sdk, env),
            "emcc": next(line for line in capture(
                ["emcc", "--version"], sdk, {**env, "EM_CONFIG": str(version_config)}
            ).splitlines() if line.startswith("emcc ")),
        },
        "provenance": {
            "runner_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            "sdk_files_sha256": sdk_hashes,
            "fixture_files_sha256": {
                tool: fingerprint(projects[tool, "build"]) for tool in ("casthon", "odra")
            },
            "casthon_binary_sha256": hashlib.sha256(casthon.read_bytes()).hexdigest(),
            "cargo_odra_binary_sha256": hashlib.sha256(odra_bin.read_bytes()).hexdigest(),
        },
        "methodology": {
            "unit": "wall-clock seconds, including CLI/process startup",
            "build_profile": "release, default optimization pipelines, no extra minification",
            "cold_build": "empty project outputs and compilation caches; SDK/compiler executables and source archives already installed",
            "cold_check": "empty mypy cache / empty Cargo target directory (including dependencies)",
            "check_scope": "strict mypy contracts; Clippy " + ("all targets including tests" if args.clippy_all_targets else "default targets"),
            "cold_test": "empty project/SDK Python bytecode caches (installed Python dependencies retained) / empty Cargo target directory (including dependencies)",
            "first_noop": "build only: immediate unchanged rerun of the cold command, capturing first-run cache transitions",
            "noop": "unchanged rerun; build measured after first_noop, check/test immediately after cold",
            "edit": "change the version entrypoint result from 1 to 2, then rerun with warm caches",
            "tests": "six equivalent tests: initial value, set, increment, repeated increments, independent deployments, version",
            "test_backends": "Casthon CPython MockHost/ContractHarness; Odra OdraVM; no Wasm execution or network",
            "parallelism": "commands sequential; Cargo jobs=6; Casthon's builders use make -j6; toolchain internals use their defaults",
            "downloads": "prefetched and excluded; measured Cargo commands run offline",
            "os_caches": "not flushed; cold refers to tool artifacts, not filesystem caches",
            "contention": "other user sessions and background processes may affect wall-clock timings; load averages recorded per sample",
        },
        "samples": [],
        "summary": [],
    }
    if sys.platform == "darwin":
        report["machine"].update(
            model=capture(["sysctl", "-n", "hw.model"], sdk, env),
            cpu=capture(["sysctl", "-n", "machdep.cpu.brand_string"], sdk, env),
            memory_bytes=int(capture(["sysctl", "-n", "hw.memsize"], sdk, env)),
        )

    def save() -> None:
        report["summary"] = []
        for tool in ("casthon", "odra"):
            for operation in ("build", "check", "test"):
                for state in ("cold", "first_noop", "noop", "edit"):
                    values = [sample["seconds"] for sample in report["samples"]
                              if (sample["tool"], sample["operation"], sample["state"], sample["exit_code"])
                              == (tool, operation, state, 0)]
                    if values:
                        report["summary"].append(dict(
                            tool=tool, operation=operation, state=state, n=len(values),
                            median_seconds=statistics.median(values),
                            min_seconds=min(values), max_seconds=max(values),
                        ))
        temporary = output.with_suffix(".json.tmp")
        temporary.write_text(json.dumps(report, indent=2) + "\n")
        temporary.replace(output)

    def measure(tool: str, operation: str, state: str, repetition: int) -> None:
        project = projects[tool, operation]
        command = commands(tool, operation, project)
        name = f"{tool}-{operation}-{state}-{repetition}.log"
        sample = dict(tool=tool, operation=operation, state=state,
                      repetition=repetition, command=command, cwd=str(project),
                      log=str((logs / name).relative_to(output.parent)),
                      load_before=list(os.getloadavg()))
        print(f"{tool:7} {operation:5} {state:4} {repetition}/{args.repeats} ...", flush=True)
        with (logs / name).open("w") as stream:
            start = time.perf_counter()
            sample_env = {**env, "BENCHMARK_EXPECTED_VERSION": "2" if state == "edit" else "1"}
            result = subprocess.run(command, cwd=project, env=sample_env, stdout=stream,
                                    stderr=subprocess.STDOUT)
            sample["seconds"] = time.perf_counter() - start
        sample.update(exit_code=result.returncode, load_after=list(os.getloadavg()))
        content = (logs / name).read_text()
        if operation == "build" and result.returncode == 0:
            artifact = (project / "build/release/bench_counter.wasm" if tool == "casthon"
                        else project / "wasm/BenchCounter.wasm")
            sample["artifact_bytes"] = artifact.stat().st_size
            sample["artifact_sha256"] = hashlib.sha256(artifact.read_bytes()).hexdigest()
            sample["cached_contract"] = "Using cached contract:" in content
            sample["compiled_c_files"] = sum(line.startswith("CC ") for line in content.splitlines())
            if tool == "casthon":
                build_report = json.loads((project / "build/release/bench_counter-build-report.json").read_text())
                sample["runtime_profile"] = build_report["cache"]["runtimeProfile"]
        if operation == "test" and result.returncode == 0:
            matched = re.search(r"(\d+) passed" if tool == "casthon"
                                else r"test result: ok\. (\d+) passed", content)
            sample["tests_passed"] = int(matched[1]) if matched else None
        report["samples"].append(sample)
        save()
        print(f"  {sample['seconds']:.3f}s (exit {result.returncode})", flush=True)
        if result.returncode:
            raise RuntimeError(f"Benchmark failed; inspect {logs / name}")
        if operation == "test" and sample.get("tests_passed") != 6:
            raise RuntimeError(f"Expected exactly six passing tests; inspect {logs / name}")

    save()
    # Alternate which tool runs first across repetitions. Never overlap samples.
    for repetition in range(1, args.repeats + 1):
        tools = ("casthon", "odra") if repetition % 2 else ("odra", "casthon")
        for operation in args.operations:
            for tool in tools:
                project = projects[tool, operation]
                relative = "contracts/bench_counter.py" if tool == "casthon" else "src/lib.rs"
                source_file = project / relative
                baseline = baselines[tool, operation]
                source_file.write_text(baseline)
                for name in (("build", ".mypy_cache", ".pytest_cache") if tool == "casthon"
                             else ("target", "wasm")):
                    shutil.rmtree(project / name, ignore_errors=True)
                if tool == "casthon":
                    for path in project.rglob("__pycache__"):
                        shutil.rmtree(path)
                    if operation == "test":
                        for path in (sdk / "src").rglob("__pycache__"):
                            shutil.rmtree(path)
                    if operation == "build":
                        shutil.rmtree(sdk / ".cache", ignore_errors=True)
                        shutil.copytree(archives, sdk / ".cache")
                measure(tool, operation, "cold", repetition)
                if operation == "build":
                    measure(tool, operation, "first_noop", repetition)
                measure(tool, operation, "noop", repetition)
                marker = "return 1  # benchmark-edit" if tool == "casthon" else "1 // benchmark-edit"
                # mypy and Python bytecode caches use whole-second timestamps
                # with a source-size shortcut. Change the file size as well as
                # the value, so even a subsecond edit is reliably detected.
                replacement = marker.replace("1", "2", 1) + " "
                if baseline.count(marker) != 1:
                    raise RuntimeError(f"Missing unique edit marker in {source_file}")
                source_file.write_text(baseline.replace(marker, replacement))
                measure(tool, operation, "edit", repetition)
                if operation == "build":
                    triplet = {sample["state"]: sample for sample in report["samples"]
                               if (sample["tool"], sample["operation"], sample["repetition"])
                               == (tool, operation, repetition)}
                    if triplet["noop"]["artifact_sha256"] != triplet["first_noop"]["artifact_sha256"]:
                        raise RuntimeError("Unchanged build unexpectedly changed the deployment artifact")
                    if triplet["edit"]["artifact_sha256"] == triplet["noop"]["artifact_sha256"]:
                        raise RuntimeError("Source edit did not change the deployment artifact")
                    if tool == "casthon" and not triplet["noop"]["cached_contract"]:
                        raise RuntimeError("Expected a steady-state Casthon build cache hit")

    with tarfile.open(logs_archive, "w:gz") as bundle:
        for path in sorted(logs.glob("*.log")):
            bundle.add(path, arcname=str(path.relative_to(output.parent)))
    report["finished_utc"] = datetime.now(timezone.utc).isoformat()
    save()
    print("\nMedian wall-clock seconds:")
    for entry in report["summary"]:
        print(f"{entry['tool']:7} {entry['operation']:5} {entry['state']:4}: "
              f"{entry['median_seconds']:.3f} ({entry['min_seconds']:.3f}–{entry['max_seconds']:.3f})")
    print(f"\nResults: {output}\nWorkspace retained: {work}")


if __name__ == "__main__":
    main()
