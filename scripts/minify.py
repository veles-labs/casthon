"""Try size-focused MVP pipelines; retain the smallest ABI-compatible module."""

import hashlib
from pathlib import Path
import shutil
import subprocess

COMPACT = ["--gufa-optimizing", "--duplicate-function-elimination", "--merge-similar-functions",
           "--dae-optimizing", "--code-folding", "--coalesce-locals-learning",
           "--simplify-globals-optimizing", "--memory-packing", "-Oz", "--converge"]
FINISH = ["--remove-unused-module-elements", "--reorder-functions", "--reorder-locals",
          "--reorder-globals", "--reorder-types", "--optimize-stack-ir", "--strip-debug",
          "--strip-producers", "--strip-target-features", "--strip-toolchain-annotations"]


class Reader:
    def __init__(self, data):
        self.data, self.pos = data, 0

    def byte(self):
        value = self.data[self.pos]
        self.pos += 1
        return value

    def uint(self):
        value, shift = 0, 0
        while True:
            part = self.byte()
            value |= (part & 127) << shift
            if not part & 128:
                return value
            shift += 7

    def vector(self, read):
        return [read() for _ in range(self.uint())]

    def string(self):
        size = self.uint()
        value = self.data[self.pos:self.pos + size].decode("utf-8")
        self.pos += size
        return value

    def limits(self):
        flags = self.byte()
        return (flags, self.uint(), self.uint() if flags & 1 else None)

    def global_type(self):
        descriptor = (self.byte(), self.byte())
        # MVP constant expressions: integer constants or an imported global.
        while (opcode := self.byte()) != 0x0B:
            if opcode not in (0x41, 0x42, 0x23):
                raise ValueError("Unsupported global initializer")
            self.uint()  # Consume signed constants without interpreting them.
        return descriptor


def interface(path):
    """Normalize function signatures and public resources without index numbers."""
    data = path.read_bytes()
    if data[:8] != b"\0asm\x01\0\0\0":
        raise ValueError("Expected Wasm version 1")
    reader = Reader(data)
    reader.pos = 8
    types, imports, functions, tables, memories, globals_, exports = [], [], [], [], [], [], []
    while reader.pos < len(data):
        kind, size = reader.byte(), reader.uint()
        section = Reader(data[reader.pos:reader.pos + size])
        reader.pos += size
        if kind == 1:
            for _ in range(section.uint()):
                if section.byte() != 0x60:
                    raise ValueError("Expected an MVP function type")
                types.append((tuple(section.vector(section.byte)), tuple(section.vector(section.byte))))
        elif kind == 2:
            for _ in range(section.uint()):
                module, name, tag = section.string(), section.string(), section.byte()
                if tag != 0:
                    raise ValueError("Casper requires function-only imports")
                type_index = section.uint()
                imports.append((module, name, types[type_index]))
                functions.append(type_index)
        elif kind == 3:
            functions.extend(section.vector(section.uint))
        elif kind == 4:
            tables = section.vector(lambda: (section.byte(), section.limits()))
        elif kind == 5:
            memories = section.vector(section.limits)
        elif kind == 6:
            globals_ = section.vector(section.global_type)
        elif kind == 7:
            for _ in range(section.uint()):
                name, tag, index = section.string(), section.byte(), section.uint()
                if tag == 0:
                    value = types[functions[index]]
                elif tag == 1:
                    value = tables[index]
                elif tag == 2:
                    value = memories[index]
                elif tag == 3:
                    value = globals_[index]
                else:
                    raise ValueError("Unsupported exported resource")
                exports.append((name, tag, value))
    return {"imports": sorted(imports), "exports": sorted(exports), "memory": memories}


def minify(source, output, wasm_opt, validator, work):
    validator = list(validator) if isinstance(validator, (list, tuple)) else [validator]
    work.mkdir(parents=True, exist_ok=True)
    expected = interface(source)
    records, candidates = [], {}
    version = subprocess.check_output([str(wasm_opt), "--version"], text=True).strip()

    def attempt(name, parent, flags, tool=wasm_opt):
        path, log = work / (name + ".wasm"), work / (name + ".log")
        record = {"name": name, "input": parent.name, "tool": tool.name, "flags": flags}
        with log.open("w") as stream:
            result = subprocess.run([str(tool), str(parent), *flags, "--mvp-features", "-o", str(path)],
                                    stdout=stream, stderr=subprocess.STDOUT)
        if result.returncode:
            record.update(accepted=False, reason="Optimizer failed; see " + str(log))
        else:
            with log.open("a") as stream:
                check = subprocess.run([*map(str, validator), "--check", str(path)], stdout=stream, stderr=subprocess.STDOUT)
            if check.returncode:
                record.update(accepted=False, reason="Casper MVP validation failed")
            elif interface(path) != expected:
                record.update(accepted=False, reason="Public imports, exports or memory changed")
            else:
                record.update(accepted=True, bytes=path.stat().st_size,
                              sha256=hashlib.sha256(path.read_bytes()).hexdigest())
                candidates[name] = path
        records.append(record)
        return candidates.get(name)

    # Canonical LLVM/LTO/-Oz input is a candidate, so extra passes cannot enlarge it.
    candidates["baseline"] = source
    attempt("converged", source, ["-Oz", "--converge", *FINISH])
    attempt("compact", source, [*COMPACT, *FINISH])
    # ABI equivalence alone does not preserve Casper's charged stack height.
    # These pipelines trap in the class Counter under stock metering; retain
    # their measurements in results/casthon-minification-investigation.json.
    selected, path = min(candidates.items(), key=lambda item: (item[1].stat().st_size, item[0]))
    shutil.copyfile(path, output)
    return {"enabled": True, "binaryen": version, "inputBytes": source.stat().st_size,
            "outputBytes": output.stat().st_size, "savedBytes": source.stat().st_size - output.stat().st_size,
            "selected": selected, "interfacePreserved": True, "candidates": records,
            "pythonSourceLines": False, "pythonAssertions": True,
            "excluded": ["ABI name mangling", "fast math", "trap assumptions", "assert removal",
                         "flatten/rereloop (metered Counter stack regression)",
                         "constructor evaluation (metered Counter startup regression)",
                         "outlining (creates non-MVP multivalue in Binaryen 132)",
                         "gzip/Brotli (Casper deploys raw Wasm)"]}
