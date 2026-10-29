#![cfg(unix)]

use serde_json::json;
use std::{
    fs,
    os::unix::fs::PermissionsExt,
    path::{Path, PathBuf},
    process::Command,
};
use tempfile::{TempDir, tempdir};

fn script(path: &Path, body: &str) {
    fs::write(path, format!("#!/bin/sh\n{body}\n")).unwrap();
    fs::set_permissions(path, fs::Permissions::from_mode(0o755)).unwrap();
}

struct DoctorFixture {
    project: TempDir,
    binaries: TempDir,
    python: PathBuf,
}

impl DoctorFixture {
    fn new() -> Self {
        let project = tempdir().unwrap();
        let binaries = tempdir().unwrap();
        let python = binaries.path().join("python chosen");
        let fixture = Self {
            project,
            binaries,
            python,
        };
        fixture.python_report(true, true, true);
        for tool in ["emcc", "wasm-opt", "node", "make", "cc", "casper-devnet"] {
            script(
                &fixture.binaries.path().join(tool),
                "printf 'test version 1.0\\n'",
            );
        }
        script(
            &fixture.binaries.path().join("casper-cli"),
            "if [ \"$1\" = --version ]; then printf 'casper-cli 0.4.0\\n'; exit 0; fi\nif [ \"$1 $2 $3\" = 'transaction put --help' ]; then printf '%s\\n' 'Build a session transaction from Wasm' '--install-upgrade --simulate --speculative --raw' 'Simulate execution locally using state queries to the network RPC'; exit 0; fi\nif [ \"$1 $2 $3\" = 'transaction call --help' ]; then printf '%s\\n' 'Call a stored contract by hash' '--package --simulate --speculative --raw'; exit 0; fi\nexit 2",
        );
        fixture
    }

    fn python_report(&self, supported: bool, is_venv: bool, modules_available: bool) {
        let modules: Vec<_> = ["pytest", "mypy", "wasmtime"].into_iter().map(|name|
            json!({"name":name, "ok":modules_available, "detail":if modules_available {"1.0"} else {"not installed"}})
        ).collect();
        let payload = json!({"version":if supported {"3.14.2"} else {"3.10.0"},
            "supported":supported, "is_venv":is_venv, "has_pip":false, "modules":modules})
        .to_string();
        let real_python = Command::new("python3")
            .args(["-c", "import sys; print(sys.executable)"])
            .output()
            .unwrap();
        assert!(real_python.status.success());
        let real_python = String::from_utf8(real_python.stdout).unwrap();
        script(
            &self.python,
            &format!(
                "if [ \"$3\" = casthon-python-info ]; then\nprintf '%s\\n' '{}'\nelse\nexec '{}' \"$@\"\nfi",
                payload.replace('\'', "'\\''"),
                real_python.trim().replace('\'', "'\\''")
            ),
        );
    }

    fn command(&self) -> Command {
        let mut command = Command::new(env!("CARGO_BIN_EXE_casthon"));
        command
            .current_dir(self.project.path())
            .arg("--project-root")
            .arg(self.project.path())
            .arg("--python")
            .arg(&self.python)
            .arg("doctor")
            .env("PATH", self.binaries.path())
            .env("NO_COLOR", "1")
            .env("CSPR_DEVNET_BIN", "casper-devnet");
        command
    }
}

#[test]
fn healthy_doctor_is_grouped_and_shows_status_and_versions() {
    let fixture = DoctorFixture::new();
    let output = fixture.command().output().unwrap();
    let text = String::from_utf8_lossy(&output.stdout);
    assert!(output.status.success(), "{text}");
    assert!(output.stderr.is_empty());
    for expected in [
        "Build dependencies",
        "Optional test tools",
        "✅ Python",
        "3.14.2",
        "1.29.0 (pinned)",
        "✅ Emscripten",
        "✅ Binaryen",
        "✅ casper-devnet",
        "✅ Veles casper-cli",
        "casper-cli 0.4.0",
        "✅ Build environment is ready.",
    ] {
        assert!(text.contains(expected), "Missing {expected}: {text}");
    }
    assert!(!text.contains("❌"));
    assert!(!text.contains("Install:"));
    assert!(!text.contains('\x1b'));
}

#[test]
fn wrong_casper_cli_is_reported_with_registry_installation_help() {
    let fixture = DoctorFixture::new();
    script(
        &fixture.binaries.path().join("casper-cli"),
        "if [ \"$1\" = --version ]; then printf 'casper-cli 99.0.0\\n'; exit 0; fi\nprintf 'some unrelated interface\\n'",
    );
    let output = fixture.command().output().unwrap();
    let text = String::from_utf8_lossy(&output.stdout);
    assert!(output.status.success(), "{text}");
    assert!(text.contains("⚠️ Veles casper-cli"), "{text}");
    assert!(text.contains("incompatible casper-cli"), "{text}");
    assert!(
        text.contains("Install from crates.io: cargo install casper-cli --locked"),
        "{text}"
    );
    assert!(text.contains("github.com/veles-labs/casper-cli"), "{text}");
    assert!(
        text.contains("Deployment tooling needs attention"),
        "{text}"
    );
}

#[test]
fn missing_and_broken_compilers_have_repair_instructions_and_fail() {
    for broken in [false, true] {
        let fixture = DoctorFixture::new();
        let emcc = fixture.binaries.path().join("emcc");
        if broken {
            script(&emcc, "printf 'compiler is broken\\n' >&2\nexit 7");
        } else {
            fs::remove_file(&emcc).unwrap();
        }
        let output = fixture.command().output().unwrap();
        assert_eq!(output.status.code(), Some(1));
        let text = String::from_utf8_lossy(&output.stdout);
        assert!(text.contains("❌ Emscripten"));
        assert!(text.contains(if broken {
            "compiler is broken"
        } else {
            "not found on PATH"
        }));
        assert!(text.contains("emscripten.org/docs/getting_started/downloads.html"));
        assert!(text.contains("Fix the build dependencies above"));
        assert!(!text.contains("Build environment is ready"));
    }
}

#[test]
fn missing_optional_tools_keep_builds_ready_and_target_the_selected_environment() {
    for is_venv in [false, true] {
        let fixture = DoctorFixture::new();
        fixture.python_report(true, is_venv, false);
        fs::remove_file(fixture.binaries.path().join("casper-devnet")).unwrap();
        let output = fixture.command().output().unwrap();
        let text = String::from_utf8_lossy(&output.stdout);
        assert!(output.status.success(), "{text}");
        assert!(text.contains("⚠️ pytest"));
        assert!(text.contains("pip install pytest mypy wasmtime"));
        assert!(text.contains("cargo install casper-devnet --locked"));
        assert!(text.contains("casper-devnet assets pull"));
        assert!(text.contains("Optional test tools need attention"));
        assert!(!text.contains("❌"));
        if is_venv {
            assert!(text.contains(&format!("'{}' -m ensurepip", fixture.python.display())));
        } else {
            assert!(text.contains(" -m venv "));
            assert!(text.contains(".venv/bin/python -m pip install"));
        }
    }
}

#[test]
fn invalid_runtime_pin_explains_how_to_fix_the_manifest() {
    let fixture = DoctorFixture::new();
    fs::write(
        fixture.project.path().join("pyproject.toml"),
        "[tool.casthon]\nmicropython='0.0.0'\n",
    )
    .unwrap();
    let output = fixture.command().output().unwrap();
    assert_eq!(output.status.code(), Some(1));
    let text = String::from_utf8_lossy(&output.stdout);
    assert!(text.contains("❌ MicroPython runtime"));
    assert!(text.contains("Set [tool.casthon].micropython = \"1.29.0\""));
    assert!(text.contains("pyproject.toml"));
}

#[test]
fn unsupported_or_missing_python_is_actionable_and_does_not_abort_other_checks() {
    for missing in [false, true] {
        let fixture = DoctorFixture::new();
        if missing {
            fs::remove_file(&fixture.python).unwrap();
        } else {
            fixture.python_report(false, false, false);
        }
        let output = fixture.command().output().unwrap();
        assert_eq!(output.status.code(), Some(1));
        let text = String::from_utf8_lossy(&output.stdout);
        assert!(text.contains("❌ Python"));
        assert!(text.contains("Choose it with casthon --python"));
        assert!(text.contains("✅ Emscripten"));
        assert!(text.contains("not checked; fix Python above first"));
    }
}
