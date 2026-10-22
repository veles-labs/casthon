#!/usr/bin/env python3
"""Build a pinned, frozen MicroPython interpreter for Casper V1."""
import hashlib
import fcntl
import argparse
import json
import os
import shlex
import shutil
import subprocess
import sys
import tarfile
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
from bundle import load_contract, contract_modules, lower, lower_enums, generate_exports
from micropython import prepare_and_verify, verify
from softfloat import build as build_softfloat, REVISION as SOFTFLOAT_REVISION, SHA256 as SOFTFLOAT_SHA256
from minify import interface, minify
from build_cache import BuildState, digest, emscripten_configuration, file_hash, sync_tree, toolchain_identity, write_changed
from build_progress import BuildProgress

RECIPE = json.loads((ROOT / "native/toolchain.json").read_text())
VERSION = RECIPE["micropython"]["version"]
SHA256 = RECIPE["micropython"]["sha256"]
CACHE, OUTPUT = ROOT / ".cache", ROOT / "build"


def run(args, **kwargs):
    subprocess.run([str(a) for a in args], check=True, cwd=ROOT, **kwargs)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("target", nargs="?", default="counter")
    parser.add_argument("--micropython", choices=(VERSION,), default=VERSION,
                        help="MicroPython version supported by this runtime recipe")
    parser.add_argument("--casthon", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--progress", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--project-root", type=Path, default=ROOT,
                        help="Project directory containing local contracts.* helper modules")
    parser.add_argument("--output-dir", type=Path, default=OUTPUT,
                        help="Artifact directory (default: this checkout's build directory)")
    parser.add_argument("--runtime", choices=("asyncify", "native-errors"), default="asyncify",
                        help="Asyncify with pristine upstream (default), or preserved native error-return patches")
    profiles = parser.add_mutually_exclusive_group()
    profiles.add_argument("--profile", choices=("debug", "release"), default="debug",
                          help="Debug prints to casper_print (default); release omits printing and dispatcher diagnostics")
    profiles.add_argument("--release", dest="profile", action="store_const", const="release",
                          help="Alias for --profile release")
    heap_options = parser.add_mutually_exclusive_group()
    heap_options.add_argument("--experimental-split-heap", action="store_true",
                        help="Experiment: grow upstream MicroPython split heaps through emmalloc (64 KiB initial GC region; 512 KiB initial/4 MiB maximum Wasm memory)")
    heap_options.add_argument("--heap", "--experimental-heap", dest="heap",
                        choices=("emmalloc-gc0", "emmalloc-gc1", "static", "split"),
                        help="Heap profile for Asyncify (default: emmalloc-gc0); the preserved native-errors backend supports static only")
    parser.add_argument("--minify", action="store_true", help="Strip Python line tables and try deeper Wasm size passes; output in the selected runtime's minified directory")
    options = parser.parse_args()
    heap_mode = "split" if options.experimental_split_heap else options.heap
    if options.runtime == "native-errors":
        if heap_mode not in (None, "static"):
            parser.error("The preserved native-errors audit covers only --heap static; use Asyncify for other heap profiles")
        heap_mode = "static"
    else:
        heap_mode = heap_mode or "emmalloc-gc0"
    CACHE.mkdir(exist_ok=True)
    progress = BuildProgress(options.progress)
    progress.start("Preparing build")
    # The compiler sources, generated port and Emscripten cache are shared.
    # Serialize both CLI builds and legacy Python entrypoints until isolated.
    with (CACHE / "build.lock").open("a+") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        build(options, heap_mode, progress)


def build(options, heap_mode, progress):
    progress.start("Analyzing and lowering Python")
    project_root = options.project_root.resolve()
    selection = options.target
    source_path = Path(selection) if selection.endswith(".py") else project_root / "contracts" / (selection + ".py")
    target = source_path.stem
    if not target.isidentifier():
        raise ValueError("Invalid contract target")
    declaration, source = load_contract(source_path, project_root)
    CACHE.mkdir(exist_ok=True)
    output_root = options.output_dir.resolve()
    output_root.mkdir(parents=True, exist_ok=True)
    output_dir = output_root if options.runtime == "asyncify" else output_root / "native-errors"
    if options.profile == "release":
        output_dir /= "release"
    if options.minify:
        output_dir /= "minified"
    output_dir.mkdir(parents=True, exist_ok=True)
    generated = output_dir / target
    generated.mkdir(exist_ok=True)
    modules = contract_modules(source, project_root)
    modules.update({"casthon/" + str(path.relative_to(ROOT / "src/casthon")): path
                    for path in sorted((ROOT / "src/casthon").rglob("*.py"))
                    if path.name not in ("_context.py", "_signatures.py")
                    and path.relative_to(ROOT / "src/casthon").parts[0] != "testing"})
    modules["casthon/types.py"] = ROOT / "runtime/types.py"
    modules["casthon/arguments.py"] = ROOT / "runtime/arguments.py"
    modules["casthon/_entry_point_signature.py"] = ROOT / "runtime/entry_point_signature.py"
    modules["casthon/_contract_schema.py"] = ROOT / "runtime/contract_schema.py"
    modules["casthon/_event_schema.py"] = ROOT / "runtime/event_schema.py"
    modules["_cspr_dispatcher.py"] = ROOT / "runtime/dispatcher.py"
    signatures = generated / "_cspr_exports.py"
    write_changed(signatures, generate_exports(source, declaration["exports"], project_root))
    modules["_cspr_exports.py"] = signatures
    progress.update(0, len(modules))
    for name, path in modules.items():
        output = generated / name
        output.parent.mkdir(parents=True, exist_ok=True)
        write_changed(output, lower_enums(path) if name == "casthon/enums.py" else
                      lower(path, sdk=name.startswith(("casthon/", "_cspr_")), project_root=project_root))
        progress.advance()
    # Removals must invalidate freezing too: make cannot detect a removed prerequisite.
    modules_changed = write_changed(generated / "modules.json", json.dumps(sorted(modules)) + "\n")
    expected_mpy = {f"module_{index}.mpy" for index in range(len(modules))}
    for previous in generated.glob("*.mpy"):
        if previous.name not in expected_mpy:
            previous.unlink()
    for previous in generated.rglob("*.py"):
        if str(previous.relative_to(generated)) not in modules:
            previous.unlink()
    write_changed(output_dir / (target + ".json"), json.dumps(declaration, indent=2) + "\n")
    write_changed(generated / "entrypoints.c", "void cspr_dispatch(const char *);\n" + "\n".join(
        f'__attribute__((export_name("{name}"))) void ep_{index}(void) {{ cspr_dispatch("{name}"); }}'
        for index, name in enumerate(declaration["exports"])) + "\n")

    progress.start("Preparing MicroPython runtime")
    archive = CACHE / f"micropython-v{VERSION}.tar.gz"
    if not archive.exists():
        print("Downloading pinned MicroPython", flush=True)
        urllib.request.urlretrieve(f"https://codeload.github.com/micropython/micropython/tar.gz/refs/tags/v{VERSION}", archive)
    if hashlib.sha256(archive.read_bytes()).hexdigest() != SHA256:
        raise ValueError("MicroPython archive checksum mismatch")
    runtime_cache = CACHE / ("procedural-" + options.runtime) / "runtime"
    runtime_cache.mkdir(parents=True, exist_ok=True)
    mp = runtime_cache / f"micropython-{VERSION}"
    if not mp.exists():
        with tarfile.open(archive) as tar:
            tar.extractall(runtime_cache, filter="data")
    expected_source, changed, patches = prepare_and_verify(archive, mp,
        "native-errors" if options.runtime == "native-errors" else "baseline")
    port = ROOT / "native"
    if options.runtime == "asyncify":
        port = CACHE / "procedural-asyncify/port"
        sync_tree(ROOT / "native", port, ignore=("micropython", "Makefile", "mpconfigport.h",
                                               "setjmp.h", "unwind.c", "setjmp_core.S"))
        for name in ("setjmp.h", "unwind.c", "setjmp_core.S"):
            write_changed(port / name, (ROOT / "native/asyncify" / name).read_bytes())
        config_text = (ROOT / "native/mpconfigport.h").read_text()
        config_text = config_text.replace("#define MICROPY_NLR_ERROR_RETURNS (1)\n", "").replace("#define MP_NORETURN\n", "")
        write_changed(port / "mpconfigport.h", config_text + "\n#define CSPR_ASYNCIFY (1)\n"
                      + f"#define CSPR_DEBUG ({int(options.profile == 'debug')})\n")
        makefile = (ROOT / "native/Makefile").read_text()
        makefile = makefile.replace("SRC_C = adapter.c system.c", "SRC_C = adapter.c system.c unwind.c")
        makefile = makefile.replace("OBJ += $(PY_CORE_O)", "OBJ += $(BUILD)/setjmp_core.o $(PY_CORE_O)")
        # Keep driver boundaries intact until Binaryen instruments continuations.
        makefile = makefile.replace("LDFLAGS += -Oz", "LDFLAGS += --profiling-funcs -sASSERTIONS=0 -O1")
        write_changed(port / "Makefile", makefile)
    else:
        # Keep the preserved call-site audit tied to its exact reviewed flags.
        port = CACHE / "procedural-native-errors/port"
        sync_tree(ROOT / "native", port, ignore=("micropython", "Makefile", "mpconfigport.h"))
        for name in ("mpconfigport.h", "Makefile"):
            content = (ROOT / "native/micropython/port" / name).read_bytes()
            if name == "mpconfigport.h":
                content += f"\n#define CSPR_DEBUG ({int(options.profile == 'debug')})\n".encode()
            write_changed(port / name, content)

    emroot, binaryen, config_text = emscripten_configuration(CACHE / "emscripten")
    config = CACHE / "emscripten-config.py"
    write_changed(config, config_text)
    env = {**os.environ, "EM_CONFIG": str(config), "EMSDK_PYTHON": sys.executable}
    emcc = [sys.executable, emroot / "emcc.py"]
    wasm_opt = binaryen / "bin/wasm-opt"
    if not wasm_opt.exists():
        wasm_opt = Path(shutil.which("wasm-opt"))
    toolchain = toolchain_identity(emcc, wasm_opt, env)
    build = generated / "vm"
    profile_sources = sorted(path for path in (ROOT / "native").rglob("*")
                             if path.is_file() and path.suffix in (".c", ".h", ".S", ".patch", ".json"))
    scripts = {str(path.relative_to(ROOT)): file_hash(path) for path in sorted((ROOT / "scripts").glob("*.py"))}
    profile_hash = digest([RECIPE, toolchain, config.read_text(), options.runtime, heap_mode, options.profile,
                           file_hash(port / "Makefile"), file_hash(port / "mpconfigport.h"),
                           {str(path.relative_to(ROOT)): file_hash(path) for path in profile_sources},
                           {name: scripts["scripts/" + name] for name in
                            ("build.py", "build_cache.py", "micropython.py", "softfloat.py")}])
    runtime_build = CACHE / "micropython-build" / VERSION / options.runtime / heap_mode / profile_hash
    if options.runtime == "native-errors":
        # Preserve the byte-for-byte audited Makefile and its compiler flags.
        # It keeps core objects locally; the default Asyncify port shares them.
        runtime_build = build
    wasm = output_dir / (target + ".wasm")
    metered = output_dir / (target + ".metered.wasm")
    report = output_dir / (target + "-build-report.json")
    outputs = [wasm, metered, report, output_dir / "readback.wasm", output_dir / (target + ".json")]
    if target == "counter":
        outputs.append(output_dir / "build-report.json")
    tool_binary = options.casthon.resolve() if options.casthon else ROOT / "tools/wasm-softfloat/target/release/wasm-softfloat"
    def fingerprint():
        return digest([profile_hash, scripts, options.minify, str(project_root), declaration,
                       {name: file_hash(generated / name) for name in sorted(modules)},
                       str(tool_binary), file_hash(tool_binary) if tool_binary.exists() else None,
                       {str(path.relative_to(ROOT)): file_hash(path) for path in sorted((ROOT / "tools/wasm-softfloat").glob("src/**/*.rs"))},
                       file_hash(ROOT / "tools/wasm-softfloat/Cargo.toml"),
                       file_hash(ROOT / "tools/wasm-softfloat/Cargo.lock")])
    state = BuildState(generated / "build-cache.json")
    if state.matches(fingerprint(), outputs):
        progress.start("Reusing cached artifacts")
        print("Using cached contract: " + str(wasm), flush=True)
        progress.finish(cached=True)
        return

    progress.start("Freezing Python modules", len(modules) + 1)
    compiler_cache = CACHE / "procedural/compiler"
    compiler_cache.mkdir(parents=True, exist_ok=True)
    compiler_source = compiler_cache / f"micropython-{VERSION}"
    if not compiler_source.exists():
        with tarfile.open(archive) as tar:
            tar.extractall(compiler_cache, filter="data")
    compiler_profile = digest([SHA256, toolchain["tools"]["cc"], toolchain["tools"]["make"],
                               toolchain["python"], toolchain["environment"]])
    compiler_stamp = compiler_source / "compiler-profile.sha256"
    if not compiler_stamp.exists() or compiler_stamp.read_text() != compiler_profile:
        shutil.rmtree(compiler_source / "mpy-cross/build", ignore_errors=True)
        write_changed(compiler_stamp, compiler_profile)
    print("Checking cached bytecode compiler and freezing changed Python modules", flush=True)
    run(["make", "-s", "-j6", "-C", compiler_source / "mpy-cross", f"PYTHON={sys.executable}"])
    progress.advance()
    mpy_cross = compiler_source / "mpy-cross/build/mpy-cross"
    compiler_hash = file_hash(mpy_cross)
    for index, name in enumerate(sorted(modules)):
        # The source path supplies MicroPython's actual package/module identity.
        debug_flags = ["-X", "no-source-lines"] if options.minify else []
        bytecode = generated / f"module_{index}.mpy"
        module_state = BuildState(generated / f"module_{index}.json")
        module_hash = digest([compiler_hash, name, file_hash(generated / name), debug_flags])
        if not module_state.matches(module_hash, [bytecode]):
            temporary = bytecode.with_suffix(".mpy.compiled")
            run([mpy_cross, "-O0", *debug_flags, "-msmall-int-bits=31", "-s", name, "-o", temporary, generated / name])
            write_changed(bytecode, temporary.read_bytes())
            temporary.unlink()
            module_state.save(module_hash, [bytecode])
        progress.advance()

    progress.start("Compiling and linking runtime")
    softfloat_library, softfloat_flags, helper_exports = build_softfloat(ROOT, CACHE, emcc, env, toolchain)
    stamp = generated / "profile.sha256"
    if build.exists() and (not stamp.exists() or stamp.read_text() != profile_hash):
        shutil.rmtree(build)
    write_changed(stamp, profile_hash)
    build.mkdir(parents=True, exist_ok=True)
    if options.runtime == "native-errors" and modules_changed:
        (build / "frozen_content.c").unlink(missing_ok=True)
    print(("Reusing" if (runtime_build / "py/vm.o").exists() else "Compiling")
          + " cached MicroPython runtime with binary64 floats", flush=True)
    run(["make", "-s", "-j6", "-C", port, f"TOP={mp}", f"BUILD={runtime_build}",
         f"CONTRACT_BUILD={build}", f"GENERATED={generated}",
         "HEAP=" + heap_mode,
         "CC=" + shlex.join(map(str, emcc)), f"PYTHON={sys.executable}",
         f"SOFTFLOAT_LIB={softfloat_library}", "SOFTFLOAT_FLAGS=" + shlex.join(softfloat_flags),
         "SOFTFLOAT_EXPORTS=" + shlex.join(helper_exports)], env=env)
    raw = build / "contract.raw.wasm"
    progress.start("Optimizing WebAssembly", 3 + int(options.runtime == "asyncify") + int(options.minify))
    # Resolve the port's Asyncify control imports before final Casper validation.
    if options.casthon:
        tool = [options.casthon.resolve(), "__wasm"]
    else:
        run(["cargo", "build", "--quiet", "--locked", "--release", "--manifest-path", ROOT / "tools/wasm-softfloat/Cargo.toml"])
        tool = [ROOT / "tools/wasm-softfloat/target/release/wasm-softfloat"]
    mvp = generated / "contract.mvp.wasm"
    run([wasm_opt, raw, "-g", "--enable-bulk-memory", "--enable-sign-ext", "--enable-nontrapping-float-to-int",
         "--llvm-memory-copy-fill-lowering", "--signext-lowering", "-o", mvp])
    progress.advance()
    unwind_input = mvp
    if options.runtime == "asyncify":
        unwind_input = generated / "contract.asyncify.wasm"
        # Shrink live locals before saving continuations, preserving all driver
        # call boundaries until Asyncify has instrumented them.
        run([wasm_opt, mvp, "--disable-bulk-memory", "--disable-sign-ext",
             "--no-inline=cspr_*", "--no-inline=dispatch_body", "-Oz", "--asyncify",
             "--pass-arg=asyncify-imports@", "-g", "-o", unwind_input])
        progress.advance()
    # Pure integer SoftFloat helpers cannot raise Python exceptions. Lowering
    # after Asyncify also preserves the final validator's Casper-only imports.
    lowered = generated / "contract.softfloat.wasm"
    run([*tool, unwind_input, lowered])
    progress.advance()
    optimized = generated / "contract.optimized.wasm"
    run([wasm_opt, lowered, "-Oz", "--strip-debug", "--strip-producers", "--strip-target-features", "--mvp-features", "-o", optimized])
    run([*tool, "--check", optimized])
    progress.advance()
    minification = minify(optimized, wasm, wasm_opt, tool, generated / "minify") if options.minify else {"enabled": False}
    if not options.minify:
        shutil.copyfile(optimized, wasm)
    else:
        progress.advance()
    progress.start("Validating and instrumenting artifacts", 5)
    run([*tool, "--check", wasm])
    imports = {name for module, name, signature in interface(wasm)["imports"]}
    if ("casper_print" in imports) != (options.profile == "debug"):
        raise ValueError("Wasm casper_print import does not match the selected build profile")
    progress.advance()
    run([*tool, "--instrument", wasm, metered])
    progress.advance()
    run([*emcc, "-Oz", "--no-entry", "-sSTANDALONE_WASM=1", "-sFILESYSTEM=0", "-sSUPPORT_LONGJMP=0", "-sINITIAL_MEMORY=4194304", "-sSTACK_SIZE=262144",
         "-I" + str(ROOT / "native"), ROOT / "native/readback.c", "-Wl,--export=call", "-o", generated / "readback.raw.wasm"], env=env)
    progress.advance()
    readback_mvp = generated / "readback.mvp.wasm"
    run([wasm_opt, generated / "readback.raw.wasm", "--enable-bulk-memory", "--enable-sign-ext",
         "--enable-nontrapping-float-to-int", "--llvm-memory-copy-fill-lowering", "--signext-lowering",
         "-Oz", "-o", readback_mvp])
    run([*tool, readback_mvp, output_dir / "readback.wasm"])
    progress.advance()
    metadata = {"micropython": VERSION, "archiveSha256": SHA256, "bytes": wasm.stat().st_size,
                "sha256": hashlib.sha256(wasm.read_bytes()).hexdigest(), "profile": "procedural-softfloat-" + options.runtime,
                "buildProfile": options.profile, "debugPrint": options.profile == "debug",
                "exports": declaration["exports"], "upstreamFilesVerified": verify(mp, expected_source),
                "upstreamChanges": changed, "patches": patches, "asyncify": options.runtime == "asyncify",
                "jumpBufferBytes": 4096 if options.runtime == "asyncify" else 0,
                "exceptionMapping": "outer-c-dispatcher", "returnMapping": "typed-boundary-and-explicit-cl-values",
                "signatures": declaration["signatures"],
                "pythonFloatBits": 64, "wasmFloatInstructions": False,
                "heap": {"mode": heap_mode,
                         "allocator": "emmalloc", "automaticCollection": False,
                         "gcEnabled": heap_mode != "emmalloc-gc0",
                         "objectAllocator": "emmalloc" if heap_mode == "emmalloc-gc0" else "micropython-gc",
                         "initialRegionBytes": {"static": 2097152, "split": 65536, "emmalloc-gc0": 0, "emmalloc-gc1": None}[heap_mode],
                         "initialRegionPolicy": "available-emmalloc-tail" if heap_mode == "emmalloc-gc1" else "fixed",
                         "initialMemoryBytes": 524288 if heap_mode == "split" else 4194304,
                         "memoryGrowth": heap_mode == "split",
                         "maximumMemoryBytes": 4194304},
                "softfloat": {"revision": SOFTFLOAT_REVISION, "archiveSha256": SOFTFLOAT_SHA256},
                "minification": minification,
                "cache": {"runtimeBuild": str(runtime_build), "runtimeProfile": profile_hash}}
    write_changed(report, json.dumps(metadata, indent=2) + "\n")
    if target == "counter":
        write_changed(output_dir / "build-report.json", json.dumps(metadata, indent=2) + "\n")
    state.save(fingerprint(), outputs)
    progress.advance()
    progress.finish()
    if not options.progress:
        print(json.dumps(metadata, indent=2))


if __name__ == "__main__":
    main()
