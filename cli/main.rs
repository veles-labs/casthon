use anyhow::{Context, Result, ensure};
use clap::{Args, Parser, Subcommand};
use serde::Deserialize;
use serde_json::{Value, json};
use sha2::{Digest, Sha256};
use std::{
    collections::HashSet,
    env,
    ffi::OsString,
    fs,
    path::{Path, PathBuf},
    process::Command,
};

mod deployment;
mod doctor;
mod output;
mod progress;
mod templates;
mod testing;

#[derive(Parser)]
#[command(
    name = "casthon",
    version,
    about = "Build Python smart contracts for Casper"
)]
struct Cli {
    /// Project directory; otherwise find the nearest pyproject.toml.
    #[arg(long, global = true)]
    project_root: Option<PathBuf>,
    /// Python interpreter; otherwise use the active or project virtualenv.
    #[arg(long, global = true)]
    python: Option<PathBuf>,
    /// SDK/tooling checkout (the proof of concept keeps Python sources here).
    #[arg(long, global = true, default_value = env!("CARGO_MANIFEST_DIR"))]
    sdk_root: PathBuf,
    /// Veles Labs Casper CLI used for network deployment.
    #[arg(long, global = true, default_value = "casper-cli")]
    casper_cli: PathBuf,
    #[command(subcommand)]
    command: Action,
}

#[derive(Subcommand)]
enum Action {
    /// Compile source using the existing MicroPython/Casper pipeline.
    Build(Build),
    /// Run pytest; pass Python runner arguments after --.
    Test(testing::Test),
    /// Run python -m mypy with the project's configuration.
    #[command(disable_help_flag = true)]
    Check(Forward),
    /// Show Wasm exports, imports, memory and Casper compatibility.
    Inspect {
        wasm: PathBuf,
        #[arg(long)]
        json: bool,
    },
    /// Check the configured runtime and installed build tools.
    Doctor,
    /// Build, speculatively execute and optionally submit release Wasm through casper-cli.
    Deploy(deployment::Deploy),
    /// Call a deployed contract using its recorded address and typed ABI.
    Call(deployment::Call),
    /// Create a project from a bundled starter template.
    New {
        directory: PathBuf,
        #[arg(long, default_value = "flipper", value_parser = ["flipper", "counter", "cep18"])]
        template: String,
    },
    #[command(name = "__wasm", hide = true, disable_help_flag = true)]
    Wasm(Forward),
}

#[derive(Args)]
struct Forward {
    #[arg(trailing_var_arg = true, allow_hyphen_values = true)]
    args: Vec<OsString>,
}

#[derive(Args)]
struct Build {
    /// Source files or contracts/<name>.py aliases; defaults to configured targets.
    targets: Vec<PathBuf>,
    #[arg(long)]
    micropython: Option<String>,
    #[arg(long, default_value = "asyncify", value_parser = ["asyncify", "native-errors"])]
    runtime: String,
    /// Debug enables print()/dispatcher diagnostics; release removes casper_print.
    #[arg(long, default_value = "debug", value_parser = ["debug", "release"])]
    profile: String,
    /// Alias for --profile release.
    #[arg(long, conflicts_with = "profile")]
    release: bool,
    #[arg(long, value_parser = ["emmalloc-gc0", "emmalloc-gc1", "static", "split"])]
    heap: Option<String>,
    #[arg(long)]
    minify: bool,
    #[arg(long)]
    output_dir: Option<PathBuf>,
    /// Emit one artifact manifest on stdout; build logs go to stderr.
    #[arg(long)]
    json: bool,
    /// Stream full compiler output without the interactive progress display.
    #[arg(long)]
    no_progress: bool,
}

#[derive(Default, Deserialize)]
struct Document {
    #[serde(default)]
    tool: Tools,
}

#[derive(Default, Deserialize)]
struct Tools {
    #[serde(default)]
    casthon: Configuration,
}

#[derive(Default, Deserialize)]
#[serde(deny_unknown_fields)]
struct Configuration {
    micropython: Option<String>,
    #[serde(default)]
    targets: Vec<PathBuf>,
    python: Option<PathBuf>,
}

struct Project {
    cwd: PathBuf,
    root: PathBuf,
    sdk: PathBuf,
    python: PathBuf,
    config: Configuration,
    supported: String,
}

fn absolute(base: &Path, path: &Path) -> PathBuf {
    if path.is_absolute() {
        path.to_owned()
    } else {
        base.join(path)
    }
}

fn find_root(cwd: &Path) -> PathBuf {
    cwd.ancestors()
        .find(|path| path.join("pyproject.toml").is_file())
        .unwrap_or(cwd)
        .to_owned()
}

impl Project {
    fn load(cli: &Cli) -> Result<Self> {
        let cwd = env::current_dir()?;
        let root = cli
            .project_root
            .as_ref()
            .map(|path| absolute(&cwd, path))
            .unwrap_or_else(|| find_root(&cwd))
            .canonicalize()
            .context("Project directory does not exist")?;
        let sdk = absolute(&cwd, &cli.sdk_root)
            .canonicalize()
            .context("SDK checkout does not exist")?;
        let manifest = root.join("pyproject.toml");
        let config = if manifest.exists() {
            toml::from_str::<Document>(&fs::read_to_string(&manifest)?)
                .with_context(|| format!("Invalid configuration in {}", manifest.display()))?
                .tool
                .casthon
        } else {
            Configuration::default()
        };
        let recipe: Value = serde_json::from_slice(
            &fs::read(sdk.join("native/toolchain.json"))
                .context("SDK checkout needs native/toolchain.json; use --sdk-root")?,
        )?;
        let supported = recipe["micropython"]["version"]
            .as_str()
            .context("Runtime recipe has no MicroPython version")?
            .to_owned();
        let python = if let Some(path) = &cli.python {
            if path.components().count() > 1 {
                absolute(&cwd, path)
            } else {
                path.clone()
            }
        } else if let Some(path) = &config.python {
            if path.components().count() > 1 {
                absolute(&root, path)
            } else {
                path.clone()
            }
        } else if let Some(venv) = env::var_os("VIRTUAL_ENV")
            .map(PathBuf::from)
            .filter(|p| p.join("bin/python").is_file())
        {
            venv.join("bin/python")
        } else if root.join(".venv/bin/python").is_file() {
            root.join(".venv/bin/python")
        } else {
            PathBuf::from("python3")
        };
        Ok(Self {
            cwd,
            root,
            sdk,
            python,
            config,
            supported,
        })
    }

    fn pin(&self, override_pin: Option<&str>) -> Result<String> {
        let pin = override_pin
            .or(self.config.micropython.as_deref())
            .unwrap_or(&self.supported);
        ensure!(
            pin == self.supported,
            "MicroPython {pin} is unsupported by this runtime recipe (supports {}). Select that version in [tool.casthon].micropython or --micropython",
            self.supported
        );
        Ok(pin.to_owned())
    }

    fn command(&self) -> Result<Command> {
        let mut command = Command::new(&self.python);
        command.current_dir(&self.root);
        // This checkout remains the SDK source until Python packaging is split.
        let mut paths = vec![self.sdk.join("src")];
        paths.extend(env::split_paths(
            &env::var_os("PYTHONPATH").unwrap_or_default(),
        ));
        command.env("PYTHONPATH", env::join_paths(paths)?);
        Ok(command)
    }

    fn forward(&self, module: &str, args: &[OsString]) -> Result<i32> {
        Ok(self
            .command()?
            .arg("-m")
            .arg(module)
            .args(args)
            .status()
            .with_context(|| format!("Could not run {} -m {module}", self.python.display()))?
            .code()
            .unwrap_or(1))
    }
}

fn hash(bytes: &[u8]) -> String {
    Sha256::digest(bytes)
        .iter()
        .map(|byte| format!("{byte:02x}"))
        .collect()
}

fn build(project: &Project, options: Build) -> Result<i32> {
    build_with_output(project, options, true, false)
}

fn build_with_output(
    project: &Project,
    options: Build,
    announce: bool,
    quiet: bool,
) -> Result<i32> {
    let pin = project.pin(options.micropython.as_deref())?;
    let profile = if options.release {
        "release"
    } else {
        &options.profile
    };
    let configured = options.targets.is_empty();
    let targets = if configured {
        project.config.targets.clone()
    } else {
        options.targets
    };
    ensure!(
        !targets.is_empty(),
        "Specify a Python file, or set [tool.casthon].targets in pyproject.toml"
    );
    let mut names = HashSet::new();
    let mut sources = vec![];
    for target in targets {
        let source = if target.extension().is_none() && target.components().count() == 1 {
            project
                .root
                .join("contracts")
                .join(&target)
                .with_extension("py")
        } else {
            let base = if configured {
                &project.root
            } else {
                &project.cwd
            };
            absolute(base, &target)
        }
        .canonicalize()
        .with_context(|| format!("Contract source {} does not exist", target.display()))?;
        ensure!(
            source.is_file() && source.extension().is_some_and(|ext| ext == "py"),
            "Expected a Python source: {}",
            source.display()
        );
        let name = source
            .file_stem()
            .context("Source has no filename")?
            .to_os_string();
        ensure!(
            names.insert(name),
            "Targets must have distinct filenames to avoid overwriting artifacts"
        );
        sources.push(source);
    }
    let output = absolute(
        &project.root,
        &options.output_dir.unwrap_or_else(|| "build".into()),
    );
    let mut folder = output.clone();
    if options.runtime == "native-errors" {
        folder.push("native-errors");
    }
    if profile == "release" {
        folder.push("release");
    }
    if options.minify {
        folder.push("minified");
    }
    let worker = project.sdk.join("scripts/build.py");
    ensure!(worker.is_file(), "SDK checkout needs scripts/build.py");
    let mut artifacts = vec![];
    for source in sources {
        fs::create_dir_all(&folder)?;
        let log = folder.join(format!(
            "{}-build.log",
            source.file_stem().unwrap().to_string_lossy()
        ));
        let mut output_display = if quiet {
            progress::BuildOutput::with_quiet(
                &source,
                &log,
                options.json,
                options.no_progress,
                true,
            )?
        } else {
            progress::BuildOutput::new(&source, &log, options.json, options.no_progress)?
        };
        let mut command = project.command()?;
        command
            .arg("-u")
            .arg(&worker)
            .arg(&source)
            .arg("--project-root")
            .arg(&project.root)
            .arg("--output-dir")
            .arg(&output)
            .arg("--micropython")
            .arg(&pin)
            .arg("--runtime")
            .arg(&options.runtime)
            .arg("--profile")
            .arg(profile)
            .arg("--casthon")
            .arg(env::current_exe()?)
            .arg("--progress");
        if let Some(heap) = &options.heap {
            command.arg("--heap").arg(heap);
        }
        if options.minify {
            command.arg("--minify");
        }
        let code = progress::run_worker(&mut command, &mut output_display)?;
        if code != 0 {
            output_display.finish(false)?;
            return Ok(code);
        }
        output_display.start("Checking build report", None)?;
        let name = source.file_stem().unwrap().to_string_lossy();
        let wasm = folder.join(format!("{name}.wasm"));
        let report = folder.join(format!("{name}-build-report.json"));
        let metadata: Value = serde_json::from_slice(
            &fs::read(&report).context("Builder did not produce its report")?,
        )?;
        let bytes = fs::read(&wasm).context("Builder did not produce Wasm")?;
        wasm_softfloat::validate(&bytes)?;
        ensure!(
            metadata["sha256"].as_str() == Some(hash(&bytes).as_str()),
            "Build report does not match Wasm"
        );
        ensure!(
            metadata["micropython"].as_str() == Some(pin.as_str()),
            "Builder used a different MicroPython version"
        );
        ensure!(
            metadata["buildProfile"].as_str() == Some(profile),
            "Builder used a different debug/release profile"
        );
        let metered = folder.join(format!("{name}.metered.wasm"));
        ensure!(metered.is_file(), "Builder did not produce metered Wasm");
        artifacts.push(json!({"source": source, "wasm": wasm, "meteredWasm": metered, "report": report, "log": log, "metadata": metadata}));
        output_display.finish(true)?;
        if announce && !options.json {
            println!("Built {}", wasm.display());
        }
    }
    if announce && options.json {
        println!(
            "{}",
            serde_json::to_string(
                &json!({"schemaVersion": 1, "project": project.root, "micropython": pin, "buildProfile": profile, "artifacts": artifacts})
            )?
        );
    }
    Ok(0)
}

fn inspect(project: &Project, path: &Path, machine: bool) -> Result<i32> {
    let path = absolute(&project.cwd, path);
    let bytes = fs::read(&path).with_context(|| format!("Cannot read {}", path.display()))?;
    let inspection = wasm_softfloat::inspect(&bytes)?;
    let error = wasm_softfloat::validate(&bytes)
        .err()
        .map(|e| format!("{e:#}"));
    let value = json!({"wasm": path, "bytes": bytes.len(), "sha256": hash(&bytes),
        "exports": inspection.exports, "imports": inspection.imports,
        "memoryPages": inspection.memory, "casperV1Compatible": error.is_none(), "validationError": error});
    if machine {
        println!("{}", serde_json::to_string(&value)?);
    } else {
        println!(
            "{}\n{} bytes\nSHA256 {}",
            path.display(),
            bytes.len(),
            value["sha256"].as_str().unwrap()
        );
        println!("Function exports: {}", inspection.exports.join(", "));
        println!(
            "Host imports: {}\nMemory pages (initial, maximum): {:?}",
            inspection.imports.len(),
            inspection.memory
        );
        println!(
            "Casper V1: {}",
            value["validationError"].as_str().unwrap_or("compatible")
        );
    }
    Ok(0)
}

fn write_embedded_template(
    directory: &Path,
    files: &[templates::TemplateFile],
    name: &str,
    dependency: &str,
    micropython: &str,
) -> Result<()> {
    for file in files {
        let source = std::str::from_utf8(file.contents)
            .with_context(|| format!("Template file {} is not UTF-8", file.path))?;
        let rendered = source
            .replace("{{PROJECT_NAME}}", name)
            .replace("{{SDK_DEPENDENCY}}", dependency)
            .replace("{{MICROPYTHON_VERSION}}", micropython);
        let destination = directory.join(file.path);
        fs::create_dir_all(
            destination
                .parent()
                .context("Template file has no parent")?,
        )?;
        fs::write(destination, rendered)?;
    }
    Ok(())
}

fn new_project(project: &Project, directory: &Path, template: &str) -> Result<i32> {
    let directory = absolute(&project.cwd, directory);
    ensure!(
        !directory.exists(),
        "Destination already exists: {}",
        directory.display()
    );
    let name = directory
        .file_name()
        .and_then(|s| s.to_str())
        .context("Project needs a name")?
        .replace('_', "-");
    ensure!(
        !name.is_empty() && name.bytes().all(|c| c.is_ascii_alphanumeric() || c == b'-'),
        "Use letters, digits and hyphens in the project name"
    );
    let sdk_manifest: toml::Value =
        toml::from_str(&fs::read_to_string(project.sdk.join("pyproject.toml"))?)?;
    let dependency = format!(
        "{}=={}",
        sdk_manifest["project"]["name"]
            .as_str()
            .context("SDK has no package name")?,
        sdk_manifest["project"]["version"]
            .as_str()
            .context("SDK has no package version")?
    );
    if template == "flipper" {
        write_embedded_template(
            &directory,
            templates::FLIPPER,
            &name,
            &dependency,
            &project.supported,
        )?;
        println!("Created {} ({template})", directory.display());
        return Ok(0);
    }
    let files = if template == "cep18" {
        vec![
            "cep18.py",
            "cep18_errors.py",
            "cep18_events.py",
            "my_token.py",
        ]
    } else {
        vec!["ownable.py", "pausable.py", "counter.py"]
    };
    for file in &files {
        ensure!(
            project.sdk.join("contracts").join(file).is_file(),
            "Template source {file} is missing"
        );
    }
    if template == "cep18" {
        ensure!(
            project.sdk.join("reference/cep18/LICENSE").is_file(),
            "CEP-18 license is missing from the SDK checkout"
        );
    }
    fs::create_dir_all(directory.join("contracts"))?;
    fs::create_dir(directory.join("tests"))?;
    fs::write(directory.join("contracts/__init__.py"), "")?;
    for file in files {
        fs::copy(
            project.sdk.join("contracts").join(file),
            directory.join("contracts").join(file),
        )?;
    }
    if template == "cep18" {
        fs::create_dir_all(directory.join("reference/cep18"))?;
        fs::copy(
            project.sdk.join("reference/cep18/LICENSE"),
            directory.join("reference/cep18/LICENSE"),
        )?;
    }
    let target = if template == "cep18" {
        "my_token"
    } else {
        "counter"
    };
    let test = if template == "cep18" {
        "from contracts.my_token import MyToken\n\ndef test_supply():\n    with use_host(MockHost()):\n        token = MyToken()\n        assert token.total_supply() == 1_000_000 * 10**18\n"
    } else {
        "from contracts.counter import Counter\n\ndef test_increment():\n    with use_host(MockHost()):\n        counter = Counter(3)\n        counter.increment_by(2)\n        assert counter.get() == 5\n"
    };
    fs::write(
        directory.join("tests/test_contract.py"),
        format!("from casthon.testing import MockHost, use_host\n{test}"),
    )?;
    fs::write(
        directory.join("pyproject.toml"),
        format!(
            "[project]\nname = {name:?}\nversion = \"0.1.0\"\nrequires-python = \">=3.11\"\ndependencies = [{dependency:?}]\n\n[dependency-groups]\ndev = [\"mypy==1.19.1\", \"pytest==9.1.1\", \"wasmtime==49.0.0\"]\n\n[tool.casthon]\nmicropython = {:?}\ntargets = [\"contracts/{target}.py\"]\n\n[tool.pytest.ini_options]\ntestpaths = [\"tests\"]\n",
            project.supported
        ),
    )?;
    fs::write(
        directory.join(".gitignore"),
        ".venv/\n.cache/\nbuild/\n__pycache__/\n.pytest_cache/\n",
    )?;
    fs::write(
        directory.join("README.md"),
        format!(
            "# {name}\n\nInstall the pinned Casthon SDK and development tools, then build and test:\n\n```sh\nuv sync\ncasthon build\ncasthon test\ncasthon check contracts\n```\n"
        ),
    )?;
    println!("Created {} ({template})", directory.display());
    Ok(0)
}

fn run(cli: Cli) -> Result<i32> {
    let presentation = match &cli.command {
        Action::Call(options) => Some(options.presentation()),
        Action::Deploy(options) => Some(options.presentation()),
        _ => None,
    };
    let mut report = presentation.as_ref().map(|(_, report)| report.clone());
    let outcome = run_command(cli, report.as_mut());
    if let Some((output, _)) = presentation {
        output.finish(report.expect("network command has result"), outcome)
    } else {
        outcome
    }
}

fn run_command(cli: Cli, report: Option<&mut output::CommandResult>) -> Result<i32> {
    if let Action::Wasm(arguments) = &cli.command {
        wasm_softfloat::run_tool(
            arguments
                .args
                .iter()
                .map(|s| {
                    s.to_str()
                        .context("Wasm tool arguments must be UTF-8")
                        .map(str::to_owned)
                })
                .collect::<Result<_>>()?,
        )?;
        return Ok(0);
    }
    let project = Project::load(&cli)?;
    let casper_cli = cli.casper_cli.clone();
    match cli.command {
        Action::Build(options) => build(&project, options),
        Action::Test(options) => testing::run(&project, options),
        Action::Check(args) => project.forward("mypy", &args.args),
        Action::Inspect { wasm, json } => inspect(&project, &wasm, json),
        Action::Doctor => doctor::run(&project, &casper_cli),
        Action::Deploy(options) => deployment::deploy(
            &project,
            &casper_cli,
            options,
            report.expect("deploy result"),
        ),
        Action::Call(options) => {
            deployment::call(&project, &casper_cli, options, report.expect("call result"))
        }
        Action::New {
            directory,
            template,
        } => new_project(&project, &directory, &template),
        Action::Wasm(_) => unreachable!(),
    }
}

fn main() {
    match run(Cli::parse()) {
        Ok(code) => std::process::exit(code),
        Err(error) => {
            eprintln!("error: {error:#}");
            std::process::exit(1);
        }
    }
}
