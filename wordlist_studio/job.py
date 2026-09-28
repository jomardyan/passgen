"""Cooperative pause and cancel controls, progress, and execution."""

import threading
import time
import queue
from collections import deque
from concurrent.futures import ProcessPoolExecutor, TimeoutError as FutureTimeout
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from .generator import candidates
from .model import Config, estimate, needs_deduplication
from .output import StreamingOutput, write_summary
from .parallel import generate_batch, tasks


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


class _OrderedWriter(threading.Thread):
    """Own the output stream while the job thread keeps CPU workers supplied."""

    def __init__(self, path, config, control, total, started, on_progress):
        super().__init__(name="wordlist-writer")
        self.path = path
        self.config = config
        self.control = control
        self.total = total
        self.started = started
        self.on_progress = on_progress
        self.batches = queue.Queue(maxsize=config.workers * 2)
        self.ready = threading.Event()
        self.input_done = threading.Event()
        self.stop_requested = threading.Event()
        self.error = None
        self.opened = False
        self.processed = 0
        self.written = 0
        self.size = 0

    def submit(self, batch):
        while True:
            if self.error is not None:
                raise self.error
            self.control.checkpoint()
            try:
                self.batches.put(batch, timeout=0.1)
                return
            except queue.Full:
                continue

    def run(self):
        output = None
        paused_seconds = 0.0
        last_update = self.started
        try:
            with StreamingOutput(self.path, self.config) as output:
                self.opened = True
                self.ready.set()
                while not self.stop_requested.is_set():
                    paused_seconds += self.control.checkpoint()
                    try:
                        count, batch = self.batches.get(timeout=0.1)
                    except queue.Empty:
                        if self.input_done.is_set():
                            break
                        continue
                    paused_seconds += self.control.checkpoint()
                    if needs_deduplication(self.config):
                        for candidate in batch:
                            output.write(candidate)
                    else:
                        output.write_batch(batch, count)
                    self.processed += count
                    self.written = output.written
                    now = time.monotonic()
                    if self.on_progress and (now - last_update >= 0.2 or
                                             self.processed == self.total):
                        active = max(now - self.started - paused_seconds, 0.000001)
                        eta = (self.total - self.processed) * active / self.processed
                        self.on_progress(Progress(self.processed, self.written, self.total,
                                                  now - self.started, eta))
                        last_update = now
                if not self.stop_requested.is_set():
                    self.control.checkpoint()
                    self.size = output.finish()
                self.written = output.written
        except Exception as exc:
            self.error = exc
            if not isinstance(exc, Cancelled):
                self.control.cancel()  # Wake a paused collector so it can report the writer error.
        finally:
            if output is not None:
                self.written = output.written
            self.ready.set()


def _parallel_run(config, path, control, total, started, on_progress):
    writer = _OrderedWriter(path, config, control, total, started, on_progress)
    writer.start()
    writer.ready.wait()
    if writer.error is not None:
        writer.join()
        if writer.opened:
            writer.error.output_path = str(path.resolve())
            writer.error.written = writer.written
        raise writer.error

    try:
        with ProcessPoolExecutor(max_workers=config.workers) as pool:
            work = iter(tasks(config))
            pending = deque()

            def submit_available():
                while len(pending) < config.workers * 2:
                    try:
                        task = next(work)
                    except StopIteration:
                        break
                    pending.append(pool.submit(generate_batch, task,
                                               not needs_deduplication(config)))

            submit_available()
            while pending:
                if writer.error is not None:
                    raise writer.error
                control.checkpoint()
                try:
                    batch = pending[0].result(timeout=0.1)
                except FutureTimeout:
                    continue
                control.checkpoint()
                pending.popleft()
                writer.submit(batch)
                submit_available()
        writer.input_done.set()
        writer.join()
        if writer.error is not None:
            raise writer.error
        return writer.processed, writer.written, writer.size
    except Exception as exc:
        writer.stop_requested.set()
        control.cancel()  # Wake a paused writer before joining it.
        writer.input_done.set()
        writer.join()
        if writer.error is not None and not isinstance(writer.error, Cancelled):
            exc = writer.error
        if writer.opened:
            exc.output_path = str(path.resolve())
            exc.written = writer.written
        raise exc


def run(config: Config, path: Path, control: JobControl | None = None,
        on_progress: Callable[[Progress], None] | None = None) -> dict:
    """Stream directly to the destination and retain partial output on interruption."""
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
    control.checkpoint()  # Do not replace an existing file if already canceled.
    if config.workers > 1:
        processed, written, size = _parallel_run(config, path, control, total, started,
                                                 on_progress)
    else:
        processed = 0
        last_update = started
        paused_seconds = 0.0
        opened = False
        output = None
        try:
            with StreamingOutput(path, config) as output:
                opened = True
                for candidate in candidates(config):
                    paused_seconds += control.checkpoint()
                    output.write(candidate)
                    processed += 1
                    now = time.monotonic()
                    if on_progress and (now - last_update >= 0.2 or processed == total):
                        active = max(now - started - paused_seconds, 0.000001)
                        eta = (total - processed) * active / processed
                        on_progress(Progress(processed, output.written, total,
                                             now - started, eta))
                        last_update = now
                control.checkpoint()
                size = output.finish()
                written = output.written
        except Exception as exc:
            if opened:
                exc.output_path = str(path.resolve())
                exc.written = output.written
            raise
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
