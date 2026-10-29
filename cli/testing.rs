use anyhow::{Context, Result};
use clap::Args;
use std::ffi::OsString;
use std::path::Path;

use crate::Project;

#[derive(Args)]
pub struct Test {
    /// Enable live network tests and default collection to tests/live.
    #[arg(long, conflicts_with = "wasm")]
    live: bool,
    /// Default collection to tests/wasm (build its artifacts first).
    #[arg(long)]
    wasm: bool,
    /// Arguments passed unchanged to python -m pytest after --.
    #[arg(last = true, value_name = "PYTEST_ARGS", allow_hyphen_values = true)]
    args: Vec<OsString>,
}

pub fn run(project: &Project, casper_cli: &Path, options: Test) -> Result<i32> {
    let mut command = project.command()?;
    if casper_cli != Path::new("casper-cli") {
        command.env("CSPR_CASPER_CLI_BIN", casper_cli);
    }
    command.args(["-m", "pytest"]);
    // Let pytest parse paths and selectors: explicit paths override testpaths,
    // while flags such as -q and -k retain the selected default collection.
    if options.live {
        command.env("CSPR_LIVE_TESTS", "1");
        command.args(["-o", "testpaths=tests/live"]);
    } else if options.wasm {
        command.args(["-o", "testpaths=tests/wasm"]);
    }
    Ok(command
        .args(options.args)
        .status()
        .with_context(|| format!("Could not run {} -m pytest", project.python.display()))?
        .code()
        .unwrap_or(1))
}
