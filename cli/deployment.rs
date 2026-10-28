use super::{Build, Project, absolute, build, hash, progress::WorkflowOutput};
use anyhow::{Context, Result, bail, ensure};
use clap::Args;
use serde::{Deserialize, Serialize};
use serde_json::Value;
use std::{
    collections::{BTreeMap, BTreeSet},
    fs,
    io::Read,
    path::{Path, PathBuf},
    process::{Child, Command, ExitStatus, Output, Stdio},
    thread,
    time::{Duration, Instant, SystemTime, UNIX_EPOCH},
};

const PROCESS_POLL_INTERVAL: Duration = Duration::from_millis(200);
const PROCESS_HEARTBEAT_INTERVAL: Duration = Duration::from_secs(5);
const DEPLOYMENT_SCHEMA_VERSION: u8 = 1;

#[derive(Args)]
struct ExecutionWait {
    /// Return after submission instead of waiting for execution.
    #[arg(long)]
    no_wait: bool,
    /// Maximum number of seconds to wait for execution.
    #[arg(long, default_value_t = 600)]
    wait_timeout: u64,
}

fn wait_with_progress(
    child: &mut Child,
    description: &str,
    waiting_hint: &str,
    started: Instant,
    workflow: &WorkflowOutput,
) -> Result<ExitStatus> {
    let mut next_heartbeat = PROCESS_HEARTBEAT_INTERVAL;
    loop {
        if let Some(status) = child
            .try_wait()
            .with_context(|| format!("Could not wait for {description}"))?
        {
            return Ok(status);
        }
        if started.elapsed() >= next_heartbeat {
            workflow.heartbeat(description, waiting_hint, started);
            next_heartbeat += PROCESS_HEARTBEAT_INTERVAL;
        }
        thread::sleep(PROCESS_POLL_INTERVAL);
    }
}

fn status_with_progress(
    command: &mut Command,
    description: &str,
    waiting_hint: &str,
    workflow: &WorkflowOutput,
) -> Result<ExitStatus> {
    let started = Instant::now();
    let mut child = command
        .spawn()
        .with_context(|| format!("Could not start {description}"))?;
    wait_with_progress(&mut child, description, waiting_hint, started, workflow)
}

fn output_with_progress(
    command: &mut Command,
    description: &str,
    waiting_hint: &str,
    workflow: &WorkflowOutput,
) -> Result<Output> {
    workflow.note(description);
    workflow.command(command, true);
    let started = Instant::now();
    command.stdout(Stdio::piped()).stderr(Stdio::piped());
    let mut child = command
        .spawn()
        .with_context(|| format!("Could not start {description}"))?;
    let mut stdout = child
        .stdout
        .take()
        .context("Could not capture casper-cli stdout")?;
    let mut stderr = child
        .stderr
        .take()
        .context("Could not capture casper-cli stderr")?;
    let stdout_reader = thread::spawn(move || {
        let mut bytes = Vec::new();
        stdout.read_to_end(&mut bytes).map(|_| bytes)
    });
    let stderr_reader = thread::spawn(move || {
        let mut bytes = Vec::new();
        stderr.read_to_end(&mut bytes).map(|_| bytes)
    });
    let status = wait_with_progress(&mut child, description, waiting_hint, started, workflow)?;
    let stdout = stdout_reader
        .join()
        .map_err(|_| anyhow::anyhow!("casper-cli stdout reader panicked"))??;
    let stderr = stderr_reader
        .join()
        .map_err(|_| anyhow::anyhow!("casper-cli stderr reader panicked"))??;
    let result = Output {
        status,
        stdout,
        stderr,
    };
    if !result.status.success() {
        let stderr = String::from_utf8_lossy(&result.stderr);
        let stdout = String::from_utf8_lossy(&result.stdout);
        let diagnostic = if stderr.trim().is_empty() {
            stdout.trim()
        } else {
            stderr.trim()
        };
        bail!("{description} failed: {diagnostic}");
    }
    Ok(result)
}

#[derive(Args)]
pub struct Deploy {
    /// Contract source or contracts/<name>.py alias; defaults to the single configured target.
    target: Option<PathBuf>,
    /// casper-cli wallet/account reference, for example testnet-funds:account-0.
    #[arg(long)]
    from: String,
    /// casper-cli network profile or chain name; selected explicitly before deployment.
    #[arg(long)]
    network: String,
    /// Runtime argument in casper-cli NAME:CLTYPE=VALUE form.
    #[arg(long = "arg", value_name = "NAME:CLTYPE=VALUE")]
    arguments: Vec<String>,
    /// Maximum standard-payment allowance in CSPR.
    #[arg(long, default_value = "800")]
    payment_amount: String,
    /// Maximum gas price accepted by the transaction.
    #[arg(long, default_value_t = 1)]
    gas_price_tolerance: u8,
    /// Submit instead of the default speculative-execution-only run.
    #[arg(long)]
    broadcast: bool,
    /// Use casper-cli's local execution engine with state queried from the public RPC.
    #[arg(long, conflicts_with = "broadcast")]
    simulate: bool,
    /// Use an existing build/release artifact instead of rebuilding it.
    #[arg(long)]
    no_build: bool,
    #[command(flatten)]
    wait: ExecutionWait,
}

#[derive(Args)]
pub struct Call {
    /// Deployed contract name from deployments/<network>/<name>.json.
    deployment: String,
    /// Stored contract entry point to invoke.
    entry_point: String,
    /// Wallet/account reference; defaults to the signer recorded by deployment.
    #[arg(long)]
    from: Option<String>,
    /// Deployment network; inferred when the name exists on exactly one network.
    #[arg(long)]
    network: Option<String>,
    /// Runtime argument; CLType is inferred from the deployment ABI when omitted.
    #[arg(long = "arg", value_name = "NAME[:CLTYPE]=VALUE")]
    arguments: Vec<String>,
    /// Maximum standard-payment allowance in CSPR.
    #[arg(long, default_value = "2.5")]
    payment_amount: String,
    /// Maximum gas price accepted by the transaction.
    #[arg(long, default_value_t = 1)]
    gas_price_tolerance: u8,
    /// Submit instead of the default speculative-execution-only run.
    #[arg(long)]
    broadcast: bool,
    /// Use casper-cli's local execution engine with state queried from the public RPC.
    #[arg(long, conflicts_with = "broadcast")]
    simulate: bool,
    #[command(flatten)]
    wait: ExecutionWait,
}

#[derive(Clone, Deserialize, Serialize)]
#[serde(rename_all = "camelCase")]
struct ArtifactRecord {
    source: PathBuf,
    wasm: PathBuf,
    build_report: PathBuf,
    sha256: String,
    micropython: Option<String>,
    build_profile: Option<String>,
}

#[derive(Clone, Deserialize, Serialize)]
#[serde(rename_all = "camelCase")]
struct EntryPointArgument {
    name: String,
    #[serde(rename = "type")]
    cl_type: String,
    #[serde(default)]
    has_default: bool,
    #[serde(default)]
    optional_arg: bool,
}

#[derive(Clone, Deserialize, Serialize)]
#[serde(rename_all = "camelCase")]
struct EntryPointSignature {
    args: Vec<EntryPointArgument>,
    returns: Option<String>,
    access: String,
    #[serde(default, skip_serializing_if = "Vec::is_empty")]
    groups: Vec<String>,
    entry_point_type: String,
    payment: String,
}

#[derive(Clone, Deserialize, Serialize)]
#[serde(rename_all = "camelCase")]
struct AbiRecord {
    artifact_sha256: String,
    entry_points: BTreeMap<String, EntryPointSignature>,
}

#[derive(Clone, Copy, Deserialize, Serialize)]
#[serde(rename_all = "camelCase")]
enum CallTargetKind {
    Package,
    Entity,
    Contract,
}

#[derive(Clone, Deserialize, Serialize)]
#[serde(rename_all = "camelCase")]
struct CallTarget {
    kind: CallTargetKind,
    hash: String,
}

#[derive(Clone, Deserialize, Serialize)]
#[serde(rename_all = "camelCase")]
struct DeploymentRecord {
    status: String,
    network_profile: String,
    chain_name: String,
    artifact: ArtifactRecord,
    abi: AbiRecord,
    signer: String,
    arguments: Vec<String>,
    payment_amount_cspr: String,
    gas_price_tolerance: u8,
    transaction_hash: String,
    submitted_at_unix: u64,
    casthon_version: String,
    casper_cli_version: String,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    block_hash: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    block_height: Option<u64>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    gas_consumed: Option<Value>,
    #[serde(default, skip_serializing_if = "BTreeMap::is_empty")]
    addresses: BTreeMap<String, Vec<String>>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    call_target: Option<CallTarget>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    error: Option<String>,
}

#[derive(Deserialize, Serialize)]
#[serde(rename_all = "camelCase")]
struct DeploymentManifest {
    schema_version: u8,
    name: String,
    network_profile: String,
    chain_name: String,
    current: DeploymentRecord,
    #[serde(default)]
    history: Vec<DeploymentRecord>,
}

fn output(command: &mut Command, description: &str) -> Result<std::process::Output> {
    let result = command
        .output()
        .with_context(|| format!("Could not run {description}"))?;
    if !result.status.success() {
        let stderr = String::from_utf8_lossy(&result.stderr);
        let stdout = String::from_utf8_lossy(&result.stdout);
        let diagnostic = if stderr.trim().is_empty() {
            stdout.trim()
        } else {
            stderr.trim()
        };
        bail!("{description} failed: {diagnostic}");
    }
    Ok(result)
}

pub fn probe(casper_cli: &Path) -> Result<String> {
    let version = output(
        Command::new(casper_cli).arg("--version"),
        &format!("{} --version", casper_cli.display()),
    )?;
    let version = String::from_utf8_lossy(&version.stdout).trim().to_owned();
    ensure!(
        version.starts_with("casper-cli "),
        "unexpected --version output; expected Veles Labs casper-cli"
    );
    let help = output(
        Command::new(casper_cli).args(["transaction", "put", "--help"]),
        &format!("{} transaction put --help", casper_cli.display()),
    )?;
    let help = String::from_utf8_lossy(&help.stdout);
    ensure!(
        help.contains("Build a session transaction from Wasm")
            && help.contains("--install-upgrade")
            && help.contains("--simulate")
            && help.contains("state queries to the network RPC")
            && help.contains("--speculative")
            && help.contains("--raw"),
        "incompatible casper-cli; install Veles Labs casper-cli"
    );
    let call_help = output(
        Command::new(casper_cli).args(["transaction", "call", "--help"]),
        &format!("{} transaction call --help", casper_cli.display()),
    )?;
    let call_help = String::from_utf8_lossy(&call_help.stdout);
    ensure!(
        call_help.contains("Call a stored contract by hash")
            && call_help.contains("--package")
            && call_help.contains("--simulate")
            && call_help.contains("--speculative"),
        "incompatible casper-cli; stored-contract calls require a current Veles Labs casper-cli"
    );
    Ok(version)
}

fn select_source(project: &Project, requested: Option<&Path>) -> Result<PathBuf> {
    let (target, base) = if let Some(target) = requested {
        (target.to_owned(), &project.cwd)
    } else {
        ensure!(
            project.config.targets.len() == 1,
            "Deployment needs one target argument or exactly one [tool.casthon].targets entry"
        );
        (project.config.targets[0].clone(), &project.root)
    };
    let source = if target.extension().is_none() && target.components().count() == 1 {
        project
            .root
            .join("contracts")
            .join(&target)
            .with_extension("py")
    } else {
        absolute(base, &target)
    };
    source
        .canonicalize()
        .with_context(|| format!("Contract source {} does not exist", target.display()))
}

fn relative(project: &Project, path: &Path) -> PathBuf {
    path.strip_prefix(&project.root).unwrap_or(path).to_owned()
}

fn release_artifact(project: &Project, source: &Path) -> Result<(ArtifactRecord, AbiRecord)> {
    let name = source
        .file_stem()
        .and_then(|name| name.to_str())
        .context("Contract source needs a UTF-8 filename")?;
    let folder = project.root.join("build/release");
    let wasm = folder.join(format!("{name}.wasm"));
    let report = folder.join(format!("{name}-build-report.json"));
    let bytes = fs::read(&wasm).with_context(|| {
        format!(
            "Release artifact {} is missing; run casthon build {} --release",
            wasm.display(),
            source.display()
        )
    })?;
    wasm_softfloat::validate(&bytes).context("Release artifact is not Casper V1 compatible")?;
    let metadata: Value = serde_json::from_slice(
        &fs::read(&report)
            .with_context(|| format!("Build report {} is missing", report.display()))?,
    )
    .with_context(|| format!("Invalid build report {}", report.display()))?;
    let digest = hash(&bytes);
    ensure!(
        metadata["sha256"].as_str() == Some(&digest),
        "Build report does not match {}",
        wasm.display()
    );
    ensure!(
        metadata["buildProfile"].as_str() == Some("release"),
        "Deployment requires a release build"
    );
    let entry_points = serde_json::from_value::<BTreeMap<String, EntryPointSignature>>(
        metadata.get("entryPoints").cloned().context(
            "Build report has no stored-contract entryPoints; rebuild with this Casthon",
        )?,
    )
    .with_context(|| format!("Invalid entryPoints in {}", report.display()))?;
    let artifact = ArtifactRecord {
        source: relative(project, source),
        wasm: relative(project, &wasm),
        build_report: relative(project, &report),
        sha256: digest,
        micropython: metadata["micropython"].as_str().map(str::to_owned),
        build_profile: metadata["buildProfile"].as_str().map(str::to_owned),
    };
    let abi = AbiRecord {
        artifact_sha256: artifact.sha256.clone(),
        entry_points,
    };
    Ok((artifact, abi))
}

fn select_network(
    casper_cli: &Path,
    requested: &str,
    workflow: &WorkflowOutput,
) -> Result<(String, String)> {
    output_with_progress(
        Command::new(casper_cli).args(["network", "use", requested]),
        &format!("Selecting casper-cli network {requested}"),
        "casper-cli is still updating its network configuration",
        workflow,
    )?;
    let listed = output_with_progress(
        Command::new(casper_cli).args(["network", "list"]),
        "Reading active casper-cli network",
        "casper-cli is still reading its network configuration",
        workflow,
    )?;
    let text = String::from_utf8_lossy(&listed.stdout);
    for line in text.lines() {
        if !line.trim_start().starts_with('|') {
            continue;
        }
        let cells: Vec<_> = line.trim_matches('|').split('|').map(str::trim).collect();
        if cells.len() >= 3 && cells[2] == "yes" {
            ensure!(
                cells[0] == requested || cells[1] == requested,
                "casper-cli selected {}, not {requested}",
                cells[0]
            );
            return Ok((cells[0].to_owned(), cells[1].to_owned()));
        }
    }
    bail!("Could not identify the active network from casper-cli network list")
}

fn put_command(
    casper_cli: &Path,
    project: &Project,
    options: &Deploy,
    artifact: &ArtifactRecord,
) -> Command {
    let mut command = Command::new(casper_cli);
    command
        .current_dir(&project.root)
        .args(["transaction", "put"])
        .arg(&artifact.wasm)
        .arg("--from")
        .arg(&options.from)
        .arg("--install-upgrade")
        .arg("--payment-amount")
        .arg(&options.payment_amount)
        .arg("--gas-price-tolerance")
        .arg(options.gas_price_tolerance.to_string());
    for argument in &options.arguments {
        command.arg("--arg").arg(argument);
    }
    command
}

fn submitted_hash(
    command: &mut Command,
    action: &str,
    workflow: &mut WorkflowOutput,
) -> Result<String> {
    command
        .arg("--raw")
        .stdin(Stdio::inherit())
        .stderr(Stdio::inherit())
        .stdout(Stdio::piped());
    workflow.external_start(action, command);
    let started = Instant::now();
    let mut child = command
        .spawn()
        .context("Could not run casper-cli transaction submission")?;
    let mut stdout = child
        .stdout
        .take()
        .context("Could not capture casper-cli transaction hash")?;
    let stdout_reader = thread::spawn(move || {
        let mut text = String::new();
        stdout.read_to_string(&mut text).map(|_| text)
    });
    let status = wait_with_progress(
        &mut child,
        action,
        "casper-cli may be waiting for wallet unlock or an RPC response",
        started,
        workflow,
    )?;
    let stdout = stdout_reader
        .join()
        .map_err(|_| anyhow::anyhow!("casper-cli transaction hash reader panicked"))??;
    workflow.external_finish(status.success());
    ensure!(status.success(), "casper-cli transaction submission failed");
    let value = stdout.trim();
    ensure!(
        value.len() == 64 && value.bytes().all(|byte| byte.is_ascii_hexdigit()),
        "casper-cli returned an invalid transaction hash: {value}"
    );
    Ok(format!(
        "transaction-v1-hash-{}",
        value.to_ascii_lowercase()
    ))
}

fn execution_error(execution: &Value) -> Result<Option<String>> {
    let result = execution
        .get("execution_result")
        .context("casper-cli execution info has no execution_result")?;
    if result.is_null() {
        return Ok(None);
    }
    if let Some(version) = result.get("Version2") {
        return Ok(version
            .get("error_message")
            .and_then(Value::as_str)
            .map(str::to_owned));
    }
    if let Some(version) = result.get("Version1") {
        if let Some(failure) = version.get("Failure") {
            return Ok(Some(
                failure
                    .get("error_message")
                    .and_then(Value::as_str)
                    .unwrap_or("transaction execution failed")
                    .to_owned(),
            ));
        }
        if version.get("Success").is_some() {
            return Ok(None);
        }
    }
    bail!("Unsupported execution result from casper-cli")
}

fn gas_consumed(execution: &Value) -> Option<Value> {
    execution
        .pointer("/execution_result/Version2/consumed")
        .or_else(|| execution.pointer("/execution_result/Version1/Success/cost"))
        .or_else(|| execution.pointer("/execution_result/Version1/Failure/cost"))
        .cloned()
}

fn address_kind(value: &str) -> Option<&'static str> {
    for (prefix, kind) in [
        ("package-", "packages"),
        ("contract-package-", "contractPackages"),
        ("addressable-entity-", "entities"),
        ("byte-code-", "bytecodes"),
        ("contract-wasm-", "contractWasms"),
        ("contract-", "contracts"),
    ] {
        if value.starts_with(prefix) {
            return Some(kind);
        }
    }
    None
}

fn collect_addresses(value: &Value, found: &mut BTreeMap<String, BTreeSet<String>>) {
    match value {
        Value::String(value) => {
            if let Some(kind) = address_kind(value) {
                found
                    .entry(kind.to_owned())
                    .or_default()
                    .insert(value.clone());
            }
        }
        Value::Array(values) => {
            for value in values {
                collect_addresses(value, found);
            }
        }
        Value::Object(values) => {
            for value in values.values() {
                collect_addresses(value, found);
            }
        }
        _ => {}
    }
}

fn addresses(execution: &Value) -> BTreeMap<String, Vec<String>> {
    let mut found = BTreeMap::<String, BTreeSet<String>>::new();
    collect_addresses(execution, &mut found);
    found
        .into_iter()
        .map(|(kind, values)| (kind, values.into_iter().collect()))
        .collect()
}

fn unique_address(addresses: &BTreeMap<String, Vec<String>>, kinds: &[&str]) -> Option<String> {
    let values = kinds
        .iter()
        .filter_map(|kind| addresses.get(*kind))
        .flatten()
        .collect::<BTreeSet<_>>();
    (values.len() == 1).then(|| (*values.first().expect("one address")).clone())
}

fn call_target(addresses: &BTreeMap<String, Vec<String>>) -> Option<CallTarget> {
    if let Some(hash) = unique_address(addresses, &["packages", "contractPackages"]) {
        return Some(CallTarget {
            kind: CallTargetKind::Package,
            hash,
        });
    }
    if let Some(hash) = unique_address(addresses, &["entities"]) {
        return Some(CallTarget {
            kind: CallTargetKind::Entity,
            hash,
        });
    }
    unique_address(addresses, &["contracts"]).map(|hash| CallTarget {
        kind: CallTargetKind::Contract,
        hash,
    })
}

fn manifest_path(project: &Project, network: &str, name: &str) -> PathBuf {
    project
        .root
        .join("deployments")
        .join(network)
        .join(format!("{name}.json"))
}

fn write_manifest(
    project: &Project,
    name: &str,
    network: &str,
    chain_name: &str,
    record: DeploymentRecord,
) -> Result<PathBuf> {
    let path = manifest_path(project, network, name);
    let mut manifest = if path.is_file() {
        let existing: DeploymentManifest = serde_json::from_slice(&fs::read(&path)?)
            .with_context(|| format!("Invalid deployment manifest {}", path.display()))?;
        ensure!(
            existing.schema_version == DEPLOYMENT_SCHEMA_VERSION,
            "Unsupported deployment manifest schema {} in {}; expected {}",
            existing.schema_version,
            path.display(),
            DEPLOYMENT_SCHEMA_VERSION
        );
        ensure!(
            existing.name == name
                && existing.network_profile == network
                && existing.chain_name == chain_name,
            "Deployment manifest identity does not match {}",
            path.display()
        );
        existing
    } else {
        DeploymentManifest {
            schema_version: DEPLOYMENT_SCHEMA_VERSION,
            name: name.to_owned(),
            network_profile: network.to_owned(),
            chain_name: chain_name.to_owned(),
            current: record.clone(),
            history: vec![],
        }
    };
    if manifest.current.transaction_hash != record.transaction_hash {
        manifest.history.push(manifest.current.clone());
    }
    manifest.current = record;
    let parent = path.parent().context("Deployment manifest has no parent")?;
    fs::create_dir_all(parent)?;
    let temporary = parent.join(format!(".{name}.json.tmp-{}", std::process::id()));
    let mut bytes = serde_json::to_vec_pretty(&manifest)?;
    bytes.push(b'\n');
    fs::write(&temporary, bytes)?;
    fs::rename(&temporary, &path)?;
    Ok(path)
}

fn wait_for_execution(
    casper_cli: &Path,
    project: &Project,
    transaction_hash: &str,
    timeout: Duration,
    workflow: &mut WorkflowOutput,
) -> Result<Value> {
    println!("Waiting for execution...");
    workflow.start("Waiting for transaction execution");
    let started = Instant::now();
    let mut attempt = 1_u64;
    loop {
        let result = output_with_progress(
            Command::new(casper_cli).current_dir(&project.root).args([
                "transaction",
                "get",
                transaction_hash,
                "--raw",
            ]),
            &format!("Checking execution status (attempt {attempt})"),
            "the RPC node has not answered yet",
            workflow,
        )?;
        let value: Value = serde_json::from_slice(&result.stdout)
            .context("casper-cli transaction get returned invalid JSON")?;
        if !value.is_null() && !value["execution_result"].is_null() {
            workflow.finish(Some(format!("block {}", execution_block(&value))));
            return Ok(value);
        }
        ensure!(
            started.elapsed() < timeout,
            "Timed out waiting for {transaction_hash}; the transaction was already submitted and may still execute"
        );
        workflow.note(format!(
            "Transaction is pending; checking again in 5s (timeout: {}s)",
            timeout.as_secs()
        ));
        thread::sleep(Duration::from_secs(5).min(timeout.saturating_sub(started.elapsed())));
        attempt += 1;
    }
}

fn execution_block(execution: &Value) -> String {
    execution["block_height"]
        .as_u64()
        .map_or_else(|| "unknown".to_owned(), |height| height.to_string())
}

fn safe_path_component(value: &str, description: &str) -> Result<()> {
    ensure!(
        !value.is_empty()
            && value
                .bytes()
                .all(|byte| byte.is_ascii_alphanumeric() || matches!(byte, b'_' | b'-' | b'.'))
            && value != "."
            && value != "..",
        "Invalid {description} '{value}'"
    );
    Ok(())
}

fn find_manifest(project: &Project, name: &str, network: Option<&str>) -> Result<PathBuf> {
    safe_path_component(name, "deployment name")?;
    if let Some(network) = network {
        safe_path_component(network, "network profile")?;
        let path = manifest_path(project, network, name);
        ensure!(
            path.is_file(),
            "No deployment manifest for '{name}' on '{network}' at {}",
            path.display()
        );
        return Ok(path);
    }

    let deployments = project.root.join("deployments");
    let mut matches = Vec::new();
    if deployments.is_dir() {
        for entry in fs::read_dir(&deployments)? {
            let entry = entry?;
            if entry.file_type()?.is_dir() {
                let path = entry.path().join(format!("{name}.json"));
                if path.is_file() {
                    matches.push(path);
                }
            }
        }
    }
    matches.sort();
    ensure!(
        !matches.is_empty(),
        "No deployment manifest named '{name}' under {}",
        deployments.display()
    );
    ensure!(
        matches.len() == 1,
        "Deployment '{name}' exists on multiple networks ({}); pass --network",
        matches
            .iter()
            .filter_map(|path| path.parent()?.file_name()?.to_str())
            .collect::<Vec<_>>()
            .join(", ")
    );
    Ok(matches.remove(0))
}

fn read_manifest(
    project: &Project,
    name: &str,
    network: Option<&str>,
) -> Result<(PathBuf, DeploymentManifest)> {
    let path = find_manifest(project, name, network)?;
    let manifest: DeploymentManifest = serde_json::from_slice(&fs::read(&path)?)
        .with_context(|| format!("Invalid deployment manifest {}", path.display()))?;
    ensure!(
        manifest.schema_version == DEPLOYMENT_SCHEMA_VERSION,
        "Unsupported deployment manifest schema {} in {}; expected {}",
        manifest.schema_version,
        path.display(),
        DEPLOYMENT_SCHEMA_VERSION
    );
    ensure!(
        manifest.name == name,
        "Deployment manifest name does not match {}",
        path.display()
    );
    ensure!(
        path.parent()
            .and_then(Path::file_name)
            .and_then(|value| value.to_str())
            == Some(manifest.network_profile.as_str()),
        "Deployment manifest network does not match {}",
        path.display()
    );
    Ok((path, manifest))
}

fn callable_record(manifest: &DeploymentManifest) -> Result<&DeploymentRecord> {
    std::iter::once(&manifest.current)
        .chain(manifest.history.iter().rev())
        .find(|record| record.status == "executed" && record.call_target.is_some())
        .with_context(|| {
            format!(
                "Deployment '{}' has no successfully executed record with an unambiguous call target",
                manifest.name
            )
        })
}

fn call_arguments(supplied: &[String], signature: &EntryPointSignature) -> Result<Vec<String>> {
    let expected = signature
        .args
        .iter()
        .map(|argument| (argument.name.as_str(), argument))
        .collect::<BTreeMap<_, _>>();
    let mut seen = BTreeSet::new();
    let mut rendered = Vec::new();
    for value in supplied {
        let (declaration, encoded) = value
            .split_once('=')
            .with_context(|| format!("Invalid --arg '{value}'; expected NAME[:CLTYPE]=VALUE"))?;
        let (name, explicit_type) = declaration
            .split_once(':')
            .map_or((declaration, None), |(name, cl_type)| (name, Some(cl_type)));
        ensure!(!name.is_empty(), "Argument name cannot be empty");
        ensure!(seen.insert(name), "Duplicate argument '{name}'");
        let argument = expected
            .get(name)
            .with_context(|| format!("Entry point does not declare an argument named '{name}'"))?;
        if let Some(explicit_type) = explicit_type {
            ensure!(
                !explicit_type.is_empty() && explicit_type == argument.cl_type,
                "Argument '{name}' has CLType {}; manifest ABI requires {}",
                explicit_type,
                argument.cl_type
            );
        }
        rendered.push(format!("{name}:{}={encoded}", argument.cl_type));
    }
    let missing = signature
        .args
        .iter()
        .filter(|argument| !argument.optional_arg && !seen.contains(argument.name.as_str()))
        .map(|argument| format!("{}:{}", argument.name, argument.cl_type))
        .collect::<Vec<_>>();
    ensure!(
        missing.is_empty(),
        "Missing required argument{}: {}",
        if missing.len() == 1 { "" } else { "s" },
        missing.join(", ")
    );
    Ok(rendered)
}

fn call_target_kind(kind: &CallTargetKind) -> &'static str {
    match kind {
        CallTargetKind::Package => "package",
        CallTargetKind::Entity => "entity",
        CallTargetKind::Contract => "contract",
    }
}

pub fn call(project: &Project, casper_cli: &Path, options: Call) -> Result<i32> {
    let (manifest_path, manifest) =
        read_manifest(project, &options.deployment, options.network.as_deref())?;
    let record = callable_record(&manifest)?;
    ensure!(
        record.network_profile == manifest.network_profile
            && record.chain_name == manifest.chain_name,
        "Callable deployment record does not match manifest network identity"
    );
    ensure!(
        record.abi.artifact_sha256 == record.artifact.sha256,
        "Deployment ABI does not match its recorded artifact hash"
    );
    let available = record.abi.entry_points.keys().cloned().collect::<Vec<_>>();
    let signature = record
        .abi
        .entry_points
        .get(&options.entry_point)
        .with_context(|| {
            format!(
                "Unknown entry point '{}' for deployment '{}'; available: {}",
                options.entry_point,
                options.deployment,
                if available.is_empty() {
                    "<none>".to_owned()
                } else {
                    available.join(", ")
                }
            )
        })?;
    let arguments = call_arguments(&options.arguments, signature)?;
    let target = record
        .call_target
        .as_ref()
        .expect("callable record has target");
    let signer = options.from.as_deref().unwrap_or(&record.signer);
    let mode = if options.broadcast {
        "broadcast — signs and submits to the network"
    } else if options.simulate {
        "local simulation — no submission"
    } else {
        "node speculative execution — no submission"
    };

    let mut workflow = WorkflowOutput::new(format!(
        "Calling {}::{}",
        options.deployment, options.entry_point
    ));
    workflow.detail("Manifest", relative(project, &manifest_path).display());
    workflow.detail(
        "Target",
        format!("{} {}", call_target_kind(&target.kind), target.hash),
    );
    workflow.detail("Network", &manifest.network_profile);
    workflow.detail("Mode", mode);
    workflow.detail("Signer", signer);
    workflow.detail("Returns", signature.returns.as_deref().unwrap_or("untyped"));
    workflow.detail(
        "Access",
        if signature.groups.is_empty() {
            signature.access.clone()
        } else {
            format!("{} ({})", signature.access, signature.groups.join(", "))
        },
    );
    workflow.detail("Entry kind", &signature.entry_point_type);
    workflow.detail("Payment", &signature.payment);
    workflow.detail("Backend", casper_cli.display());

    workflow.start("Checking Veles Labs casper-cli");
    let mut version_command = Command::new(casper_cli);
    version_command.arg("--version");
    workflow.command(&version_command, true);
    let mut put_help_command = Command::new(casper_cli);
    put_help_command.args(["transaction", "put", "--help"]);
    workflow.command(&put_help_command, true);
    let mut call_help_command = Command::new(casper_cli);
    call_help_command.args(["transaction", "call", "--help"]);
    workflow.command(&call_help_command, true);
    let casper_cli_version = probe(casper_cli)?;
    workflow.finish(Some(casper_cli_version));

    workflow.start(format!(
        "Selecting casper-cli network {}",
        manifest.network_profile
    ));
    let (network, chain_name) = select_network(casper_cli, &manifest.network_profile, &workflow)?;
    ensure!(
        network == manifest.network_profile && chain_name == manifest.chain_name,
        "casper-cli selected {network} ({chain_name}), but manifest records {} ({})",
        manifest.network_profile,
        manifest.chain_name
    );
    workflow.finish(Some(format!("{network} ({chain_name})")));

    let mut command = Command::new(casper_cli);
    command
        .current_dir(&project.root)
        .args(["transaction", "call"])
        .arg(&target.hash)
        .arg(&options.entry_point)
        .arg("--from")
        .arg(signer)
        .arg("--payment-amount")
        .arg(&options.payment_amount)
        .arg("--gas-price-tolerance")
        .arg(options.gas_price_tolerance.to_string());
    if matches!(target.kind, CallTargetKind::Package) {
        command.arg("--package");
    }
    for argument in arguments {
        command.arg("--arg").arg(argument);
    }
    if options.broadcast {
        let transaction_hash = submitted_hash(
            &mut command,
            "Signing and submitting contract call",
            &mut workflow,
        )?;
        println!("Submitted {transaction_hash}");
        if options.wait.no_wait {
            return Ok(0);
        }
        let execution = wait_for_execution(
            casper_cli,
            project,
            &transaction_hash,
            Duration::from_secs(options.wait.wait_timeout),
            &mut workflow,
        )?;
        if let Some(error) = execution_error(&execution)? {
            bail!("Transaction {transaction_hash} failed: {error}");
        }
        println!("Executed in block {}", execution_block(&execution));
        return Ok(0);
    }
    let (action, waiting_hint) = if options.simulate {
        command.arg("--simulate");
        (
            "Simulating contract call locally",
            "casper-cli may be waiting for wallet access, an RPC state query, or local execution",
        )
    } else {
        command.arg("--speculative");
        (
            "Speculatively executing contract call",
            "casper-cli may be waiting for wallet access or an RPC response",
        )
    };
    command
        .stdin(Stdio::inherit())
        .stdout(Stdio::inherit())
        .stderr(Stdio::inherit());
    println!("{action}; pass --broadcast to submit it.");
    workflow.external_start(action, &command);
    let status = status_with_progress(&mut command, action, waiting_hint, &workflow)?;
    workflow.external_finish(status.success());
    Ok(status.code().unwrap_or(1))
}

pub fn deploy(project: &Project, casper_cli: &Path, options: Deploy) -> Result<i32> {
    let source = select_source(project, options.target.as_deref())?;
    let name = source
        .file_stem()
        .and_then(|name| name.to_str())
        .context("Contract source needs a UTF-8 filename")?;
    let mode = if options.broadcast {
        "broadcast — signs and submits to the network"
    } else if options.simulate {
        "local simulation — no submission"
    } else {
        "node speculative execution — no submission"
    };
    let mut workflow = WorkflowOutput::new(format!("Deploying {name}"));
    workflow.detail("Contract", relative(project, &source).display());
    workflow.detail("Network", &options.network);
    workflow.detail("Mode", mode);
    workflow.detail("Signer", &options.from);
    workflow.detail("Backend", casper_cli.display());

    workflow.start("Checking Veles Labs casper-cli");
    let mut version_command = Command::new(casper_cli);
    version_command.arg("--version");
    workflow.command(&version_command, true);
    let mut help_command = Command::new(casper_cli);
    help_command.args(["transaction", "put", "--help"]);
    workflow.command(&help_command, true);
    let mut call_help_command = Command::new(casper_cli);
    call_help_command.args(["transaction", "call", "--help"]);
    workflow.command(&call_help_command, true);
    let casper_cli_version = probe(casper_cli)?;
    workflow.finish(Some(&casper_cli_version));

    if !options.no_build {
        workflow.passthrough_start("Building release artifact with Casthon");
        workflow.note(format!("Source: {}", source.display()));
        workflow.note("Nested Casthon build progress follows");
        let code = build(
            project,
            Build {
                targets: options.target.clone().into_iter().collect(),
                micropython: None,
                runtime: "asyncify".to_owned(),
                profile: "release".to_owned(),
                release: false,
                heap: None,
                minify: false,
                output_dir: None,
                json: false,
                no_progress: false,
            },
        )?;
        workflow.passthrough_finish(code == 0);
        if code != 0 {
            return Ok(code);
        }
    } else {
        workflow.start("Using existing release artifact");
        workflow.finish(Some("--no-build"));
    }

    workflow.start("Validating release Wasm and build report");
    let (artifact, abi) = release_artifact(project, &source)?;
    workflow.finish(Some(format!(
        "{} · sha256 {} · {} entry points",
        artifact.wasm.display(),
        artifact.sha256,
        abi.entry_points.len()
    )));

    workflow.start(format!("Selecting casper-cli network {}", options.network));
    let (network, chain_name) = select_network(casper_cli, &options.network, &workflow)?;
    workflow.finish(Some(format!("{network} ({chain_name})")));
    println!("Network: {network} ({chain_name})");
    println!(
        "Artifact: {} ({})",
        artifact.wasm.display(),
        artifact.sha256
    );

    let mut command = put_command(casper_cli, project, &options, &artifact);
    if !options.broadcast {
        let (flag, action, waiting_hint) = if options.simulate {
            (
                "--simulate",
                "Simulating installation locally",
                "casper-cli may be waiting for wallet access, an RPC state query, or local execution",
            )
        } else {
            (
                "--speculative",
                "Speculatively executing installation",
                "casper-cli may be waiting for wallet access or an RPC response",
            )
        };
        println!("{action}; pass --broadcast to submit it.");
        command
            .arg(flag)
            .stdin(Stdio::inherit())
            .stdout(Stdio::inherit())
            .stderr(Stdio::inherit());
        workflow.external_start(action, &command);
        let status = status_with_progress(&mut command, action, waiting_hint, &workflow)?;
        workflow.external_finish(status.success());
        return Ok(status.code().unwrap_or(1));
    }

    println!("Submitting installation from {}...", options.from);
    let transaction_hash = submitted_hash(
        &mut command,
        "Signing and submitting installation",
        &mut workflow,
    )?;
    println!("Submitted {transaction_hash}");
    let mut record = DeploymentRecord {
        status: "submitted".to_owned(),
        network_profile: network.clone(),
        chain_name: chain_name.clone(),
        artifact,
        abi,
        signer: options.from.clone(),
        arguments: options.arguments.clone(),
        payment_amount_cspr: options.payment_amount.clone(),
        gas_price_tolerance: options.gas_price_tolerance,
        transaction_hash: transaction_hash.clone(),
        submitted_at_unix: SystemTime::now().duration_since(UNIX_EPOCH)?.as_secs(),
        casthon_version: env!("CARGO_PKG_VERSION").to_owned(),
        casper_cli_version,
        block_hash: None,
        block_height: None,
        gas_consumed: None,
        addresses: BTreeMap::new(),
        call_target: None,
        error: None,
    };
    workflow.start("Recording submitted deployment");
    let mut path = write_manifest(project, name, &network, &chain_name, record.clone())?;
    workflow.finish(Some(path.display()));
    if options.wait.no_wait {
        println!("Recorded {}", path.display());
        return Ok(0);
    }

    let execution = wait_for_execution(
        casper_cli,
        project,
        &transaction_hash,
        Duration::from_secs(options.wait.wait_timeout),
        &mut workflow,
    )?;
    record.block_hash = execution["block_hash"].as_str().map(str::to_owned);
    record.block_height = execution["block_height"].as_u64();
    record.gas_consumed = gas_consumed(&execution);
    record.addresses = addresses(&execution);
    record.error = execution_error(&execution)?;
    record.status = if record.error.is_some() {
        "failed".to_owned()
    } else {
        "executed".to_owned()
    };
    if record.error.is_none() {
        record.call_target = call_target(&record.addresses);
    }
    workflow.start("Updating deployment manifest");
    path = write_manifest(project, name, &network, &chain_name, record.clone())?;
    workflow.finish(Some(path.display()));
    if let Some(error) = &record.error {
        bail!(
            "Transaction {transaction_hash} failed: {error}; recorded {}",
            path.display()
        );
    }
    println!("Executed in block {}", execution_block(&execution));
    println!("Recorded {}", path.display());
    if let Some(target) = &record.call_target {
        println!(
            "Call target: {} {}",
            call_target_kind(&target.kind),
            target.hash
        );
        if record.abi.entry_points.is_empty() {
            workflow.note("No stored entry points were declared by this artifact");
        } else {
            println!(
                "Callable entry points: {}",
                record
                    .abi
                    .entry_points
                    .keys()
                    .cloned()
                    .collect::<Vec<_>>()
                    .join(", ")
            );
            println!("Next: casthon call {name} <entry-point>");
        }
    } else {
        workflow.note(
            "Warning: execution succeeded, but no unambiguous package/entity address was found; casthon call is unavailable for this record",
        );
    }
    Ok(0)
}

#[cfg(test)]
mod tests {
    use super::*;

    fn signature() -> EntryPointSignature {
        EntryPointSignature {
            args: vec![
                EntryPointArgument {
                    name: "amount".to_owned(),
                    cl_type: "U32".to_owned(),
                    has_default: false,
                    optional_arg: false,
                },
                EntryPointArgument {
                    name: "memo".to_owned(),
                    cl_type: "String".to_owned(),
                    has_default: true,
                    optional_arg: true,
                },
            ],
            returns: Some("Unit".to_owned()),
            access: "public".to_owned(),
            groups: vec![],
            entry_point_type: "called".to_owned(),
            payment: "caller".to_owned(),
        }
    }

    #[test]
    fn call_arguments_infer_and_validate_manifest_types() {
        assert_eq!(
            call_arguments(&["amount=7".to_owned()], &signature()).unwrap(),
            ["amount:U32=7"]
        );
        assert!(
            call_arguments(&[], &signature())
                .unwrap_err()
                .to_string()
                .contains("Missing required argument: amount:U32")
        );
        assert!(
            call_arguments(&["amount:String=7".to_owned()], &signature())
                .unwrap_err()
                .to_string()
                .contains("manifest ABI requires U32")
        );
    }

    #[test]
    fn call_target_prefers_packages_and_does_not_confuse_legacy_wasm_hashes() {
        let mut found = BTreeMap::from([
            ("contracts".to_owned(), vec!["contract-entity".to_owned()]),
            (
                "contractWasms".to_owned(),
                vec!["contract-wasm-code".to_owned()],
            ),
        ]);
        let target = call_target(&found).unwrap();
        assert!(matches!(target.kind, CallTargetKind::Contract));
        assert_eq!(target.hash, "contract-entity");

        found.insert("packages".to_owned(), vec!["package-stable".to_owned()]);
        let target = call_target(&found).unwrap();
        assert!(matches!(target.kind, CallTargetKind::Package));
        assert_eq!(target.hash, "package-stable");
        assert_eq!(address_kind("contract-wasm-code"), Some("contractWasms"));
    }
}
