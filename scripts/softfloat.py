"""Build pinned Berkeley SoftFloat and the integer ABI used by the Wasm lowerer."""

import hashlib
import json
from pathlib import Path
import shlex
import shutil
import subprocess
import tarfile
import urllib.request
from build_cache import digest, file_hash, tool_identity

RECIPE = json.loads((Path(__file__).resolve().parents[1] / "native/toolchain.json").read_text())["softfloat"]
REVISION = RECIPE["revision"]
SHA256 = RECIPE["sha256"]


def build(root, cache, emcc, env, toolchain=None):
    archive = cache / "softfloat.tar.gz"
    if not archive.exists():
        urllib.request.urlretrieve(
            f"https://codeload.github.com/ucb-bar/berkeley-softfloat-3/tar.gz/{REVISION}", archive)
    if hashlib.sha256(archive.read_bytes()).hexdigest() != SHA256:
        raise ValueError("SoftFloat archive checksum mismatch")
    source = cache / ("berkeley-softfloat-3-" + REVISION) / "source"
    if not source.exists():
        with tarfile.open(archive) as tar:
            tar.extractall(cache, filter="data")
    platform = root / "native/softfloat/platform.h"
    flags = ["-DSOFTFLOAT_FAST_INT64", "-DSOFTFLOAT_ROUND_ODD", "-DINLINE_LEVEL=5",
             "-I" + str(root / "native/softfloat"), "-I" + str(source / "include")]
    cflags = ["-Oz", "-flto", "-DNDEBUG", "-fwrapv", "-fno-jump-tables",
              "-mno-bulk-memory", "-mno-reference-types", "-mno-multivalue",
              "-mno-nontrapping-fptoint", "-mno-sign-ext", "-mno-simd128", "-mno-atomics"]
    profile = digest([SHA256, flags, cflags, file_hash(platform), file_hash(__file__),
                      toolchain or tool_identity(emcc, env), env.get("EM_CONFIG"),
                      file_hash(env["EM_CONFIG"]) if env.get("EM_CONFIG") else None])
    output = cache / "softfloat-build" / profile
    output.mkdir(parents=True, exist_ok=True)
    cached_platform = output / "platform.h"
    if not cached_platform.exists() or cached_platform.read_bytes() != platform.read_bytes():
        shutil.copyfile(platform, cached_platform)
    emar = [emcc[0], str(Path(emcc[1]).with_name("emar.py"))]
    compile_c = shlex.join([*map(str, emcc), *cflags, *flags, "-I" + str(source / "8086-SSE"), "-c", "-o"]) + " $@"
    make_lib = shlex.join(emar) + " crs $@"
    print("Building integer-only Berkeley SoftFloat", flush=True)
    subprocess.run(["make", "-s", "-j6", "-f", str(source.parent / "build/Linux-x86_64-GCC/Makefile"),
                    "SOURCE_DIR=" + str(source), "COMPILE_C=" + compile_c, "MAKELIB=" + make_lib],
                   cwd=output, env=env, check=True)
    helpers = []
    for bits in (32, 64):
        for op in ("abs", "neg", "ceil", "floor", "trunc", "nearest", "sqrt", "add", "sub", "mul", "div",
                   "min", "max", "copysign", "eq", "ne", "lt", "gt", "le", "ge"):
            helpers.append(f"__sf_f{bits}_{op}")
        for ibits in (32, 64):
            for sign in ("s", "u"):
                helpers.extend((f"__sf_i{ibits}_trunc_f{bits}_{sign}", f"__sf_i{ibits}_trunc_sat_f{bits}_{sign}",
                                f"__sf_f{bits}_convert_i{ibits}_{sign}"))
    helpers.extend(("__sf_f32_demote_f64", "__sf_f64_promote_f32"))
    return output / "softfloat.a", flags, ["-Wl,--export=" + name for name in helpers]
