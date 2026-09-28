"""Reproducible throughput benchmark. Run from the repository root."""

import argparse
import platform
import tempfile
from pathlib import Path

from wordlist_studio.job import run
from wordlist_studio.model import Config


def _worker_counts(value):
    try:
        counts = tuple(dict.fromkeys(int(part.strip()) for part in value.split(",")))
    except ValueError as exc:
        raise argparse.ArgumentTypeError("Use comma-separated worker counts, such as 1,4.") from exc
    if not counts or any(not 1 <= count <= 32 for count in counts):
        raise argparse.ArgumentTypeError("Worker counts must be between 1 and 32.")
    return counts


def _print_table(rows):
    headers = ("Mode", "Workers", "Processed", "Written", "Time (s)",
               "Candidates/s", "Size (bytes)", "Speedup")
    widths = [max(len(header), *(len(row[index]) for row in rows))
              for index, header in enumerate(headers)]
    border = "+-" + "-+-".join("-" * width for width in widths) + "-+"

    def line(values):
        cells = [value.ljust(width) if index == 0 else value.rjust(width)
                 for index, (value, width) in enumerate(zip(values, widths))]
        return "| " + " | ".join(cells) + " |"

    print(border)
    print(line(headers))
    print(border)
    for row in rows:
        print(line(row))
    print(border)


def main(argv=None, prog="python -m benchmarks.benchmark"):
    parser = argparse.ArgumentParser(prog=prog, description=__doc__)
    parser.add_argument("--workers", type=_worker_counts, default=(1,), metavar="1,4",
                        help="one or more worker counts to compare (default: 1)")
    parser.add_argument("--length", type=int, default=6, help="candidate length (default: 6)")
    parser.add_argument("--alphabet", default="abcdefghij",
                        help="characters to enumerate (default: abcdefghij)")
    parser.add_argument("--compression", choices=("both", "plain", "gzip"), default="both")
    parser.add_argument("--deduplicate", action="store_true",
                        help="request deduplication (skipped for unique exhaustive output)")
    args = parser.parse_args(argv)
    if not 1 <= args.length <= 32:
        parser.error("--length must be between 1 and 32")
    if not args.alphabet or any(char in "\r\n" for char in args.alphabet):
        parser.error("--alphabet must contain characters without line breaks")
    modes = (False, True) if args.compression == "both" else (args.compression == "gzip",)
    rows = []
    with tempfile.TemporaryDirectory() as folder:
        for compressed in modes:
            baseline = None
            for workers in args.workers:
                config = Config(min_length=args.length, max_length=args.length,
                                lowercase=False, digits=False, extra_chars=args.alphabet,
                                workers=workers, gzip_output=compressed,
                                deduplicate=args.deduplicate)
                path = Path(folder) / ("benchmark.txt.gz" if compressed else "benchmark.txt")
                summary = run(config, path)
                seconds = max(summary["seconds"], 0.001)
                baseline = seconds if baseline is None else baseline
                rate = summary["processed"] / seconds
                speedup = baseline / seconds
                speedup_text = (f"{speedup:.2f}x" if speedup >= 0.01
                                else f"{speedup:.2g}x")
                rows.append(("Gzip" if compressed else "Plain", str(workers),
                             f"{summary['processed']:,}", f"{summary['total_entries']:,}",
                             f"{summary['seconds']:.3f}", f"{rate:,.0f}",
                             f"{summary['file_size_bytes']:,}", speedup_text))
    print("Wordlist Studio benchmark")
    print(f"Python {platform.python_version()} | {platform.platform()}")
    dedup_state = "skipped (exhaustive output is unique)" if args.deduplicate else "off"
    print(f"Workload: length {args.length}, alphabet {len(set(args.alphabet))} characters, "
          f"{len(set(args.alphabet)) ** args.length:,} candidates, "
          f"disk deduplication {dedup_state}")
    baseline_label = "worker" if args.workers[0] == 1 else "workers"
    print(f"Speedup is relative to {args.workers[0]} {baseline_label} within each mode. "
          "One run per row.\n")
    _print_table(rows)
    return 0


if __name__ == "__main__":
    main()
