use anyhow::{Context, Result};
use console::{Term, strip_ansi_codes, truncate_str};
use indicatif::{MultiProgress, ProgressBar, ProgressStyle};
use serde::Deserialize;
use std::{
    collections::VecDeque,
    fs::File,
    io::{self, BufRead, BufReader, BufWriter, IsTerminal, Read, Write},
    path::Path,
    process::{Command, Stdio},
    sync::mpsc::{self, RecvTimeoutError},
    thread,
    time::Duration,
};

const LOG_LINES: usize = 4;

#[derive(Deserialize)]
struct WorkerEvent {
    casthon_build: u8,
    #[serde(flatten)]
    event: Event,
}

#[derive(Deserialize)]
#[serde(tag = "event", rename_all = "snake_case")]
enum Event {
    Start {
        name: String,
        total: Option<u64>,
    },
    Progress {
        completed: u64,
        total: Option<u64>,
    },
    Finish {
        #[serde(default)]
        cached: bool,
    },
}

pub struct BuildOutput {
    terminal: Option<MultiProgress>,
    heading: Option<ProgressBar>,
    logs: Option<ProgressBar>,
    active: Option<ProgressBar>,
    name: String,
    step: usize,
    tail: VecDeque<String>,
    transcript: BufWriter<File>,
    log_path: String,
    plain_steps: bool,
    finished: bool,
}

fn style(template: &str) -> ProgressStyle {
    ProgressStyle::with_template(template).expect("valid built-in progress template")
}

fn clean(line: &str) -> String {
    strip_ansi_codes(line)
        .chars()
        .filter(|c| !c.is_control() || *c == '\t')
        .collect::<String>()
        .replace('\t', "    ")
}

impl BuildOutput {
    pub fn new(source: &Path, log: &Path, machine: bool, no_progress: bool) -> Result<Self> {
        let transcript = BufWriter::new(File::create(log).context("Cannot create build log")?);
        let interactive = !machine
            && !no_progress
            && io::stderr().is_terminal()
            && std::env::var("TERM").as_deref() != Ok("dumb");
        let terminal = interactive.then(MultiProgress::new);
        let heading = terminal.as_ref().map(|term| {
            let bar = ProgressBar::hidden();
            bar.set_style(style("{wide_msg:.bold}"));
            bar.set_message(format!("Building {}", source.display()));
            term.add(bar)
        });
        let logs = terminal.as_ref().map(|term| {
            let bar = ProgressBar::hidden();
            bar.set_style(style("{msg:.dim}"));
            term.add(bar)
        });
        let output = Self {
            terminal,
            heading,
            logs,
            active: None,
            name: String::new(),
            step: 0,
            tail: VecDeque::with_capacity(LOG_LINES),
            transcript,
            log_path: log.display().to_string(),
            plain_steps: !machine && !no_progress,
            finished: false,
        };
        output.tick();
        Ok(output)
    }

    pub fn start(&mut self, name: &str, total: Option<u64>) -> Result<()> {
        self.complete(false);
        self.step += 1;
        self.name = clean(name);
        writeln!(self.transcript, "{}. {}", self.step, self.name)?;
        if let Some(term) = &self.terminal {
            let bar = ProgressBar::hidden();
            bar.set_prefix(self.step.to_string());
            bar.set_message(self.name.clone());
            let frames: Vec<String> = (0..24)
                .map(|tick| {
                    let position = if tick < 12 { tick } else { 23 - tick };
                    (0..16)
                        .map(|i| {
                            if (position..position + 4).contains(&i) {
                                '━'
                            } else {
                                '─'
                            }
                        })
                        .collect()
                })
                .collect();
            let frames: Vec<&str> = frames.iter().map(String::as_str).collect();
            bar.set_style(
                style("{prefix:>2}. {wide_msg} [{spinner:.cyan}] {elapsed_precise}")
                    .tick_strings(&frames),
            );
            self.active = Some(term.insert_before(self.logs.as_ref().unwrap(), bar));
            if let Some(total) = total {
                self.update(0, Some(total));
            }
        } else if self.plain_steps {
            eprintln!("{}. {}...", self.step, self.name);
        }
        self.tick();
        Ok(())
    }

    fn update(&self, completed: u64, total: Option<u64>) {
        if let Some(bar) = &self.active {
            if let Some(total) = total {
                bar.set_length(total.max(1));
                bar.set_style(
                    style("{prefix:>2}. {wide_msg} [{bar:16.cyan/blue}] {pos}/{len}")
                        .progress_chars("━╸─"),
                );
            }
            bar.set_position(completed.min(bar.length().unwrap_or(u64::MAX)));
        }
    }

    fn complete(&mut self, cached: bool) {
        if let Some(bar) = self.active.take() {
            bar.set_length(1);
            bar.set_position(1);
            let suffix = if cached { "cached" } else { "done" };
            bar.set_style(
                style(&format!(
                    "{{prefix:>2}}. {{wide_msg}} [{{bar:16.green/green}}] {suffix}"
                ))
                .progress_chars("━╸─"),
            );
            bar.finish_with_message(self.name.clone());
        }
    }

    fn event(&mut self, line: &str) -> Result<bool> {
        let Ok(event) = serde_json::from_str::<WorkerEvent>(line) else {
            return Ok(false);
        };
        if event.casthon_build != 1 {
            return Ok(false);
        }
        match event.event {
            Event::Start { name, total } => self.start(&name, total)?,
            Event::Progress { completed, total } => self.update(completed, total),
            Event::Finish { cached } => self.complete(cached),
        }
        Ok(true)
    }

    fn log(&mut self, bytes: &[u8]) -> Result<()> {
        self.transcript.write_all(bytes)?;
        let text = String::from_utf8_lossy(bytes);
        if self.terminal.is_none() {
            io::stderr().lock().write_all(bytes)?;
        } else {
            // A child cannot move the cursor or wrap a long diagnostic into
            // the fixed progress rows. Keep all unmodified bytes in the log.
            let line = clean(text.trim_end_matches(['\r', '\n']));
            if !line.is_empty() {
                if self.tail.len() == LOG_LINES {
                    self.tail.pop_front();
                }
                self.tail.push_back(line);
            }
        }
        Ok(())
    }

    fn tick(&self) {
        if let Some(bar) = &self.active {
            bar.tick();
        }
        if let Some(bar) = &self.logs {
            let width = usize::from(Term::stderr().size().1).saturating_sub(4);
            let mut lines = vec!["  │".to_owned(); LOG_LINES.saturating_sub(self.tail.len())];
            lines.extend(
                self.tail
                    .iter()
                    .map(|line| format!("  │ {}", truncate_str(line, width, "…"))),
            );
            bar.set_message(lines.join("\n"));
        }
    }

    pub fn finish(&mut self, success: bool) -> Result<()> {
        if self.finished {
            return Ok(());
        }
        self.finished = true;
        if success {
            self.complete(false);
        } else if let Some(bar) = self.active.take() {
            bar.set_style(
                style("{prefix:>2}. {wide_msg} [{bar:16.red/red}] failed").progress_chars("━╸─"),
            );
            bar.abandon_with_message(self.name.clone());
        }
        self.tick();
        for bar in [&self.heading, &self.logs].into_iter().flatten() {
            bar.finish();
        }
        self.transcript.flush()?;
        if !success {
            eprintln!("Build log: {}", self.log_path);
        }
        Ok(())
    }
}

impl Drop for BuildOutput {
    fn drop(&mut self) {
        let _ = self.finish(false);
    }
}

pub fn run_worker(command: &mut Command, output: &mut BuildOutput) -> Result<i32> {
    let mut child = command
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .spawn()
        .context("Could not start the Python build worker")?;
    let (sender, receiver) = mpsc::sync_channel(128);
    let readers: Vec<_> = [
        (
            true,
            Box::new(child.stdout.take().unwrap()) as Box<dyn Read + Send>,
        ),
        (
            false,
            Box::new(child.stderr.take().unwrap()) as Box<dyn Read + Send>,
        ),
    ]
    .into_iter()
    .map(|(events, pipe)| {
        let sender = sender.clone();
        thread::spawn(move || -> io::Result<()> {
            let mut reader = BufReader::new(pipe);
            loop {
                let mut line = Vec::new();
                if reader.read_until(b'\n', &mut line)? == 0 {
                    return Ok(());
                }
                if sender.send((events, line)).is_err() {
                    return Ok(());
                }
            }
        })
    })
    .collect();
    drop(sender);
    let result = (|| {
        loop {
            match receiver.recv_timeout(Duration::from_millis(80)) {
                Ok((events, line)) => {
                    if !events || !output.event(&String::from_utf8_lossy(&line))? {
                        output.log(&line)?;
                    }
                }
                Err(RecvTimeoutError::Timeout) => {}
                Err(RecvTimeoutError::Disconnected) => break,
            }
            output.tick();
        }
        for reader in readers {
            reader
                .join()
                .map_err(|_| anyhow::anyhow!("Build output reader panicked"))??;
        }
        Ok(child.wait()?.code().unwrap_or(1))
    })();
    if result.is_err() {
        let _ = child.kill();
        let _ = child.wait();
    }
    result
}

#[cfg(test)]
mod tests {
    use super::*;
    use indicatif::ProgressDrawTarget;

    #[test]
    fn log_pane_is_bounded_sanitized_and_keeps_the_full_transcript() {
        let temporary = tempfile::tempdir().unwrap();
        let log = temporary.path().join("build.log");
        let mut output = BuildOutput::new(Path::new("token.py"), &log, true, false).unwrap();
        let terminal = MultiProgress::with_draw_target(ProgressDrawTarget::hidden());
        output.logs = Some(terminal.add(ProgressBar::new_spinner()));
        output.terminal = Some(terminal);
        for index in 0..40 {
            output
                .log(format!("\x1b[2J\x1b[31mline {index}\x1b[0m\n").as_bytes())
                .unwrap();
        }
        output.tick();
        assert_eq!(output.tail.len(), LOG_LINES);
        assert_eq!(output.tail.front().unwrap(), "line 36");
        let pane = output.logs.as_ref().unwrap().message();
        assert_eq!(pane.lines().count(), LOG_LINES);
        assert!(pane.contains("line 39"));
        assert!(!pane.contains('\x1b'));
        output.finish(true).unwrap();
        let transcript = std::fs::read_to_string(log).unwrap();
        assert!(transcript.contains("line 0"));
        assert!(transcript.contains("line 39"));
    }

    #[test]
    fn progress_events_drive_real_units_and_do_not_consume_ordinary_json() {
        let temporary = tempfile::tempdir().unwrap();
        let mut output = BuildOutput::new(
            Path::new("token.py"),
            &temporary.path().join("build.log"),
            true,
            false,
        )
        .unwrap();
        let terminal = MultiProgress::with_draw_target(ProgressDrawTarget::hidden());
        output.logs = Some(terminal.add(ProgressBar::new_spinner()));
        output.terminal = Some(terminal);
        assert!(
            !output
                .event(r#"{"message":"normal compiler output"}"#)
                .unwrap()
        );
        assert!(
            output
                .event(r#"{"casthon_build":1,"event":"start","name":"Freeze modules","total":10}"#)
                .unwrap()
        );
        output
            .event(r#"{"casthon_build":1,"event":"progress","completed":4}"#)
            .unwrap();
        assert_eq!(output.active.as_ref().unwrap().position(), 4);
        assert_eq!(output.active.as_ref().unwrap().length(), Some(10));
        output
            .event(r#"{"casthon_build":1,"event":"start","name":"Compile runtime"}"#)
            .unwrap();
        assert_eq!(output.step, 2);
        assert_eq!(output.active.as_ref().unwrap().length(), None);
        output.finish(false).unwrap();
        assert!(output.active.is_none());
    }
}
