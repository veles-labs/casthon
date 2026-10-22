"""Build events stay separate from Python, native and descendant output."""

import json
from pathlib import Path
import subprocess
import sys
import unittest


SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"


class BuildProgressTests(unittest.TestCase):
    def run_probe(self, enabled):
        return subprocess.run([sys.executable, "-c", f'''
import os, subprocess, sys
sys.path.insert(0, {str(SCRIPTS)!r})
from build_progress import BuildProgress
progress = BuildProgress({enabled!r})
progress.start("Freezing modules", 2)
print("python stdout", flush=True)
os.write(1, b"native stdout\\n")
os.write(2, b"native stderr\\n")
subprocess.run([sys.executable, "-c", "import os; os.write(1, b'child stdout\\\\n'); os.write(2, b'child stderr\\\\n')"], check=True)
progress.advance()
progress.advance()
progress.start("Reusing artifacts")
progress.finish(cached=True)
'''], capture_output=True, text=True, check=True)

    def test_private_events_pipe_survives_native_and_descendant_stdout(self):
        result = self.run_probe(True)
        events = [json.loads(line) for line in result.stdout.splitlines()]
        self.assertTrue(all(event['casthon_build'] == 1 for event in events))
        self.assertEqual([event['event'] for event in events],
                         ['start', 'progress', 'progress', 'finish', 'start', 'finish'])
        self.assertEqual(events[0]['total'], 2)
        self.assertEqual([events[index]['completed'] for index in (1, 2)], [1, 2])
        self.assertTrue(events[-1]['cached'])
        for text in ('python stdout', 'native stdout', 'native stderr', 'child stdout', 'child stderr'):
            self.assertIn(text, result.stderr)

    def test_direct_worker_keeps_ordinary_stdout_and_stderr(self):
        result = self.run_probe(False)
        for text in ('python stdout', 'native stdout', 'child stdout'):
            self.assertIn(text, result.stdout)
        for text in ('native stderr', 'child stderr'):
            self.assertIn(text, result.stderr)
        self.assertNotIn('casthon_build', result.stdout + result.stderr)
