"""Atomic streaming output and bounded, disk backed deduplication."""

import gzip
import json
import os
import sqlite3
import tempfile
from dataclasses import asdict
from pathlib import Path

from .model import Config


class StreamingOutput:
    def __init__(self, path: Path, config: Config):
        self.path = Path(path)
        self.config = config
        self.temporary = None
        self.database_path = None
        self.database = None
        self.stream = None
        self.raw = None
        self.buffer = []
        self.buffer_chars = 0
        self.written = 0

    def __enter__(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        try:
            descriptor, name = tempfile.mkstemp(prefix=self.path.name + ".", suffix=".partial",
                                              dir=self.path.parent)
            self.temporary = Path(name)
            try:
                raw = os.fdopen(descriptor, "wb", buffering=1024 * 1024)
            except Exception:
                os.close(descriptor)
                raise
            self.raw = raw
            if self.config.gzip_output:
                self.stream = gzip.GzipFile(filename="", mode="wb", fileobj=raw,
                                            compresslevel=3, mtime=0)
            else:
                self.stream = raw
            if self.config.deduplicate:
                descriptor, name = tempfile.mkstemp(prefix="wordlist-dedup-", suffix=".sqlite",
                                                  dir=self.path.parent)
                os.close(descriptor)
                self.database_path = Path(name)
                self.database = sqlite3.connect(name)
                self.database.execute("PRAGMA journal_mode=OFF")
                self.database.execute("PRAGMA synchronous=OFF")
                self.database.execute("CREATE TABLE seen (candidate TEXT PRIMARY KEY) WITHOUT ROWID")
                self.database.execute("BEGIN")
            return self
        except Exception:
            try:
                self.close()
            except Exception:
                pass  # Preserve the setup error after attempting every cleanup step.
            raise

    def write(self, candidate: str) -> bool:
        if self.database is not None:
            cursor = self.database.execute("INSERT OR IGNORE INTO seen VALUES (?)", (candidate,))
            if cursor.rowcount == 0:
                return False
        self.buffer.append(candidate)
        self.buffer_chars += len(candidate) + 1
        self.written += 1
        if self.buffer_chars >= 65536:
            self.flush()
        return True

    def flush(self):
        if self.buffer:
            self.stream.write(("\n".join(self.buffer) + "\n").encode("utf-8"))
            self.buffer.clear()
            self.buffer_chars = 0
        if self.database is not None:
            self.database.commit()
            self.database.execute("BEGIN")

    def finish(self) -> int:
        self.flush()
        try:
            self.stream.close()
        finally:
            if self.raw is not self.stream:
                self.raw.close()
        self.stream = None
        self.raw = None
        size = self.temporary.stat().st_size
        os.replace(self.temporary, self.path)
        self.temporary = None
        return size

    def close(self):
        errors = []
        resources = (self.stream, self.raw if self.raw is not self.stream else None,
                     self.database)
        self.stream = self.raw = self.database = None
        for resource in resources:
            if resource is not None:
                try:
                    resource.close()
                except Exception as exc:
                    errors.append(exc)
        for name in ("database_path", "temporary"):
            path = getattr(self, name)
            setattr(self, name, None)
            if path is not None:
                try:
                    path.unlink(missing_ok=True)
                except Exception as exc:
                    errors.append(exc)
        if errors:
            raise errors[0]

    def __exit__(self, exc_type, exc_value, traceback):
        if exc_type is None:
            self.close()
        else:
            try:
                self.close()
            except Exception:
                pass  # The generation error is more useful than a cleanup error.


def write_summary(path: Path, config: Config, statistics: dict) -> Path:
    """Create a sidecar JSON summary only after successful output commit."""
    sidecar = Path(str(path) + ".summary.json")
    descriptor, name = tempfile.mkstemp(prefix=sidecar.name + ".", dir=sidecar.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as output:
            json.dump({"settings": asdict(config), "statistics": statistics}, output,
                      indent=2, ensure_ascii=False)
            output.write("\n")
        os.replace(name, sidecar)
    finally:
        Path(name).unlink(missing_ok=True)
    return sidecar
