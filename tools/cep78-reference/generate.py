#!/usr/bin/env python3
"""Generate independent fixtures from a verified upstream CEP-78 checkout."""
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
COMMIT = '9a624aa9a4f5cba59260f93652b76948e528c7f2'
upstream = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / '.cache/cep78-upstream'
revision = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=upstream, text=True).strip()
if revision != COMMIT:
    raise SystemExit('Expected upstream commit ' + COMMIT + ', got ' + revision)
work = ROOT / '.cache/cep78-reference'
source = work / 'src'
source.mkdir(parents=True, exist_ok=True)
rust = upstream / 'contracts/contract/src'
shutil.copyfile(rust / 'constants.rs', source / 'constants.rs')
main = (rust / 'main.rs').read_text()
entrypoints = main[main.index('fn generate_entry_points()'):main.index('fn install_contract()')]
(source / 'entry_points.rs').write_text(entrypoints)
events = (rust / 'events/events_ces.rs').read_text()
records = re.findall(r'#\[derive\([^\n]+\)\]\npub struct \w+ \{[^}]*\}', events)
assert len(records) == 10
(source / 'events.rs').write_text('use casper_event_standard::Event;\nuse serde::{Serialize, Deserialize};\nuse casper_types::Key;\n' + '\n'.join(records))
metadata = (rust / 'metadata.rs').read_text()
records = re.findall(r'#\[derive\(Serialize, Deserialize\)\]\npub\(crate\) struct Metadata(?:NFT721|CEP78) \{[^}]*\}', metadata)
assert len(records) == 2
(source / 'metadata.rs').write_text('use serde::{Serialize, Deserialize};\n' + '\n'.join(records))
shutil.copyfile(Path(__file__).with_name('main.rs'), source / 'main.rs')
(work / 'Cargo.toml').write_text('''[package]
name = "cep78-reference"
version = "0.1.0"
edition = "2024"
[dependencies]
casper-types = { version = "=6.1.0", default-features = false }
casper-event-standard = { version = "=0.7.0", default-features = false }
serde = { version = "=1.0.229", features = ["derive"] }
serde_json = "=1.0.154"
hex = "=0.4.3"
''')
output = subprocess.check_output(['cargo', 'run', '--quiet', '--offline', '--manifest-path', str(work / 'Cargo.toml')], cwd=ROOT, text=True)
# Parse before replacing the checked-in fixture file.
json.loads(output)
(ROOT / 'reference/cep78/fixtures.json').write_text(output)
print('Wrote reference/cep78/fixtures.json')
