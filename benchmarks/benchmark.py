"""Reproducible throughput benchmark. Run from the repository root."""

import platform
import tempfile
from pathlib import Path

from wordlist_studio.job import run
from wordlist_studio.model import Config


def main():
    config = Config(min_length=6, max_length=6, lowercase=False, digits=False,
                    extra_chars="abcdefghij")
    print(f"Python {platform.python_version()} on {platform.platform()}")
    with tempfile.TemporaryDirectory() as folder:
        for compressed in (False, True):
            current = Config(**{**config.__dict__, "gzip_output": compressed})
            path = Path(folder) / ("benchmark.txt.gz" if compressed else "benchmark.txt")
            summary = run(current, path)
            rate = summary["processed"] / max(summary["seconds"], 0.001)
            print(f"gzip={compressed} entries={summary['total_entries']:,} "
                  f"size={summary['file_size_bytes']:,} bytes "
                  f"seconds={summary['seconds']:.3f} rate={rate:,.0f} candidates/s")


if __name__ == "__main__":
    main()
