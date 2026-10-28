use anyhow::Result;
use clap::{ArgAction, Args, ValueEnum};
use serde::Serialize;
use serde_json::Value;
use std::path::PathBuf;

fn format_gas_cspr(gas: &Value) -> String {
    let raw = gas
        .as_str()
        .map(str::to_owned)
        .unwrap_or_else(|| gas.to_string());
    if raw.is_empty() || !raw.bytes().all(|byte| byte.is_ascii_digit()) {
        return raw;
    }
    // Shift the decimal point without floating-point rounding or integer limits.
    let digits = raw.trim_start_matches('0');
    let padded = format!("{digits:0>10}");
    let (whole, fractional) = padded.split_at(padded.len() - 9);
    format!("{whole}.{fractional} CSPR")
}

#[derive(Clone, Copy, Default, ValueEnum)]
pub enum Format {
    #[default]
    Text,
    Json,
}

#[derive(Clone, Copy, PartialEq, PartialOrd)]
pub enum Verbosity {
    Quiet,
    Normal,
    Verbose,
    Debug,
}

#[derive(Args, Clone, Copy, Default)]
pub struct OutputOptions {
    /// Result format; JSON emits one result object on stdout, including on failure.
    #[arg(long, value_enum, default_value = "text", conflicts_with = "json")]
    format: Format,
    /// Shorthand for --format json.
    #[arg(long, conflicts_with = "format")]
    json: bool,
    /// Show workflow progress; repeat (-vv) for commands and backend diagnostics.
    #[arg(short, long, action = ArgAction::Count, conflicts_with = "quiet")]
    verbose: u8,
    /// Print only the result, without headings or progress.
    #[arg(short, long, conflicts_with = "verbose")]
    quiet: bool,
}

impl OutputOptions {
    pub fn is_json(self) -> bool {
        self.json || matches!(self.format, Format::Json)
    }

    pub fn verbosity(self) -> Verbosity {
        match (self.quiet, self.verbose) {
            (true, _) => Verbosity::Quiet,
            (_, 2..) => Verbosity::Debug,
            (_, 1) => Verbosity::Verbose,
            _ if self.is_json() => Verbosity::Quiet,
            _ => Verbosity::Normal,
        }
    }

    pub fn finish(self, mut report: CommandResult, outcome: Result<i32>) -> Result<i32> {
        let code = match outcome {
            Ok(code) => code,
            Err(error) => {
                report.error = Some(format!("{error:#}"));
                1
            }
        };
        report.exit_code = code;
        report.success = code == 0;
        if code != 0 {
            report.status = "failed".to_owned();
            report
                .error
                .get_or_insert_with(|| format!("Command exited with status {code}"));
        }
        if self.is_json() {
            println!("{}", serde_json::to_string(&report)?);
        } else if let Some(error) = &report.error {
            eprintln!("error: {error}");
        } else {
            report.print_text(self.quiet);
        }
        Ok(code)
    }
}

#[derive(Clone, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct CommandResult {
    schema_version: u8,
    success: bool,
    pub command: &'static str,
    pub deployment: Option<String>,
    pub entry_point: Option<String>,
    pub network: Option<String>,
    pub mode: &'static str,
    pub status: String,
    pub transaction_hash: Option<String>,
    pub block_height: Option<u64>,
    pub gas_consumed: Option<Value>,
    pub return_value: Option<Value>,
    pub manifest: Option<PathBuf>,
    pub result: Option<Value>,
    pub error: Option<String>,
    exit_code: i32,
}

impl CommandResult {
    pub fn new(command: &'static str, broadcast: bool, simulate: bool) -> Self {
        Self {
            schema_version: 1,
            success: false,
            command,
            deployment: None,
            entry_point: None,
            network: None,
            mode: if broadcast {
                "broadcast"
            } else if simulate {
                "simulation"
            } else {
                "speculative"
            },
            status: "pending".to_owned(),
            transaction_hash: None,
            block_height: None,
            gas_consumed: None,
            return_value: None,
            manifest: None,
            result: None,
            error: None,
            exit_code: 0,
        }
    }

    pub fn preview(&mut self, result: Value) {
        self.block_height = result.get("blockHeight").and_then(Value::as_u64);
        self.gas_consumed = result
            .get("gasConsumed")
            .or_else(|| result.pointer("/execution_result/consumed"))
            .cloned();
        self.return_value = result
            .get("returnValue")
            .filter(|value| !value.is_null())
            .cloned();
        self.status = if self.mode == "simulation" {
            "simulated"
        } else {
            "speculated"
        }
        .to_owned();
        self.result = Some(result);
    }

    fn print_text(&self, quiet: bool) {
        if let Some(value) = &self.return_value {
            if value.get("cl_type").and_then(Value::as_str) != Some("Unit") {
                let parsed = value.get("parsed").unwrap_or(value);
                let rendered = parsed
                    .as_str()
                    .map(str::to_owned)
                    .unwrap_or_else(|| parsed.to_string());
                if quiet {
                    println!("{rendered}");
                } else {
                    let cl_type = value
                        .get("cl_type")
                        .map(|v| {
                            v.as_str()
                                .map(str::to_owned)
                                .unwrap_or_else(|| v.to_string())
                        })
                        .unwrap_or_else(|| "value".to_owned());
                    println!("Return {cl_type}: {rendered}");
                }
            } else {
                println!("Execution succeeded.");
            }
        } else if self.status == "executed" {
            println!(
                "Executed in block {}",
                self.block_height
                    .map_or_else(|| "unknown".to_owned(), |height| height.to_string())
            );
        } else if self.status == "submitted" {
            println!(
                "Submitted {}",
                self.transaction_hash.as_deref().unwrap_or("unknown")
            );
        } else {
            println!("Execution succeeded.");
        }
        if !quiet {
            if let Some(hash) = &self.transaction_hash
                && self.status != "submitted"
            {
                println!("Transaction: {hash}");
            }
            if let Some(gas) = &self.gas_consumed {
                println!("Gas consumed: {}", format_gas_cspr(gas));
            }
            if let Some(path) = &self.manifest
                && self.command == "deploy"
            {
                println!("Recorded {}", path.display());
            }
        }
    }
}

#[cfg(test)]
mod tests {
    use super::format_gas_cspr;
    use serde_json::json;

    #[test]
    fn gas_display_preserves_nine_decimal_places_for_small_and_large_amounts() {
        for (gas, expected) in [
            (json!("0"), "0.000000000 CSPR"),
            (json!(1), "0.000000001 CSPR"),
            (json!("999999999"), "0.999999999 CSPR"),
            (json!("1000000000"), "1.000000000 CSPR"),
            (json!("19250329205"), "19.250329205 CSPR"),
            (json!(u64::MAX), "18446744073.709551615 CSPR"),
            (
                json!("1000000000000000000000000001"),
                "1000000000000000000.000000001 CSPR",
            ),
        ] {
            assert_eq!(format_gas_cspr(&gas), expected);
        }
    }
}
