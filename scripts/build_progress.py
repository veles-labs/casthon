"""Private build events on stdout, with compiler output kept on stderr."""

import json
import os
import sys


class BuildProgress:
    def __init__(self, enabled=False):
        self.stream = None
        self.active = False
        self.completed = 0
        if enabled:
            sys.stdout.flush()
            sys.stderr.flush()
            # Keep a private pipe for events. Descendants inherit stdout and
            # stderr pointing at the log pipe, including subprocesses in helpers.
            self.stream = os.fdopen(os.dup(sys.stdout.fileno()), "w", encoding="utf8", buffering=1)
            os.dup2(sys.stderr.fileno(), sys.stdout.fileno())

    def emit(self, event, **fields):
        if self.stream is not None:
            print(json.dumps({"casthon_build": 1, "event": event, **fields}),
                  file=self.stream, flush=True)

    def start(self, name, total=None):
        self.finish()
        self.active = True
        self.completed = 0
        self.emit("start", name=name, total=total)

    def update(self, completed, total=None):
        self.completed = completed
        self.emit("progress", completed=completed, total=total)

    def advance(self):
        self.update(self.completed + 1)

    def finish(self, cached=False):
        if self.active:
            self.emit("finish", cached=cached)
            self.active = False
