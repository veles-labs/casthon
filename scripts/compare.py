"""Preserve measured results and compare to the recorded JS counter run."""
import hashlib
import json
import os
from pathlib import Path

root = Path(__file__).resolve().parent.parent
output = root / os.environ.get("CSPR_BUILD_DIR", "build")
python = json.loads((output / "devnet-report.json").read_text())
javascript = json.loads((root / "reference/js-counter-report.json").read_text())
if not python.get("passed") or not javascript.get("passed"):
    raise SystemExit("Both devnet runs must pass before comparison")
if not all(python.get(check) for check in ("abiMatches", "lowLevelHostApiMatches", "fullFfiMatches", "missingExportRejected", "dispatchMatches", "hostErrorsUnwind", "wireTypesMatch", "nativeUnwindingMatches", "networkStopped")):
    raise SystemExit("Run the full devnet validation before comparison")
for target, field in (("basic", "wasm"), ("api_smoke", "apiSmokeWasm"), ("ffi_smoke", "ffiSmokeWasm"), ("dispatch_smoke", "dispatchSmokeWasm"), ("native_unwind", "nativeUnwindWasm")):
    artifact = output / (target + ".wasm")
    if hashlib.sha256(artifact.read_bytes()).hexdigest() != python[field]["sha256"]:
        raise SystemExit("Devnet result does not match current " + target + " artifact; rerun validation")
comparison = {
    "pythonArtifact": python["wasm"], "javascriptArtifact": javascript["wasm"],
    "sizeReductionPercent": 100 * (1 - python["wasm"]["bytes"] / javascript["wasm"]["bytes"]),
    "caveat": "Different SDK profiles: Python uses procedural host calls with 3 stored fields and 10 entrypoints, binary64 SoftFloat and catchable native exceptions; JS has 1 field and 4 entrypoints, float support and catchable exceptions. This is not a controlled language benchmark.",
    "gas": [],
}
for label in ("install", "increment", "increment_by", "typed-get-return"):
    py = next(t for t in python["transactions"] if t["label"] == label and t["error"] is None)
    js = next(t for t in javascript["transactions"] if t["label"] == label and t["error"] is None)
    a, b = int(py["consumed"]), int(js["consumed"])
    comparison["gas"].append({"operation": label, "pythonGas": str(a), "javascriptGas": str(b),
                              "reductionPercent": 100 * (1 - a / b)})
results = root / "results"
profile = json.loads((output / "basic-build-report.json").read_text())
if profile.get("profile") == "procedural-softfloat-native-errors":
    results /= "native-errors"
if profile.get("minification", {}).get("enabled"):
    results /= "minified"
results.mkdir(parents=True, exist_ok=True)
(results / "devnet-report.json").write_text(json.dumps(python, indent=2) + "\n")
(results / "build-report.json").write_bytes((output / "basic-build-report.json").read_bytes())
(results / "api_smoke-build-report.json").write_bytes((output / "api_smoke-build-report.json").read_bytes())
(results / "ffi_smoke-build-report.json").write_bytes((output / "ffi_smoke-build-report.json").read_bytes())
(results / "dispatch_smoke-build-report.json").write_bytes((output / "dispatch_smoke-build-report.json").read_bytes())
(results / "native_unwind-build-report.json").write_bytes((output / "native_unwind-build-report.json").read_bytes())
(results / "comparison.json").write_text(json.dumps(comparison, indent=2) + "\n")
print(json.dumps(comparison, indent=2))
