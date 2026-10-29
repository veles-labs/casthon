use serde_json::Value;
#[cfg(unix)]
use std::os::unix::fs::PermissionsExt;
use std::{
    fs,
    path::{Path, PathBuf},
    process::{Command, Output},
};
use tempfile::{TempDir, tempdir};

fn sdk() -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR"))
}
fn command(project: &Path) -> Command {
    let mut command = Command::new(env!("CARGO_BIN_EXE_casthon"));
    command.current_dir(project).args([
        "--project-root",
        project.to_str().unwrap(),
        "--python",
        "python3",
    ]);
    command
}
fn success(output: Output) -> Output {
    assert!(
        output.status.success(),
        "stdout={}\nstderr={}",
        String::from_utf8_lossy(&output.stdout),
        String::from_utf8_lossy(&output.stderr)
    );
    output
}
fn fake_sdk() -> TempDir {
    let root = tempdir().unwrap();
    fs::create_dir_all(root.path().join("scripts")).unwrap();
    fs::create_dir_all(root.path().join("native")).unwrap();
    fs::copy(
        sdk().join("native/toolchain.json"),
        root.path().join("native/toolchain.json"),
    )
    .unwrap();
    fs::write(root.path().join("scripts/build.py"), r#"import argparse, hashlib, json, sys
from pathlib import Path
p=argparse.ArgumentParser()
p.add_argument('source')
p.add_argument('--output-dir')
p.add_argument('--project-root')
p.add_argument('--micropython')
p.add_argument('--runtime')
p.add_argument('--profile', choices=('debug','release'), default='debug')
p.add_argument('--heap')
p.add_argument('--casthon')
p.add_argument('--progress', action='store_true')
p.add_argument('--minify', action='store_true')
a=p.parse_args()
Path('arguments.json').write_text(json.dumps(vars(a)))
out=Path(a.output_dir)
if a.runtime=='native-errors': out=out/'native-errors'
if a.profile=='release': out=out/'release'
if a.minify: out=out/'minified'
out.mkdir(parents=True,exist_ok=True)
data=b'\0asm\1\0\0\0'
name=Path(a.source).stem
(out/(name+'.wasm')).write_bytes(data)
(out/(name+'.metered.wasm')).write_bytes(data)
(out/(name+'-build-report.json')).write_text(json.dumps({'sha256':hashlib.sha256(data).hexdigest(),'micropython':a.micropython,'buildProfile':a.profile,'entryPoints':{'flip':{'args':[],'returns':'Unit','access':'public','groups':[],'entryPointType':'called','payment':'caller'},'get':{'args':[],'returns':'Bool','access':'public','groups':[],'entryPointType':'called','payment':'caller'},'set':{'args':[{'name':'value','type':'Bool','hasDefault':False}],'returns':'Unit','access':'public','groups':[],'entryPointType':'called','payment':'caller'}}}))
print('worker output belongs on stderr in JSON mode')
print('worker diagnostic on stderr', file=sys.stderr)
"#).unwrap();
    root
}

#[cfg(unix)]
fn fake_casper_cli(directory: &Path, execution: &str) -> (PathBuf, PathBuf) {
    let binary = directory.join("casper-cli");
    let log = directory.join("casper-cli.log");
    let body = format!(
        r#"#!/bin/sh
printf '%s\n' "$*" >> '{}'
fixture_dir='{}'
if [ "$1" = "--version" ]; then
  printf 'casper-cli 0.4.0\n'
elif [ "$1 $2 $3" = "transaction put --help" ]; then
  printf '%s\n' 'Build a session transaction from Wasm' '--install-upgrade --simulate --speculative --raw' 'Simulate execution locally using state queries to the network RPC'
elif [ "$1 $2 $3" = "transaction call --help" ]; then
  printf '%s\n' 'Call a stored contract by hash' '--package --simulate --speculative --raw'
elif [ "$1 $2 $3" = "network use testnet" ]; then
  printf 'Active network: testnet\n'
elif [ "$1 $2" = "network list" ]; then
  printf '| Name | Chain | Active | RPC |\n| testnet | casper-test | yes | https://rpc |\n'
elif [ "$1 $2" = "transaction put" ]; then
  case " $* " in
    *' --simulate '*) printf '%s\n' '{{"schemaVersion":1,"success":true,"blockHeight":42,"gasConsumed":"137","returnValue":null,"error":null}}' ;;
    *' --speculative '*) printf '%s\n' '{{"execution_result":{{"consumed":"137","error":null}}}}' ;;
    *) printf 'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa\n' ;;
  esac
elif [ "$1 $2" = "transaction call" ]; then
  if [ -f "$fixture_dir/need-input" ]; then
    printf 'Wallet unlock: ' >&2
    IFS= read -r answer
    if [ "$answer" != 'test-password' ]; then exit 9; fi
  fi
  if [ -f "$fixture_dir/preview.json" ]; then
    cat "$fixture_dir/preview.json"
    if [ -f "$fixture_dir/preview-failed" ]; then exit 7; fi
    exit 0
  fi
  case " $* " in
    *' --simulate '*) printf '%s\n' '{{"schemaVersion":1,"success":true,"blockHeight":42,"gasConsumed":"137","returnValue":{{"cl_type":"Bool","bytes":"01","parsed":true}},"error":null}}' ;;
    *' --speculative '*) printf '%s\n' '{{"execution_result":{{"consumed":"137","error":null}}}}' ;;
    *' --raw '*) printf 'bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb\n' ;;
    *) printf 'Contract call submitted to testnet: bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb\n' ;;
  esac
elif [ "$1 $2" = "transaction get" ]; then
  if [ -f '{}' ]; then
    printf 'null\n'
    rm '{}'
  else
    printf '%s\n' '{}'
  fi
else
  printf 'unexpected invocation: %s\n' "$*" >&2
  exit 9
fi
"#,
        log.display(),
        directory.display(),
        directory.join("execution-pending").display(),
        directory.join("execution-pending").display(),
        execution.replace('\'', "'\\''")
    );
    fs::write(&binary, body).unwrap();
    fs::set_permissions(&binary, fs::Permissions::from_mode(0o755)).unwrap();
    (binary, log)
}

#[cfg(unix)]
fn deployed_call_project() -> TempDir {
    let project = tempdir().unwrap();
    let artifact = serde_json::json!({
        "source": "contracts/flipper.py", "wasm": "build/release/flipper.wasm",
        "buildReport": "build/release/flipper-build-report.json", "sha256": "artifact-hash",
        "micropython": "1.29.0", "buildProfile": "release"
    });
    let manifest = serde_json::json!({
        "schemaVersion": 1, "name": "flipper", "networkProfile": "testnet",
        "chainName": "casper-test", "history": [],
        "current": {
            "status": "executed", "networkProfile": "testnet", "chainName": "casper-test",
            "artifact": artifact,
            "abi": {"artifactSha256": "artifact-hash", "entryPoints": {
                "flip": {"args": [], "returns": "Unit", "access": "public",
                         "entryPointType": "called", "payment": "caller"},
                "get": {"args": [], "returns": "Bool", "access": "public",
                         "entryPointType": "called", "payment": "caller"}
            }},
            "signer": "wallet:account-0", "arguments": [], "paymentAmountCspr": "800",
            "gasPriceTolerance": 1, "transactionHash": "transaction-v1-hash-original",
            "submittedAtUnix": 1, "casthonVersion": "0.1.0", "casperCliVersion": "0.4.0",
            "callTarget": {"kind": "package", "hash": "package-111"}
        }
    });
    fs::create_dir_all(project.path().join("deployments/testnet")).unwrap();
    fs::write(
        project.path().join("deployments/testnet/flipper.json"),
        serde_json::to_vec(&manifest).unwrap(),
    )
    .unwrap();
    project
}

#[test]
#[cfg(unix)]
fn call_broadcast_waits_through_pending_execution_and_reports_success() {
    let project = deployed_call_project();
    let manifest_path = project.path().join("deployments/testnet/flipper.json");
    let manifest_before = fs::read(&manifest_path).unwrap();
    let execution = r#"{"block_height":43,"execution_result":{"Version2":{"error_message":null}}}"#;
    let (casper_cli, log) = fake_casper_cli(project.path(), execution);
    fs::write(project.path().join("execution-pending"), "").unwrap();

    let output = success(
        command(project.path())
            .arg("--casper-cli")
            .arg(&casper_cli)
            .args(["call", "flipper", "flip", "--broadcast", "-vv"])
            .output()
            .unwrap(),
    );
    let stdout = String::from_utf8_lossy(&output.stdout);
    let stderr = String::from_utf8_lossy(&output.stderr);
    assert!(
        stdout.contains("Transaction: transaction-v1-hash-bbbb"),
        "{stdout}"
    );
    assert!(stderr.contains("Waiting for execution"), "{stderr}");
    assert!(stdout.contains("Executed in block 43"), "{stdout}");
    assert!(
        stderr.contains("Signing and submitting contract call"),
        "{stderr}"
    );
    assert!(stderr.contains("Transaction is pending"), "{stderr}");
    assert!(
        stderr.contains("Checking execution status (attempt 2)"),
        "{stderr}"
    );
    let calls = fs::read_to_string(log).unwrap();
    let submissions: Vec<_> = calls
        .lines()
        .filter(|line| line.starts_with("transaction call package-111 "))
        .collect();
    assert_eq!(submissions.len(), 1, "{calls}");
    assert!(submissions[0].ends_with("--package --raw"), "{calls}");
    assert_eq!(
        calls
            .matches("transaction get transaction-v1-hash-bbbb")
            .count(),
        2,
        "{calls}"
    );
    assert_eq!(fs::read(&manifest_path).unwrap(), manifest_before);
}

#[test]
#[cfg(unix)]
fn call_broadcast_reports_execution_failures() {
    for execution in [
        r#"{"block_height":43,"execution_result":{"Version2":{"error_message":"Out of gas error"}}}"#,
        r#"{"block_height":43,"execution_result":{"Version1":{"Failure":{"error_message":"Out of gas error"}}}}"#,
    ] {
        let project = deployed_call_project();
        let (casper_cli, log) = fake_casper_cli(project.path(), execution);
        let output = command(project.path())
            .arg("--casper-cli")
            .arg(&casper_cli)
            .args(["call", "flipper", "flip", "--broadcast"])
            .output()
            .unwrap();
        assert!(!output.status.success());
        let stdout = String::from_utf8_lossy(&output.stdout);
        let stderr = String::from_utf8_lossy(&output.stderr);
        assert!(stderr.contains("failed: Out of gas error"), "{stderr}");
        assert!(
            stderr.contains("Transaction transaction-v1-hash-bbbb"),
            "{stderr}"
        );
        assert!(!stdout.contains("Executed in block"), "{stdout}");
        let calls = fs::read_to_string(log).unwrap();
        assert_eq!(
            calls
                .lines()
                .filter(|line| line.starts_with("transaction call package-111 "))
                .count(),
            1,
            "{calls}"
        );
    }
}

#[test]
#[cfg(unix)]
fn call_broadcast_no_wait_returns_without_querying_execution() {
    let project = deployed_call_project();
    let (casper_cli, log) = fake_casper_cli(project.path(), "null");
    let output = success(
        command(project.path())
            .arg("--casper-cli")
            .arg(&casper_cli)
            .args(["call", "flipper", "flip", "--broadcast", "--no-wait"])
            .output()
            .unwrap(),
    );
    let stdout = String::from_utf8_lossy(&output.stdout);
    assert!(
        stdout.contains("Submitted transaction-v1-hash-bbbb"),
        "{stdout}"
    );
    assert!(!stdout.contains("Waiting for execution"), "{stdout}");
    assert!(!fs::read_to_string(log).unwrap().contains("transaction get"));
}

#[test]
#[cfg(unix)]
fn call_broadcast_timeout_reports_the_submitted_hash() {
    let project = deployed_call_project();
    let (casper_cli, log) = fake_casper_cli(project.path(), "null");
    let output = command(project.path())
        .arg("--casper-cli")
        .arg(&casper_cli)
        .args([
            "call",
            "flipper",
            "flip",
            "--broadcast",
            "--wait-timeout",
            "0",
        ])
        .output()
        .unwrap();
    assert!(!output.status.success());
    let stderr = String::from_utf8_lossy(&output.stderr);
    assert!(
        stderr.contains("Timed out waiting for transaction-v1-hash-bbbb"),
        "{stderr}"
    );
    assert!(
        stderr.contains("already submitted and may still execute"),
        "{stderr}"
    );
    let calls = fs::read_to_string(log).unwrap();
    assert_eq!(calls.matches("transaction get ").count(), 1, "{calls}");
}

#[test]
#[cfg(unix)]
fn call_text_verbosity_controls_diagnostics_without_changing_results() {
    let project = deployed_call_project();
    let (casper_cli, _) = fake_casper_cli(project.path(), "null");
    for level in [None, Some("-q"), Some("-v"), Some("-vv")] {
        let mut call = command(project.path());
        call.arg("--casper-cli")
            .arg(&casper_cli)
            .args(["call", "flipper", "get", "--simulate"]);
        if let Some(level) = level {
            call.arg(level);
        }
        let output = success(call.output().unwrap());
        let stdout = String::from_utf8_lossy(&output.stdout);
        let stderr = String::from_utf8_lossy(&output.stderr);
        if level == Some("-q") {
            assert_eq!(stdout, "true\n");
            assert!(stderr.is_empty(), "{stderr}");
        } else {
            assert!(stdout.contains("Return Bool: true"), "{stdout}");
            assert!(
                stdout.contains("Gas consumed: 0.000000137 CSPR"),
                "{stdout}"
            );
            assert!(stderr.contains("Calling flipper::get"), "{stderr}");
        }
        assert_eq!(
            stderr.contains("Checking Veles Labs casper-cli"),
            matches!(level, Some("-v" | "-vv"))
        );
        assert_eq!(stderr.contains("Shelling out"), level == Some("-vv"));
        assert!(!stdout.contains("Shelling out"), "{stdout}");
    }
}

#[test]
#[cfg(unix)]
fn call_json_is_one_typed_document_at_every_verbosity() {
    let project = deployed_call_project();
    let (casper_cli, _) = fake_casper_cli(project.path(), "null");
    for format in [vec!["--json"], vec!["--format", "json"]] {
        for level in [None, Some("-q"), Some("-v"), Some("-vv")] {
            let mut call = command(project.path());
            call.arg("--casper-cli")
                .arg(&casper_cli)
                .args(["call", "flipper", "get", "--simulate"])
                .args(&format);
            if let Some(level) = level {
                call.arg(level);
            }
            let output = success(call.output().unwrap());
            let result: Value = serde_json::from_slice(&output.stdout).unwrap();
            assert_eq!(result["schemaVersion"], 1);
            assert_eq!(result["command"], "call");
            assert_eq!(result["deployment"], "flipper");
            assert_eq!(result["entryPoint"], "get");
            assert_eq!(result["network"], "testnet");
            assert_eq!(result["mode"], "simulation");
            assert_eq!(result["status"], "simulated");
            assert_eq!(result["success"], true);
            assert_eq!(result["exitCode"], 0);
            assert_eq!(result["returnValue"]["cl_type"], "Bool");
            assert_eq!(result["returnValue"]["parsed"], true);
            assert_eq!(result["gasConsumed"], "137");
            assert_eq!(result["blockHeight"], 42);
            assert!(result["error"].is_null());
            let stderr = String::from_utf8_lossy(&output.stderr);
            if matches!(level, None | Some("-q")) {
                assert!(stderr.is_empty(), "{stderr}");
            } else {
                assert!(
                    stderr.contains("Checking Veles Labs casper-cli"),
                    "{stderr}"
                );
                assert_eq!(stderr.contains("Shelling out"), level == Some("-vv"));
            }
        }
    }
}

#[test]
#[cfg(unix)]
fn json_errors_cover_project_validation_and_backend_execution() {
    for broken_project in [false, true] {
        let project = deployed_call_project();
        if broken_project {
            fs::write(project.path().join("pyproject.toml"), "invalid = [").unwrap();
        }
        let output = command(project.path())
            .args(["call", "flipper", "missing", "--json"])
            .output()
            .unwrap();
        assert!(!output.status.success());
        let result: Value = serde_json::from_slice(&output.stdout).unwrap();
        assert_eq!(result["status"], "failed");
        assert_eq!(result["success"], false);
        let expected = if broken_project {
            "Invalid configuration"
        } else {
            "Unknown entry point"
        };
        assert!(
            result["error"].as_str().unwrap().contains(expected),
            "{result}"
        );
    }
    let project = deployed_call_project();
    let (casper_cli, _) = fake_casper_cli(project.path(), "null");
    fs::write(project.path().join("preview.json"),
        r#"{"success":false,"error":"Revert: User(1)","blockHeight":42,"gasConsumed":"19","returnValue":null}"#).unwrap();
    fs::write(project.path().join("preview-failed"), "").unwrap();
    let output = command(project.path())
        .arg("--casper-cli")
        .arg(&casper_cli)
        .args(["call", "flipper", "get", "--simulate", "--json"])
        .output()
        .unwrap();
    assert_eq!(output.status.code(), Some(7));
    let result: Value = serde_json::from_slice(&output.stdout).unwrap();
    assert_eq!(result["error"], "Revert: User(1)");
    assert_eq!(result["status"], "failed");
    assert_eq!(result["gasConsumed"], "19");
    assert_eq!(result["exitCode"], 7);
}

#[test]
#[cfg(unix)]
fn broadcast_json_preserves_receipts_errors_and_submission_hashes() {
    for (execution, no_wait, expected_status) in [
        (
            r#"{"block_height":43,"execution_result":{"Version2":{"error_message":null,"consumed":"137"}}}"#,
            false,
            "executed",
        ),
        (
            r#"{"block_height":43,"execution_result":{"Version2":{"error_message":"Out of gas error","consumed":"137"}}}"#,
            false,
            "failed",
        ),
        ("null", true, "submitted"),
        ("null", false, "failed"),
    ] {
        let project = deployed_call_project();
        let (casper_cli, _) = fake_casper_cli(project.path(), execution);
        let mut call = command(project.path());
        call.arg("--casper-cli").arg(&casper_cli).args([
            "call",
            "flipper",
            "flip",
            "--broadcast",
            "--wait-timeout",
            "0",
            "--json",
            "-vv",
        ]);
        if no_wait {
            call.arg("--no-wait");
        }
        let output = call.output().unwrap();
        let result: Value = serde_json::from_slice(&output.stdout).unwrap();
        assert_eq!(result["status"], expected_status);
        assert!(
            result["transactionHash"]
                .as_str()
                .unwrap()
                .starts_with("transaction-v1-hash-bbbb")
        );
        assert_eq!(output.status.success(), expected_status != "failed");
        if execution != "null" {
            assert_eq!(result["blockHeight"], 43);
            assert_eq!(result["gasConsumed"], "137");
            assert!(result["result"]["execution_result"].is_object());
        }
    }
}

#[test]
#[cfg(unix)]
fn deployment_json_captures_nested_builds_and_preview_or_broadcast_outcomes() {
    for (flags, expected_status) in [
        (vec![], "speculated"),
        (vec!["--simulate"], "simulated"),
        (vec!["--broadcast"], "executed"),
        (vec!["--broadcast", "--no-wait"], "submitted"),
    ] {
        let project = tempdir().unwrap();
        let tooling = fake_sdk();
        fs::create_dir(project.path().join("contracts")).unwrap();
        fs::write(
            project.path().join("contracts/flipper.py"),
            "def call(): pass\n",
        )
        .unwrap();
        fs::write(
            project.path().join("pyproject.toml"),
            "[tool.casthon]\nmicropython='1.29.0'\ntargets=['contracts/flipper.py']\n",
        )
        .unwrap();
        let execution = r#"{"block_height":43,"execution_result":{"Version2":{"error_message":null,"consumed":"137","effects":[{"key":"package-111"}]}}}"#;
        let (casper_cli, _) = fake_casper_cli(project.path(), execution);
        let output = success(
            command(project.path())
                .arg("--sdk-root")
                .arg(tooling.path())
                .arg("--casper-cli")
                .arg(&casper_cli)
                .args([
                    "deploy",
                    "--network",
                    "testnet",
                    "--from",
                    "wallet:account-0",
                    "--format",
                    "json",
                ])
                .args(flags)
                .output()
                .unwrap(),
        );
        let result: Value = serde_json::from_slice(&output.stdout).unwrap();
        assert_eq!(result["command"], "deploy");
        assert_eq!(result["status"], expected_status);
        assert!(
            output.stderr.is_empty(),
            "{}",
            String::from_utf8_lossy(&output.stderr)
        );
        if matches!(expected_status, "executed" | "submitted") {
            assert!(Path::new(result["manifest"].as_str().unwrap()).is_file());
        }
    }
}

#[test]
#[cfg(unix)]
fn json_keeps_wallet_prompts_on_stderr_and_passes_input_to_backend() {
    use std::io::Write;
    use std::process::Stdio;
    let project = deployed_call_project();
    let (casper_cli, _) = fake_casper_cli(project.path(), "null");
    fs::write(project.path().join("need-input"), "").unwrap();
    let mut child = command(project.path())
        .arg("--casper-cli")
        .arg(&casper_cli)
        .args(["call", "flipper", "get", "--simulate", "--json"])
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .spawn()
        .unwrap();
    child
        .stdin
        .take()
        .unwrap()
        .write_all(b"test-password\n")
        .unwrap();
    let output = success(child.wait_with_output().unwrap());
    let result: Value = serde_json::from_slice(&output.stdout).unwrap();
    assert_eq!(result["returnValue"]["parsed"], true);
    assert_eq!(String::from_utf8(output.stderr).unwrap(), "Wallet unlock: ");
    assert!(
        !String::from_utf8(output.stdout)
            .unwrap()
            .contains("test-password")
    );
}

#[test]
#[cfg(unix)]
fn json_build_failure_emits_one_error_result_and_preserves_exit_code() {
    let project = tempdir().unwrap();
    let tooling = fake_sdk();
    fs::create_dir(project.path().join("contracts")).unwrap();
    fs::write(
        project.path().join("contracts/flipper.py"),
        "def call(): pass\n",
    )
    .unwrap();
    fs::write(
        project.path().join("pyproject.toml"),
        "[tool.casthon]\nmicropython='1.29.0'\ntargets=['contracts/flipper.py']\n",
    )
    .unwrap();
    fs::write(tooling.path().join("scripts/build.py"),
        "import sys\nprint('compiler diagnostic on stdout')\nprint('compiler error on stderr', file=sys.stderr)\nsys.exit(9)\n").unwrap();
    let (casper_cli, log) = fake_casper_cli(project.path(), "null");
    let output = command(project.path())
        .arg("--sdk-root")
        .arg(tooling.path())
        .arg("--casper-cli")
        .arg(&casper_cli)
        .args([
            "deploy",
            "--network",
            "testnet",
            "--from",
            "wallet:account-0",
            "--json",
        ])
        .output()
        .unwrap();
    assert_eq!(output.status.code(), Some(9));
    let result: Value = serde_json::from_slice(&output.stdout).unwrap();
    assert_eq!(result["success"], false);
    assert_eq!(result["exitCode"], 9);
    assert!(
        result["error"]
            .as_str()
            .unwrap()
            .contains("Release build failed")
    );
    assert!(
        !fs::read_to_string(log)
            .unwrap()
            .contains("transaction put build/")
    );
    let build_log =
        fs::read_to_string(project.path().join("build/release/flipper-build.log")).unwrap();
    assert!(build_log.contains("compiler diagnostic on stdout"));
    assert!(build_log.contains("compiler error on stderr"));
}

#[test]
#[cfg(unix)]
fn malformed_backend_output_is_a_json_error_instead_of_leaking_stdout() {
    let project = deployed_call_project();
    let (casper_cli, _) = fake_casper_cli(project.path(), "null");
    fs::write(
        project.path().join("preview.json"),
        "Simulation result in an older CLI format\n",
    )
    .unwrap();
    let output = command(project.path())
        .arg("--casper-cli")
        .arg(&casper_cli)
        .args(["call", "flipper", "get", "--simulate", "--json", "-vv"])
        .output()
        .unwrap();
    assert!(!output.status.success());
    let result: Value = serde_json::from_slice(&output.stdout).unwrap();
    assert_eq!(result["status"], "failed");
    assert!(
        result["error"]
            .as_str()
            .unwrap()
            .contains("structured execution JSON")
    );
}

#[test]
fn test_delegates_arguments_working_directory_and_exit_code() {
    let project = tempdir().unwrap();
    fs::write(project.path().join("pytest.py"), "import json,os,sys\nprint(json.dumps({'args':sys.argv[1:],'cwd':os.getcwd()}))\nraise SystemExit(7)\n").unwrap();
    let output = command(project.path())
        .args([
            "test",
            "--",
            "tests/a b.py",
            "-k",
            "transfer and not failure",
            "--help",
        ])
        .output()
        .unwrap();
    assert_eq!(output.status.code(), Some(7));
    let received: Value = serde_json::from_slice(&output.stdout).unwrap();
    assert_eq!(
        received["args"],
        serde_json::json!(["tests/a b.py", "-k", "transfer and not failure", "--help"])
    );
    assert_eq!(
        Path::new(received["cwd"].as_str().unwrap())
            .canonicalize()
            .unwrap(),
        project.path().canonicalize().unwrap()
    );
}

#[test]
fn test_suite_options_set_defaults_and_keep_python_arguments_intact() {
    let project = tempdir().unwrap();
    fs::write(
        project.path().join("pytest.py"),
        "import json,os,sys\nprint(json.dumps({'args':sys.argv[1:],'live':os.environ.get('CSPR_LIVE_TESTS')}))\nraise SystemExit(7)\n",
    )
    .unwrap();
    for (suite, directory, enabled) in
        [("--live", "tests/live", "1"), ("--wasm", "tests/wasm", "0")]
    {
        let output = command(project.path())
            .env("CSPR_LIVE_TESTS", "0")
            .args([
                "test",
                suite,
                "--",
                "tests/custom/test_selected.py::TestExample",
                "-q",
                "-k",
                "transfer and not failure",
            ])
            .output()
            .unwrap();
        assert_eq!(output.status.code(), Some(7));
        let received: Value = serde_json::from_slice(&output.stdout).unwrap();
        assert_eq!(received["live"], enabled);
        assert_eq!(
            received["args"],
            serde_json::json!([
                "-o",
                format!("testpaths={directory}"),
                "tests/custom/test_selected.py::TestExample",
                "-q",
                "-k",
                "transfer and not failure"
            ])
        );
    }
    let output = command(project.path())
        .env_remove("CSPR_LIVE_TESTS")
        .args(["test", "--", "--live", "--wasm"])
        .output()
        .unwrap();
    assert_eq!(output.status.code(), Some(7));
    let received: Value = serde_json::from_slice(&output.stdout).unwrap();
    assert_eq!(received["args"], serde_json::json!(["--live", "--wasm"]));
    assert!(received["live"].is_null());
}

#[test]
fn test_requires_the_runner_separator_and_rejects_conflicting_suites() {
    let project = tempdir().unwrap();
    for arguments in [
        vec!["test", "-q"],
        vec!["test", "tests/test_contract.py"],
        vec!["test", "--live", "--wasm"],
    ] {
        let output = command(project.path()).args(arguments).output().unwrap();
        assert_eq!(output.status.code(), Some(2));
        assert!(output.stdout.is_empty());
    }
    let output = success(
        command(project.path())
            .args(["test", "--help"])
            .output()
            .unwrap(),
    );
    let help = String::from_utf8_lossy(&output.stdout);
    assert!(help.contains("--live"), "{help}");
    assert!(help.contains("--wasm"), "{help}");
    assert!(help.contains("PYTEST_ARGS"), "{help}");
}

#[test]
fn check_is_a_thin_mypy_command() {
    let project = tempdir().unwrap();
    fs::write(
        project.path().join("mypy.py"),
        "import json,sys\nprint(json.dumps(sys.argv[1:]))\n",
    )
    .unwrap();
    let output = success(
        command(project.path())
            .args(["check", "contracts", "--strict"])
            .output()
            .unwrap(),
    );
    assert_eq!(
        serde_json::from_slice::<Value>(&output.stdout).unwrap(),
        serde_json::json!(["contracts", "--strict"])
    );
}

#[test]
#[cfg(unix)]
fn deploy_builds_release_and_speculatively_executes_without_a_manifest() {
    let project = tempdir().unwrap();
    let tooling = fake_sdk();
    fs::create_dir(project.path().join("contracts")).unwrap();
    fs::write(
        project.path().join("contracts/flipper.py"),
        "def call(): pass\n",
    )
    .unwrap();
    fs::write(
        project.path().join("pyproject.toml"),
        "[tool.casthon]\nmicropython='1.29.0'\ntargets=['contracts/flipper.py']\n",
    )
    .unwrap();
    let (casper_cli, log) = fake_casper_cli(project.path(), "null");
    let output = success(
        command(project.path())
            .args(["--sdk-root", tooling.path().to_str().unwrap()])
            .arg("--casper-cli")
            .arg(&casper_cli)
            .args([
                "deploy",
                "--network",
                "testnet",
                "--from",
                "wallet:account-0",
                "--arg",
                "initial:Bool=false",
                "-vv",
            ])
            .output()
            .unwrap(),
    );
    let stdout = String::from_utf8_lossy(&output.stdout);
    let stderr = String::from_utf8_lossy(&output.stderr);
    assert!(!stdout.contains("Built "), "{stdout}");
    assert!(
        stderr.contains("Speculatively executing installation"),
        "{stderr}"
    );
    assert!(stdout.contains("Execution succeeded"), "{stdout}");
    assert!(
        stderr.contains("Checking Veles Labs casper-cli"),
        "{stderr}"
    );
    assert!(
        stderr.contains("Selecting casper-cli network testnet"),
        "{stderr}"
    );
    assert!(
        stderr.contains("casper-cli reads terminal input directly"),
        "{stderr}"
    );
    assert!(
        stderr.contains("Shelling out (capturing output):")
            && stderr.contains("transaction put build/release/flipper.wasm")
            && stderr.contains("--speculative"),
        "{stderr}"
    );
    assert!(stderr.contains("── casper-cli output"), "{stderr}");
    assert!(
        stderr.contains("Speculatively executing installation finished after"),
        "{stderr}"
    );
    assert!(project.path().join("build/release/flipper.wasm").is_file());
    assert!(!project.path().join("deployments").exists());
    let calls = fs::read_to_string(&log).unwrap();
    assert!(calls.contains("network use testnet"), "{calls}");
    assert!(
        calls.contains("transaction put build/release/flipper.wasm"),
        "{calls}"
    );
    assert!(calls.contains("--install-upgrade"), "{calls}");
    assert!(calls.contains("--arg initial:Bool=false"), "{calls}");
    assert!(calls.contains("--speculative"), "{calls}");

    let simulated = success(
        command(project.path())
            .arg("--casper-cli")
            .arg(&casper_cli)
            .args([
                "deploy",
                "--network",
                "testnet",
                "--from",
                "wallet:account-0",
                "--arg",
                "initial:Bool=false",
                "--no-build",
                "--simulate",
                "-vv",
            ])
            .output()
            .unwrap(),
    );
    let stdout = String::from_utf8_lossy(&simulated.stdout);
    let stderr = String::from_utf8_lossy(&simulated.stderr);
    assert!(
        stderr.contains("Simulating installation locally"),
        "{stderr}"
    );
    assert!(stdout.contains("Execution succeeded"), "{stdout}");
    assert!(
        stderr.contains("Simulating installation locally finished after"),
        "{stderr}"
    );
    let calls = fs::read_to_string(&log).unwrap();
    assert!(calls.contains("--simulate"), "{calls}");
    assert!(!calls.contains("transaction get"), "{calls}");
}

#[test]
#[cfg(unix)]
fn deploy_broadcast_waits_and_records_an_executed_manifest() {
    let project = tempdir().unwrap();
    let tooling = fake_sdk();
    fs::create_dir(project.path().join("contracts")).unwrap();
    fs::write(
        project.path().join("contracts/flipper.py"),
        "def call(): pass\n",
    )
    .unwrap();
    fs::write(
        project.path().join("pyproject.toml"),
        "[tool.casthon]\nmicropython='1.29.0'\ntargets=['contracts/flipper.py']\n",
    )
    .unwrap();
    let execution = r#"{"block_hash":"block-123","block_height":42,"execution_result":{"Version2":{"error_message":null,"consumed":"137","effects":[{"key":"package-111"},{"key":"addressable-entity-222"},{"value":"byte-code-333"}]}}}"#;
    let (casper_cli, log) = fake_casper_cli(project.path(), execution);
    let output = success(
        command(project.path())
            .args(["--sdk-root", tooling.path().to_str().unwrap()])
            .arg("--casper-cli")
            .arg(&casper_cli)
            .args([
                "deploy",
                "--network",
                "testnet",
                "--from",
                "wallet:account-0",
                "--arg",
                "initial:Bool=true",
                "--payment-amount",
                "23.5",
                "--broadcast",
                "-vv",
            ])
            .output()
            .unwrap(),
    );
    let stdout = String::from_utf8_lossy(&output.stdout);
    let stderr = String::from_utf8_lossy(&output.stderr);
    assert!(
        stderr.contains("Submitted transaction-v1-hash-aaaa"),
        "{stderr}"
    );
    assert!(stdout.contains("Executed in block 42"), "{stdout}");
    assert!(
        stderr.contains("Callable entry points: flip, get, set")
            && stderr.contains("Next: casthon call flipper <entry-point>"),
        "{stderr}"
    );
    assert!(
        stderr.contains("Signing and submitting installation"),
        "{stderr}"
    );
    assert!(
        stderr.contains("Checking execution status (attempt 1)"),
        "{stderr}"
    );
    let path = project.path().join("deployments/testnet/flipper.json");
    let manifest: Value = serde_json::from_slice(&fs::read(&path).unwrap()).unwrap();
    assert_eq!(manifest["schemaVersion"], 1);
    assert_eq!(manifest["networkProfile"], "testnet");
    assert_eq!(manifest["chainName"], "casper-test");
    assert_eq!(manifest["current"]["status"], "executed");
    assert_eq!(manifest["current"]["blockHeight"], 42);
    assert_eq!(manifest["current"]["gasConsumed"], "137");
    assert_eq!(manifest["current"]["paymentAmountCspr"], "23.5");
    assert_eq!(manifest["current"]["artifact"]["buildProfile"], "release");
    assert_eq!(
        manifest["current"]["abi"]["artifactSha256"],
        manifest["current"]["artifact"]["sha256"]
    );
    assert_eq!(
        manifest["current"]["abi"]["entryPoints"]["set"]["args"][0]["type"],
        "Bool"
    );
    assert_eq!(
        manifest["current"]["abi"]["entryPoints"]["set"]["access"],
        "public"
    );
    assert_eq!(manifest["current"]["callTarget"]["kind"], "package");
    assert_eq!(manifest["current"]["callTarget"]["hash"], "package-111");
    assert_eq!(
        manifest["current"]["addresses"]["packages"][0],
        "package-111"
    );
    assert_eq!(
        manifest["current"]["addresses"]["entities"][0],
        "addressable-entity-222"
    );
    assert_eq!(
        manifest["current"]["addresses"]["bytecodes"][0],
        "byte-code-333"
    );
    assert_eq!(manifest["history"], serde_json::json!([]));
    let calls = fs::read_to_string(&log).unwrap();
    assert!(calls.contains("--raw"), "{calls}");
    assert!(
        calls.contains("transaction get transaction-v1-hash-aaaa"),
        "{calls}"
    );

    let called = success(
        command(project.path())
            .arg("--casper-cli")
            .arg(&casper_cli)
            .args(["call", "flipper", "set", "--arg", "value=true", "-vv"])
            .output()
            .unwrap(),
    );
    let stdout = String::from_utf8_lossy(&called.stdout);
    let stderr = String::from_utf8_lossy(&called.stderr);
    assert!(stdout.contains("Execution succeeded"), "{stdout}");
    assert!(stderr.contains("Calling flipper::set"), "{stderr}");
    assert!(stderr.contains("package package-111"), "{stderr}");
    assert!(stderr.contains("Returns    Unit"), "{stderr}");
    let calls = fs::read_to_string(&log).unwrap();
    assert!(
        calls.contains("transaction call package-111 set --from wallet:account-0"),
        "{calls}"
    );
    assert!(calls.contains("--package"), "{calls}");
    assert!(calls.contains("--arg value:Bool=true"), "{calls}");
    assert!(calls.contains("--speculative"), "{calls}");
}

#[test]
fn configured_build_uses_pin_and_emits_clean_json() {
    let project = tempdir().unwrap();
    let tooling = fake_sdk();
    fs::create_dir(project.path().join("contracts")).unwrap();
    fs::write(
        project.path().join("contracts/token.py"),
        "def call(): pass\n",
    )
    .unwrap();
    fs::write(
        project.path().join("pyproject.toml"),
        "[tool.casthon]\nmicropython='1.29.0'\ntargets=['contracts/token.py']\n",
    )
    .unwrap();
    let output = success(
        command(project.path())
            .args([
                "--sdk-root",
                tooling.path().to_str().unwrap(),
                "build",
                "--json",
                "--minify",
                "--runtime",
                "native-errors",
                "--heap",
                "static",
            ])
            .output()
            .unwrap(),
    );
    let manifest: Value = serde_json::from_slice(&output.stdout).unwrap();
    assert_eq!(manifest["schemaVersion"], 1);
    assert_eq!(manifest["micropython"], "1.29.0");
    assert_eq!(manifest["buildProfile"], "debug");
    assert!(
        manifest["artifacts"][0]["wasm"]
            .as_str()
            .unwrap()
            .ends_with("build/native-errors/minified/token.wasm")
    );
    assert!(String::from_utf8_lossy(&output.stderr).contains("worker output"));
    assert!(String::from_utf8_lossy(&output.stderr).contains("worker diagnostic"));
    let log = Path::new(manifest["artifacts"][0]["log"].as_str().unwrap());
    let transcript = fs::read_to_string(log).unwrap();
    assert!(transcript.contains("worker output"));
    assert!(transcript.contains("worker diagnostic"));
    let args: Value =
        serde_json::from_slice(&fs::read(project.path().join("arguments.json")).unwrap()).unwrap();
    assert_eq!(args["micropython"], "1.29.0");
    assert_eq!(args["heap"], "static");
    assert_eq!(args["runtime"], "native-errors");
    assert_eq!(args["profile"], "debug");
    assert_eq!(args["casthon"], env!("CARGO_BIN_EXE_casthon"));
}

#[test]
fn release_flags_select_separate_artifacts_and_reject_conflicts() {
    let project = tempdir().unwrap();
    let tooling = fake_sdk();
    fs::write(project.path().join("token.py"), "def call(): pass\n").unwrap();
    for flags in [vec!["--release"], vec!["--profile", "release"]] {
        let output = success(
            command(project.path())
                .args([
                    "--sdk-root",
                    tooling.path().to_str().unwrap(),
                    "build",
                    "token.py",
                    "--json",
                    "--minify",
                ])
                .args(flags)
                .output()
                .unwrap(),
        );
        let manifest: Value = serde_json::from_slice(&output.stdout).unwrap();
        assert_eq!(manifest["buildProfile"], "release");
        assert!(
            manifest["artifacts"][0]["wasm"]
                .as_str()
                .unwrap()
                .ends_with("build/release/minified/token.wasm")
        );
        assert_eq!(
            manifest["artifacts"][0]["metadata"]["buildProfile"],
            "release"
        );
    }
    let output = command(project.path())
        .args(["build", "token.py", "--release", "--profile", "debug"])
        .output()
        .unwrap();
    assert!(!output.status.success());
    let output = command(project.path())
        .args(["build", "token.py", "--profile", "unknown"])
        .output()
        .unwrap();
    assert!(!output.status.success());
}

#[test]
fn build_steps_and_worker_failures_are_readable_without_a_terminal() {
    let project = tempdir().unwrap();
    let tooling = fake_sdk();
    fs::write(project.path().join("token.py"), "def call(): pass\n").unwrap();
    let worker = tooling.path().join("scripts/build.py");
    let original = fs::read_to_string(&worker).unwrap();
    let events = r#"
print(json.dumps({'casthon_build': 1, 'event': 'start', 'name': 'Compiling runtime'}), flush=True)
for i in range(40): print(f'compiler line {i}', file=sys.stderr, flush=True)
print('compiler error: example failure', file=sys.stderr, flush=True)
raise SystemExit(23)
"#;
    fs::write(&worker, format!("{original}\n{events}")).unwrap();
    for flags in [vec![], vec!["--json"], vec!["--no-progress"]] {
        let output = command(project.path())
            .args([
                "--sdk-root",
                tooling.path().to_str().unwrap(),
                "build",
                "token.py",
            ])
            .args(&flags)
            .output()
            .unwrap();
        assert_eq!(output.status.code(), Some(23));
        assert!(output.stdout.is_empty());
        let stderr = String::from_utf8_lossy(&output.stderr);
        assert!(stderr.contains("compiler line 0"));
        assert!(stderr.contains("compiler line 39"));
        assert!(stderr.contains("compiler error: example failure"));
        assert!(stderr.contains("Build log:"));
        assert!(!stderr.contains('\x1b'));
        assert!(!stderr.contains("casthon_build"));
        assert_eq!(stderr.contains("1. Compiling runtime..."), flags.is_empty());
        let transcript = fs::read_to_string(project.path().join("build/token-build.log")).unwrap();
        assert!(transcript.contains("compiler line 0"));
        assert!(transcript.contains("compiler line 39"));
        assert!(!transcript.contains("casthon_build"));
    }
}

#[test]
#[cfg(unix)]
fn interactive_build_keeps_a_log_pane_and_progress_rows() {
    let project = tempdir().unwrap();
    let tooling = fake_sdk();
    fs::write(project.path().join("token.py"), "def call(): pass\n").unwrap();
    let worker = tooling.path().join("scripts/build.py");
    let original = fs::read_to_string(&worker).unwrap();
    fs::write(
        &worker,
        format!(
            "{original}\n{}",
            r#"
import time
print(json.dumps({'casthon_build': 1, 'event': 'start', 'name': 'Compiling runtime'}), flush=True)
for i in range(40):
    print(f'compiler line {i}', file=sys.stderr, flush=True)
    time.sleep(0.004)
"#
        ),
    )
    .unwrap();
    let probe = r#"
import errno, fcntl, json, os, pty, select, struct, subprocess, sys, termios, time
master, slave = pty.openpty()
fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack('HHHH', 24, 80, 0, 0))
env = dict(os.environ, TERM='xterm-256color', NO_COLOR='1')
process = subprocess.Popen([sys.argv[1], '--project-root', sys.argv[2], '--python', sys.executable,
    '--sdk-root', sys.argv[3], 'build', 'token.py'], cwd=sys.argv[2],
    stdout=subprocess.PIPE, stderr=slave, env=env)
os.close(slave)
screen = bytearray()
deadline = time.monotonic() + 10
try:
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0 or not select.select([master], [], [], remaining)[0]:
            raise TimeoutError('Build display did not finish')
        try:
            data = os.read(master, 65536)
        except OSError as error:
            if error.errno == errno.EIO: break
            raise
        if not data: break
        screen.extend(data)
    stdout, _ = process.communicate(timeout=3)
    print(json.dumps({'code': process.returncode, 'stdout': stdout.decode(), 'screen': screen.decode()}))
finally:
    os.close(master)
    if process.poll() is None:
        process.kill()
        process.wait()
"#;
    let result = success(
        Command::new("python3")
            .args([
                "-c",
                probe,
                env!("CARGO_BIN_EXE_casthon"),
                project.path().to_str().unwrap(),
                tooling.path().to_str().unwrap(),
            ])
            .output()
            .unwrap(),
    );
    let result: Value = serde_json::from_slice(&result.stdout).unwrap();
    assert_eq!(result["code"], 0);
    assert!(result["stdout"].as_str().unwrap().starts_with("Built "));
    let screen = result["screen"].as_str().unwrap();
    assert!(screen.contains("Compiling runtime"), "{screen}");
    assert!(screen.contains("Checking build report"), "{screen}");
    assert!(screen.contains("compiler line 39"), "{screen}");
    assert!(
        screen.contains('\x1b'),
        "Expected terminal redraws: {screen}"
    );
    assert!(!screen.contains("casthon_build"));
    let transcript = fs::read_to_string(project.path().join("build/token-build.log")).unwrap();
    assert!(transcript.contains("compiler line 0"));
    assert!(transcript.contains("compiler line 39"));
}

#[test]
fn unsupported_pin_fails_before_building() {
    let project = tempdir().unwrap();
    fs::write(
        project.path().join("pyproject.toml"),
        "[tool.casthon]\nmicropython='0.0.0'\ntargets=['missing.py']\n",
    )
    .unwrap();
    let output = command(project.path()).arg("build").output().unwrap();
    assert!(!output.status.success());
    assert!(String::from_utf8_lossy(&output.stderr).contains("MicroPython 0.0.0 is unsupported"));
    assert!(!project.path().join("build").exists());
}

#[test]
fn explicit_pin_overrides_project_pin() {
    let project = tempdir().unwrap();
    let tooling = fake_sdk();
    fs::write(project.path().join("token.py"), "def call(): pass\n").unwrap();
    fs::write(
        project.path().join("pyproject.toml"),
        "[tool.casthon]\nmicropython='0.0.0'\n",
    )
    .unwrap();
    success(
        command(project.path())
            .args([
                "--sdk-root",
                tooling.path().to_str().unwrap(),
                "build",
                "token.py",
                "--micropython",
                "1.29.0",
                "--json",
            ])
            .output()
            .unwrap(),
    );
}

#[test]
fn build_without_manifest_accepts_a_file_with_spaces() {
    let project = tempdir().unwrap();
    let tooling = fake_sdk();
    fs::create_dir(project.path().join("contracts with spaces")).unwrap();
    fs::write(
        project.path().join("contracts with spaces/token.py"),
        "def call(): pass\n",
    )
    .unwrap();
    let output = success(
        command(project.path())
            .args([
                "--sdk-root",
                tooling.path().to_str().unwrap(),
                "build",
                "contracts with spaces/token.py",
                "--json",
            ])
            .output()
            .unwrap(),
    );
    let manifest: Value = serde_json::from_slice(&output.stdout).unwrap();
    assert_eq!(manifest["artifacts"].as_array().unwrap().len(), 1);
}

#[test]
fn repeated_target_names_fail_before_overwriting() {
    let project = tempdir().unwrap();
    for dir in ["a", "b"] {
        fs::create_dir(project.path().join(dir)).unwrap();
        fs::write(project.path().join(dir).join("token.py"), "").unwrap();
    }
    let output = command(project.path())
        .args(["build", "a/token.py", "b/token.py"])
        .output()
        .unwrap();
    assert!(!output.status.success());
    assert!(String::from_utf8_lossy(&output.stderr).contains("distinct filenames"));
}

#[test]
fn unknown_configuration_is_an_actionable_error() {
    let project = tempdir().unwrap();
    fs::write(
        project.path().join("pyproject.toml"),
        "[tool.casthon]\nmicropythno='1.29.0'\n",
    )
    .unwrap();
    let output = command(project.path()).arg("build").output().unwrap();
    assert!(!output.status.success());
    assert!(String::from_utf8_lossy(&output.stderr).contains("unknown field `micropythno`"));
}

#[test]
fn inspect_uses_the_embedded_wasm_engine() {
    let project = tempdir().unwrap();
    fs::write(project.path().join("empty.wasm"), b"\0asm\x01\0\0\0").unwrap();
    let output = success(
        command(project.path())
            .args(["inspect", "empty.wasm", "--json"])
            .output()
            .unwrap(),
    );
    let report: Value = serde_json::from_slice(&output.stdout).unwrap();
    assert_eq!(report["bytes"], 8);
    assert_eq!(report["casperV1Compatible"], true);
    assert_eq!(report["exports"], serde_json::json!([]));
}

#[test]
fn lowering_hides_initializer_but_preserves_constructor_calls() {
    let project = tempdir().unwrap();
    // ctor() -> 42; call() -> ctor(); _initialize() drops ctor's result.
    // Removing an export must preserve both the constructor and its callers.
    let code = b"\x0a\x11\x03\x04\x00\x41\x2a\x0b\x04\x00\x10\x00\x0b\x05\x00\x10\x00\x1a\x0b";
    let mut input = b"\0asm\x01\0\0\0\x01\x08\x02\x60\x00\x01\x7f\x60\x00\x00\x03\x04\x03\x00\x00\x01\x07\x16\x02\x04call\x00\x01\x0b_initialize\x00\x02".to_vec();
    input.extend_from_slice(code);
    assert_eq!(
        wasm_softfloat::inspect(&input).unwrap().exports,
        ["call", "_initialize"]
    );
    fs::write(project.path().join("input.wasm"), input).unwrap();
    success(
        command(project.path())
            .args(["__wasm", "input.wasm", "output.wasm"])
            .output()
            .unwrap(),
    );
    let output = fs::read(project.path().join("output.wasm")).unwrap();
    assert_eq!(wasm_softfloat::inspect(&output).unwrap().exports, ["call"]);
    assert!(output.ends_with(code), "Constructor code and calls changed");
}

#[test]
fn new_creates_templates_and_refuses_existing_directories() {
    let project = tempdir().unwrap();
    for template in ["flipper", "counter", "cep18"] {
        success(
            command(project.path())
                .args(["new", template, "--template", template])
                .output()
                .unwrap(),
        );
        assert!(
            project
                .path()
                .join(template)
                .join("pyproject.toml")
                .is_file()
        );
        let manifest: toml::Value = toml::from_str(
            &fs::read_to_string(project.path().join(template).join("pyproject.toml")).unwrap(),
        )
        .unwrap();
        let recipe: Value =
            serde_json::from_slice(&fs::read(sdk().join("native/toolchain.json")).unwrap())
                .unwrap();
        assert_eq!(
            manifest["tool"]["casthon"]["micropython"].as_str().unwrap(),
            recipe["micropython"]["version"].as_str().unwrap()
        );
        assert_eq!(
            manifest["project"]["dependencies"][0].as_str().unwrap(),
            "casthon-sdk==0.1.0a1"
        );
        let test = if template == "flipper" {
            "tests/test_flipper.py"
        } else {
            "tests/test_contract.py"
        };
        let test_source = fs::read_to_string(project.path().join(template).join(test)).unwrap();
        assert!(test_source.contains("from casthon.testing import"));
        assert!(test_source.contains("MockHost"));
        let readme = fs::read_to_string(project.path().join(template).join("README.md")).unwrap();
        assert!(readme.contains("uv sync"));
        assert!(!readme.contains(sdk().to_string_lossy().as_ref()));
        if template == "flipper" {
            assert_eq!(
                fs::read(project.path().join(template).join("contracts/flipper.py")).unwrap(),
                fs::read(sdk().join("templates/flipper/contracts/flipper.py")).unwrap()
            );
            assert!(
                fs::read_to_string(
                    project
                        .path()
                        .join(template)
                        .join("tests/live/test_flipper.py")
                )
                .unwrap()
                .contains("LiveNetworkTest")
            );
            assert_eq!(
                manifest["tool"]["casthon"]["targets"][0].as_str().unwrap(),
                "contracts/flipper.py"
            );
        }
        let output = command(project.path())
            .args(["new", template])
            .output()
            .unwrap();
        assert!(!output.status.success());
    }
    assert!(
        project
            .path()
            .join("cep18/reference/cep18/LICENSE")
            .is_file()
    );

    success(
        command(project.path())
            .args(["new", "default-flipper"])
            .output()
            .unwrap(),
    );
    assert!(
        project
            .path()
            .join("default-flipper/contracts/flipper.py")
            .is_file()
    );
}
