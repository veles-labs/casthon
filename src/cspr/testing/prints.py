"""Bounded capture of the launcher's print-FD lines, separate from node logs."""

from collections import deque
from dataclasses import dataclass
import re
import threading


@dataclass(frozen=True)
class ContractPrint:
    sequence: int
    node_id: int
    text: str


class _PrintCapture:
    def __init__(self, *, max_lines: int = 1000, max_chars: int = 262144) -> None:
        self._lines: deque[ContractPrint] = deque()
        self._condition = threading.Condition()
        self._sequence = self._chars = 0
        self._max_lines, self._max_chars = max_lines, max_chars
        self._closed = False

    @property
    def cursor(self) -> int:
        with self._condition:
            return self._sequence

    def feed(self, line: str) -> None:
        match = re.fullmatch(r"node-([1-9][0-9]*) casper_print: (.*)", line.removesuffix("\n"))
        if match is None:
            return
        text = match[2]
        limit = min(16384, self._max_chars)
        if len(text) > limit:
            text = text[:max(0, limit - 24)] + " [print line truncated]"
        with self._condition:
            self._sequence += 1
            self._lines.append(ContractPrint(self._sequence, int(match[1]), text))
            self._chars += len(text)
            while self._lines and (len(self._lines) > self._max_lines or self._chars > self._max_chars):
                self._chars -= len(self._lines.popleft().text)
            self._condition.notify_all()

    def snapshot(self, since: int = 0) -> tuple[ContractPrint, ...]:
        with self._condition:
            return tuple(line for line in self._lines if line.sequence > since)

    def wait(self, pattern: str, *, since: int = 0, node_id: int | None = None,
             timeout: float = 5) -> ContractPrint:
        if timeout <= 0:
            raise ValueError("Print timeout must be positive")
        expression = re.compile(pattern)
        def find() -> ContractPrint | None:
            return next((line for line in self._lines if line.sequence > since
                         and (node_id is None or line.node_id == node_id)
                         and expression.search(line.text)), None)
        with self._condition:
            self._condition.wait_for(lambda: find() is not None or self._closed, timeout)
            line = find()
            if line is None:
                raise TimeoutError(f"No contract print matching {pattern!r} after cursor {since}")
            return line

    def close(self) -> None:
        with self._condition:
            self._closed = True
            self._condition.notify_all()


def _print_note(lines: tuple[ContractPrint, ...], since: int = 0) -> str:
    if not lines:
        return ""
    selected = lines[-50:]
    omitted = max(0, selected[0].sequence - since - 1)
    body = "\n".join(f"node-{line.node_id}: {line.text}" for line in selected)
    if len(body) > 8192:
        body = "[earlier output truncated]\n" + body[-8192:]
    prefix = f"[{omitted} earlier lines omitted]\n" if omitted else ""
    return "Captured Casper prints (node stream; no transaction attribution):\n" + prefix + body
