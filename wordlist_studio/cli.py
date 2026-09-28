"""Command-line entry points for generation and benchmarking."""

import argparse
import os
import signal
import sys
from pathlib import Path

from .display import estimated_file_size, format_duration, planning_rate
from .job import Cancelled, JobControl, run
from .model import Config, estimate_output


def _file_lines(path):
    if path is None:
        return ()
    return tuple(line.strip() for line in Path(path).read_text(encoding="utf-8").splitlines()
                 if line.strip())


def _unique(values):
    return tuple(dict.fromkeys(values))


def _substitutions(values):
    result = []
    for item in values:
        if "=" not in item:
            raise ValueError(f"Invalid substitution {item!r}; use a=@.")
        source, target = item.split("=", 1)
        if len(source) != 1 or len(target) != 1:
            raise ValueError(f"Invalid substitution {item!r}; use one character on each side.")
        result.append((source, target))
    return _unique(result)


def _generate(args):
    path = Path(args.output).expanduser()
    try:
        config = Config(
            mode=args.mode, min_length=args.min_length,
            max_length=args.max_length if args.max_length is not None else args.min_length,
            lowercase=args.lowercase, uppercase=args.uppercase, digits=args.digits,
            symbols=args.symbols, extra_chars=args.extra_chars,
            exclude_chars=args.exclude_chars,
            words=_unique((*args.word, *_file_lines(args.words_file))),
            combine_words=args.combine_words,
            substitutions=_substitutions((*args.substitution,
                                           *_file_lines(args.substitutions_file))),
            prefixes=_unique((*args.prefix, *_file_lines(args.prefixes_file))),
            suffixes=_unique((*args.suffix, *_file_lines(args.suffixes_file))),
            case_variants=args.case_variants, deduplicate=args.deduplicate,
            gzip_output=args.gzip or path.suffix.lower() == ".gz", workers=args.workers)
        result = estimate_output(config)
        if not result.candidates:
            raise ValueError("No candidates match the selected settings.")
        if config.gzip_output and path.suffix.lower() != ".gz":
            raise ValueError("Compressed output needs a .gz filename.")
        if not config.gzip_output and path.suffix.lower() != ".txt":
            raise ValueError("Plain output needs a .txt filename.")
    except (OSError, ValueError) as exc:
        print(f"Configuration error: {exc}", file=sys.stderr)
        return 2

    rate = planning_rate(config)
    seconds = (result.candidates + rate - 1) // rate
    print(f"Candidates before deduplication: {result.candidates:,}")
    print(f"Estimated time: {format_duration(seconds)} at {rate:,} candidates/s")
    print(f"Estimated final file size: {estimated_file_size(config, result)}")
    if args.dry_run:
        return 0
    if path.exists() and not args.force:
        print(f"Output exists: {path}. Use --force to overwrite it.", file=sys.stderr)
        return 2

    control = JobControl()
    previous_handler = signal.getsignal(signal.SIGINT)

    def cancel_from_keyboard(_signal_number, _frame):
        control.cancel()
        print("\nCanceling; partial output will be kept...", file=sys.stderr)

    def progress(value):
        if not args.quiet:
            print(f"Processed {value.processed:,}/{value.total:,}; "
                  f"written {value.written:,}; ETA {value.eta:.0f}s", file=sys.stderr)

    signal.signal(signal.SIGINT, cancel_from_keyboard)
    try:
        summary = run(config, path, control, progress)
    except Cancelled as exc:
        saved = getattr(exc, "output_path", None)
        print(f"Canceled. Partial output saved to {saved}." if saved else
              "Canceled before output was created.", file=sys.stderr)
        return 130
    except Exception as exc:
        saved = getattr(exc, "output_path", None)
        print(f"Generation failed: {exc}", file=sys.stderr)
        if saved:
            print(f"Partial output saved to {saved}.", file=sys.stderr)
        return 1
    finally:
        signal.signal(signal.SIGINT, previous_handler)

    print(f"Saved {summary['total_entries']:,} entries "
          f"({summary['file_size_bytes']:,} bytes) to {summary['output']} "
          f"in {summary['seconds']:.3f}s")
    if "summary_error" in summary:
        print(f"Summary log failed: {summary['summary_error']}", file=sys.stderr)
    return 0


def _parser():
    parser = argparse.ArgumentParser(prog="python -m wordlist_studio",
                                     description="Wordlist Studio for authorized password audits")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("gui", help="open the desktop interface")
    commands.add_parser("benchmark", help="measure one or more worker counts")
    generate = commands.add_parser("generate", help="generate a wordlist from the terminal")
    generate.add_argument("--output", required=True, help="destination .txt or .gz file")
    generate.add_argument("--mode", choices=("exhaustive", "rules"), default="exhaustive")
    generate.add_argument("--min-length", type=int, default=4)
    generate.add_argument("--max-length", type=int)
    generate.add_argument("--lowercase", action=argparse.BooleanOptionalAction, default=True)
    generate.add_argument("--uppercase", action="store_true")
    generate.add_argument("--digits", action=argparse.BooleanOptionalAction, default=True)
    generate.add_argument("--symbols", action="store_true")
    generate.add_argument("--extra-chars", default="")
    generate.add_argument("--exclude-chars", default="")
    generate.add_argument("--word", action="append", default=[], help="base word; repeat as needed")
    generate.add_argument("--words-file", help="UTF-8 file with one base word per line")
    generate.add_argument("--combine-words", action="store_true")
    generate.add_argument("--substitution", action="append", default=[], help="mapping such as a=@")
    generate.add_argument("--substitutions-file", help="UTF-8 file with one mapping per line")
    generate.add_argument("--prefix", action="append", default=[])
    generate.add_argument("--prefixes-file", help="UTF-8 file with one prefix per line")
    generate.add_argument("--suffix", action="append", default=[])
    generate.add_argument("--suffixes-file", help="UTF-8 file with one suffix per line")
    generate.add_argument("--case-variants", action="store_true")
    generate.add_argument("--deduplicate", action="store_true")
    generate.add_argument("--gzip", action="store_true", help="compress output; also inferred from .gz")
    generate.add_argument("--workers", type=int, default=min(os.cpu_count() or 1, 8))
    generate.add_argument("--dry-run", action="store_true", help="print estimates without writing")
    generate.add_argument("--force", action="store_true", help="replace an existing output file")
    generate.add_argument("--quiet", action="store_true", help="hide progress updates")
    return parser


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if not argv or argv == ["gui"]:
        from .ui import main as gui_main
        gui_main()
        return 0
    if argv[0] == "benchmark":
        from benchmarks.benchmark import main as benchmark_main
        return benchmark_main(argv[1:], prog="python -m wordlist_studio benchmark")
    parser = _parser()
    args = parser.parse_args(argv)
    if args.command == "generate":
        return _generate(args)
    if args.command == "gui":
        parser.error("gui does not accept additional arguments")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
