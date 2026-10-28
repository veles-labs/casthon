use super::{Project, deployment};
use anyhow::Result;
use console::{strip_ansi_codes, style};
use serde::Deserialize;
use std::{env, fs, path::Path, process::Command};

const PYTHON_CHECK: &str = r#"
import json, sys
supported = sys.version_info >= (3, 11)
modules = []
has_pip = False
if supported:
    import contextlib, importlib, importlib.metadata, importlib.util, io
    has_pip = importlib.util.find_spec('pip') is not None
    for name in ('pytest', 'mypy', 'wasmtime'):
        try:
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                importlib.import_module(name)
            try:
                detail = importlib.metadata.version(name)
            except importlib.metadata.PackageNotFoundError:
                detail = 'available'
            modules.append({'name': name, 'ok': True, 'detail': detail})
        except (Exception, SystemExit) as error:
            modules.append({'name': name, 'ok': False, 'detail': '{}: {}'.format(type(error).__name__, error)})
print(json.dumps({'version': '.'.join(map(str, sys.version_info[:3])),
    'supported': supported, 'is_venv': sys.prefix != getattr(sys, 'base_prefix', sys.prefix),
    'has_pip': has_pip, 'modules': modules}))
"#;

const EMSCRIPTEN_CHECK: &str = r#"
import os, pathlib, subprocess, sys, tempfile
sys.path.insert(0, str(pathlib.Path(sys.argv[1]) / 'scripts'))
from build_cache import emscripten_configuration
try:
    with tempfile.TemporaryDirectory(prefix='casthon-doctor-') as temporary:
        root, _, text = emscripten_configuration(pathlib.Path(temporary) / 'cache')
        driver = root / 'emcc.py'
        command = [sys.executable, str(driver), '--version'] if driver.is_file() else ['emcc', '--version']
        config = pathlib.Path(temporary) / 'emscripten-config.py'
        config.write_text(text)
        environment = dict(os.environ, EM_CONFIG=str(config), EMSDK_PYTHON=sys.executable)
        result = subprocess.run(command, env=environment)
        sys.exit(result.returncode)
except OSError as error:
    print(error, file=sys.stderr)
    sys.exit(1)
"#;

#[derive(Deserialize)]
struct PythonInfo {
    version: String,
    supported: bool,
    is_venv: bool,
    has_pip: bool,
    modules: Vec<Module>,
}

#[derive(Deserialize)]
struct Module {
    name: String,
    ok: bool,
    detail: String,
}

fn summary(bytes: &[u8]) -> String {
    let text = String::from_utf8_lossy(bytes);
    let text = strip_ansi_codes(&text);
    let mut lines = text.lines().filter(|line| !line.trim().is_empty());
    let first = lines.next().unwrap_or("no diagnostic output");
    let line = if first.starts_with("Traceback") {
        lines.next_back().unwrap_or(first)
    } else {
        first
    };
    line.chars()
        .filter(|ch| !ch.is_control())
        .take(120)
        .collect()
}

fn row(ok: bool, optional: bool, name: &str, detail: &str) {
    let icon = if ok {
        "✅"
    } else if optional {
        "⚠️"
    } else {
        "❌"
    };
    println!("  {icon} {name:<24} {}", summary(detail.as_bytes()));
}

fn hint(text: &str) {
    println!("       {}", style(text).dim());
}

fn shell(path: &Path) -> String {
    let text = path.to_string_lossy();
    if !text.is_empty()
        && text
            .chars()
            .all(|ch| ch.is_ascii_alphanumeric() || "/._-".contains(ch))
    {
        text.into_owned()
    } else {
        format!("'{}'", text.replace('\'', "'\\''"))
    }
}

fn executable(name: &str) -> bool {
    env::split_paths(&env::var_os("PATH").unwrap_or_default())
        .any(|directory| directory.join(name).is_file())
}

fn install(tool: &str) {
    let os = if cfg!(target_os = "macos") {
        "macos".to_owned()
    } else {
        fs::read_to_string("/etc/os-release").unwrap_or_default()
    };
    let package = match tool {
        "python" if os == "macos" => "python",
        "python" => "python3",
        "emcc" => "emscripten",
        "wasm-opt" => "binaryen",
        "node" if os == "macos" || os.contains("arch") => "node",
        "node" => "nodejs",
        "make" => "make",
        "cc" if os.contains("debian") || os.contains("ubuntu") => "build-essential",
        "cc" if os.contains("arch") => "base-devel",
        "cc" => "gcc",
        _ => unreachable!(),
    };
    if os == "macos" && matches!(tool, "cc" | "make") {
        hint("Install: xcode-select --install");
    } else if os == "macos" {
        hint(&format!("Install: brew install {package}"));
        if !executable("brew") {
            hint("Install Homebrew first: https://brew.sh");
        }
    } else if os.contains("debian") || os.contains("ubuntu") {
        hint(&format!(
            "Install: sudo apt-get update && sudo apt-get install {package}"
        ));
    } else if os.contains("fedora") || os.contains("rhel") {
        hint(&format!("Install: sudo dnf install {package}"));
    } else if os.contains("arch") {
        hint(&format!("Install: sudo pacman -S {package}"));
    }
    let instructions = match tool {
        "python" => "Python 3.11+ setup: https://docs.astral.sh/uv/guides/install-python/",
        "emcc" => {
            "Emsdk setup and shell activation: https://emscripten.org/docs/getting_started/downloads.html"
        }
        "wasm-opt" => {
            "Binaryen releases: https://github.com/WebAssembly/binaryen/releases (add bin/ to PATH)"
        }
        "node" => "Node.js installer: https://nodejs.org/en/download",
        "make" => "GNU Make setup: https://www.gnu.org/software/make/",
        "cc" => "C compiler setup: https://clang.llvm.org/get_started.html",
        _ => unreachable!(),
    };
    hint(instructions);
    hint("If already installed, add its executable directory to PATH.");
}

fn check_tool(name: &str, command: &mut Command, optional: bool) -> bool {
    match command.output() {
        Ok(output) if output.status.success() => {
            let version = if output.stdout.is_empty() {
                &output.stderr
            } else {
                &output.stdout
            };
            let summary = summary(version);
            let detail = if optional {
                "available"
            } else if name == "Emscripten (emcc)" {
                summary
                    .split_whitespace()
                    .find(|part| {
                        part.starts_with(|ch: char| ch.is_ascii_digit()) && part.contains('.')
                    })
                    .unwrap_or(&summary)
            } else {
                &summary
            };
            row(true, optional, name, detail);
            true
        }
        Ok(output) => {
            let diagnostic = if output.stderr.is_empty() {
                &output.stdout
            } else {
                &output.stderr
            };
            row(false, optional, name, &summary(diagnostic));
            false
        }
        Err(error) => {
            let detail = if error.kind() == std::io::ErrorKind::NotFound {
                "not found on PATH".to_owned()
            } else {
                error.to_string()
            };
            row(false, optional, name, &detail);
            false
        }
    }
}

fn install_python_tools(project: &Project, python: &PythonInfo, missing: &[&str]) {
    let interpreter = shell(&project.python);
    let use_uv = executable("uv");
    let interpreter = if python.is_venv {
        if !use_uv && !python.has_pip {
            hint(&format!("{interpreter} -m ensurepip --upgrade"));
        }
        interpreter
    } else {
        let environment = project.root.join(".venv");
        if use_uv {
            hint(&format!(
                "uv venv --python {interpreter} {}",
                shell(&environment)
            ));
        } else {
            hint(&format!("{interpreter} -m venv {}", shell(&environment)));
        }
        shell(&environment.join("bin/python"))
    };
    let packages = missing.join(" ");
    if use_uv {
        hint(&format!("uv pip install --python {interpreter} {packages}"));
    } else {
        hint(&format!("{interpreter} -m pip install {packages}"));
    }
}

pub fn run(project: &Project, casper_cli: &Path) -> Result<i32> {
    println!(
        "{}",
        style(format!(
            "Casthon {} — environment check",
            env!("CARGO_PKG_VERSION")
        ))
        .bold()
    );
    println!(
        "  Project: {}\n  SDK:     {}\n  Python:  {}",
        project.root.display(),
        project.sdk.display(),
        project.python.display()
    );
    println!("\n{}", style("Build dependencies").bold());
    let mut healthy = true;
    match project.pin(None) {
        Ok(pin) => row(
            true,
            false,
            "MicroPython runtime",
            &format!("{pin} (pinned)"),
        ),
        Err(error) => {
            healthy = false;
            row(false, false, "MicroPython runtime", &format!("{error:#}"));
            hint(&format!(
                "Set [tool.casthon].micropython = \"{}\" in {}",
                project.supported,
                project.root.join("pyproject.toml").display()
            ));
        }
    }
    let probe = project
        .command()?
        .args(["-c", PYTHON_CHECK, "casthon-python-info"])
        .output();
    let python: std::result::Result<PythonInfo, String> = match probe {
        Ok(output) if output.status.success() => serde_json::from_slice(&output.stdout)
            .map_err(|error| format!("Invalid Python check output: {error}")),
        Ok(output) => Err(summary(&output.stderr)),
        Err(error) => Err(error.to_string()),
    };
    let python_ready = python.as_ref().is_ok_and(|python| python.supported);
    match &python {
        Ok(info) if info.supported => row(true, false, "Python", &info.version),
        Ok(info) => row(
            false,
            false,
            "Python",
            &format!("{}; Python 3.11+ is required", info.version),
        ),
        Err(error) => row(false, false, "Python", error),
    }
    if !python_ready {
        healthy = false;
        install("python");
        hint(
            "Choose it with casthon --python /path/to/python3 doctor, or create the project's .venv.",
        );
    }
    for (name, binary) in [
        ("Emscripten (emcc)", "emcc"),
        ("Binaryen (wasm-opt)", "wasm-opt"),
        ("Node.js", "node"),
        ("Make", "make"),
        ("C compiler", "cc"),
    ] {
        let mut command = if binary == "emcc" && python_ready {
            let mut command = project.command()?;
            command.args(["-c", EMSCRIPTEN_CHECK]).arg(&project.sdk);
            command
        } else {
            let mut command = Command::new(binary);
            command.arg("--version");
            command
        };
        if !check_tool(name, &mut command, false) {
            healthy = false;
            install(binary);
        }
    }
    row(true, false, "Wasm processing", "built into casthon");
    println!("\n{}", style("Optional test tools").bold());
    let mut optional_ready = true;
    if let Ok(info) = &python
        && info.supported
    {
        let missing: Vec<_> = info
            .modules
            .iter()
            .filter(|module| !module.ok)
            .map(|module| module.name.as_str())
            .collect();
        for module in &info.modules {
            row(module.ok, true, &module.name, &module.detail);
        }
        if !missing.is_empty() {
            optional_ready = false;
            hint("Install the missing Python tools:");
            install_python_tools(project, info, &missing);
        }
    } else {
        optional_ready = false;
        row(
            false,
            true,
            "Python test tools",
            "not checked; fix Python above first",
        );
    }
    let devnet = env::var("CSPR_DEVNET_BIN").unwrap_or_else(|_| "casper-devnet".to_owned());
    if !check_tool(
        "casper-devnet (live)",
        Command::new(&devnet).arg("--help"),
        true,
    ) {
        optional_ready = false;
        hint("Install: cargo install casper-devnet --locked");
        hint("Then download node assets: casper-devnet assets pull");
        hint("Setup: https://github.com/veles-labs/casper-devnet#quick-start");
    }
    println!("\n{}", style("Deployment tools").bold());
    let deployment_ready = match deployment::probe(casper_cli) {
        Ok(version) => {
            row(true, true, "Veles casper-cli", &version);
            true
        }
        Err(error) => {
            row(false, true, "Veles casper-cli", &format!("{error:#}"));
            hint(
                "Install: cargo install --git https://github.com/veles-labs/casper-cli casper-cli --locked",
            );
            hint("Setup: https://github.com/veles-labs/casper-cli");
            false
        }
    };
    println!();
    if healthy {
        println!("✅ Build environment is ready.");
        if !optional_ready {
            println!("⚠️  Optional test tools need attention.");
        }
        if !deployment_ready {
            println!("⚠️  Deployment tooling needs attention.");
        }
    } else {
        println!("❌ Fix the build dependencies above, then run casthon doctor again.");
    }
    Ok(if healthy { 0 } else { 1 })
}
