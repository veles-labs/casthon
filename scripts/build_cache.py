"""Content-based build state; callers hold the shared build lock."""

import hashlib
import json
import os
from pathlib import Path
import shutil
import shlex
import subprocess
import sys


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def file_hash(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write_changed(path, data):
    """Keep make dependencies' mtimes when their contents have not changed."""
    path = Path(path)
    data = data.encode() if isinstance(data, str) else data
    if path.is_file() and path.read_bytes() == data:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_bytes(data)
    temporary.replace(path)
    return True


def sync_tree(source, destination, ignore=()):
    expected = set()
    for path in sorted(source.rglob("*")):
        relative = path.relative_to(source)
        if path.is_file() and not any(part in ignore for part in relative.parts):
            expected.add(relative)
            write_changed(destination / relative, path.read_bytes())
    for path in destination.rglob("*"):
        relative = path.relative_to(destination)
        if path.is_file() and relative not in expected and not any(part in ignore for part in relative.parts):
            path.unlink()


def tool_identity(command, env=None):
    """Include versions and the actual tools, rather than just their PATH names."""
    located = shutil.which(str(command[0]))
    if not located:
        raise FileNotFoundError(str(command[0]))
    executable = Path(located).resolve()
    result = subprocess.run([*map(str, command), "--version"], check=True,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, env=env)
    files = [executable, *(Path(arg) for arg in command[1:] if Path(arg).is_file())]
    return {"command": list(map(str, command)), "version": result.stdout,
            "files": {str(path): file_hash(path) for path in files}}


def toolchain_identity(emcc, wasm_opt, env):
    emroot = Path(emcc[1]).parent
    # The emcc launcher is a Python script; track the compiler/linker it drives too.
    llvm = Path(os.environ.get("EMSCRIPTEN_LLVM_ROOT", emroot / "llvm/bin"))
    commands = {"emcc": emcc, "wasm-opt": [wasm_opt], "clang": [llvm / "clang"],
                "wasm-ld": [llvm / "wasm-ld"], "node": ["node"],
                "cc": shlex.split(os.environ.get("CC", "cc")), "make": ["make"]}
    environment = {name: value for name, value in env.items()
                   if name.startswith(("EM", "BINARYEN", "LLVM", "MICROPY"))
                   or name in ("CC", "CFLAGS", "CPPFLAGS", "CXXFLAGS", "LDFLAGS", "AR", "CROSS_COMPILE", "MAKEFLAGS", "SOURCE_DATE_EPOCH")}
    return {"tools": {name: tool_identity(command, env) for name, command in commands.items()},
            "python": [sys.executable, sys.version], "environment": environment}


class BuildState:
    """A hit requires matching inputs and intact outputs; publish only on success."""

    def __init__(self, path):
        self.path = Path(path)
        try:
            self.record = json.loads(self.path.read_text())
        except (OSError, ValueError):
            self.record = {}

    def matches(self, fingerprint, outputs):
        if not isinstance(self.record, dict) or self.record.get("fingerprint") != fingerprint:
            return False
        recorded = self.record.get("outputs")
        if not isinstance(recorded, dict) or set(recorded) != set(map(str, outputs)):
            return False
        try:
            return all(file_hash(path) == recorded[str(path)] for path in outputs)
        except OSError:
            return False

    def save(self, fingerprint, outputs):
        self.record = {"fingerprint": fingerprint,
                       "outputs": {str(path): file_hash(path) for path in outputs}}
        write_changed(self.path, json.dumps(self.record, indent=2) + "\n")
