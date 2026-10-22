use serde_json::Value;
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
(out/(name+'-build-report.json')).write_text(json.dumps({'sha256':hashlib.sha256(data).hexdigest(),'micropython':a.micropython,'buildProfile':a.profile}))
print('worker output belongs on stderr in JSON mode')
print('worker diagnostic on stderr', file=sys.stderr)
"#).unwrap();
    root
}

#[test]
fn test_delegates_arguments_working_directory_and_exit_code() {
    let project = tempdir().unwrap();
    fs::write(project.path().join("pytest.py"), "import json,os,sys\nprint(json.dumps({'args':sys.argv[1:],'cwd':os.getcwd()}))\nraise SystemExit(7)\n").unwrap();
    let output = command(project.path())
        .args([
            "test",
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
    for template in ["counter", "cep18"] {
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
        assert!(
            project
                .path()
                .join(template)
                .join("tests/test_contract.py")
                .is_file()
        );
        assert!(
            fs::read_to_string(project.path().join(template).join("tests/test_contract.py"))
                .unwrap()
                .contains("from casthon.testing import MockHost, use_host")
        );
        let readme = fs::read_to_string(project.path().join(template).join("README.md")).unwrap();
        assert!(readme.contains("uv sync"));
        assert!(!readme.contains(sdk().to_string_lossy().as_ref()));
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
}
