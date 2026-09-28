"""Cooperative pause and cancel controls, progress, and execution."""

import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from .generator import candidates
from .model import Config, estimate
from .output import StreamingOutput, write_summary


@dataclass(frozen=True)
class Progress:
    processed: int
    written: int
    total: int
    elapsed: float
    eta: float | None


class Cancelled(Exception):
    pass


class JobControl:
    def __init__(self):
        self._resume = threading.Event()
        self._resume.set()
        self._cancel = threading.Event()

    def pause(self):
        self._resume.clear()

    def resume(self):
        self._resume.set()

    def cancel(self):
        self._cancel.set()
        self._resume.set()

    def checkpoint(self):
        if self._cancel.is_set():
            raise Cancelled()
        paused = 0.0
        if not self._resume.is_set():
            began = time.monotonic()
            while not self._resume.wait(0.1):
                if self._cancel.is_set():
                    raise Cancelled()
            paused = time.monotonic() - began
        if self._cancel.is_set():
            raise Cancelled()
        return paused


def run(config: Config, path: Path, control: JobControl | None = None,
        on_progress: Callable[[Progress], None] | None = None) -> dict:
    """Generate into a temporary file and commit it on successful completion.

    Cancellation or any error removes temporary output and preserves an existing
    destination. All callbacks run in the caller's thread.
    """
    total = estimate(config)
    if total == 0:
        raise ValueError("No candidates match the selected length and rules.")
    path = Path(path)
    if config.gzip_output != (path.suffix.lower() == ".gz"):
        raise ValueError("Use a .gz filename for compressed output, or .txt for plain output.")
    if not config.gzip_output and path.suffix.lower() != ".txt":
        raise ValueError("Plain output must use a .txt filename.")
    control = control or JobControl()
    started = time.monotonic()
    processed = 0
    last_update = started
    paused_seconds = 0.0
    with StreamingOutput(path, config) as output:
        for candidate in candidates(config):
            paused_seconds += control.checkpoint()
            now = time.monotonic()
            processed += 1
            output.write(candidate)
            if on_progress and (now - last_update >= 0.2 or processed == total):
                active = max(now - started - paused_seconds, 0.000001)
                eta = (total - processed) * active / processed
                on_progress(Progress(processed, output.written, total, now - started, eta))
                last_update = now
        control.checkpoint()
        size = output.finish()
        written = output.written
    duration = time.monotonic() - started
    summary = {"processed": processed, "total_entries": written, "file_size_bytes": size,
               "seconds": round(duration, 3),
               "finished_at_utc": datetime.now(timezone.utc).isoformat(),
               "output": str(path.resolve())}
    try:
        write_summary(path, config, summary)
    except OSError as exc:
        # The wordlist is already committed. Report the log failure separately.
        summary["summary_error"] = str(exc)
    return summary
