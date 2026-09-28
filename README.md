# Wordlist Studio

A desktop wordlist generator for authorized security testing and lawful password strength audits. It enumerates candidates deterministically, reports an estimate before generation, and writes output to disk without storing the entire wordlist in memory.

## Install and launch

Use Python 3.10 or later with Tk support. Tkinter ships with most Python desktop installers. Some Linux distributions require a separate `python3-tk` operating system package.

```bash
python -m wordlist_studio
```

No Python packages are required. The `requirements.txt` file is intentionally empty.

## Command line

The desktop interface remains the default. Use `generate` for a terminal job and `--dry-run` to view the estimates without creating a file:

```bash
python -m wordlist_studio generate --output wordlist.txt --min-length 4 --max-length 4 --workers 4 --dry-run
python -m wordlist_studio generate --output wordlist.txt --min-length 4 --max-length 4 --workers 4
```

Existing output requires `--force` because generation writes directly to that file. Press Ctrl+C for a clean cancellation that keeps the partial output. A `.gz` destination enables gzip automatically. For keyword rules, use `--mode rules` with `--word` or `--words-file`, and optional `--substitution`, `--prefix`, and `--suffix` arguments. Run `python -m wordlist_studio generate --help` for all settings.

The benchmark can compare worker counts under the same workload:

```bash
python -m wordlist_studio benchmark --workers 1,4
python -m wordlist_studio benchmark --workers 1,2,4 --length 7 --alphabet abcdef --compression plain
```

## Configuration

- **Exhaustive combinations** enumerates all strings of the selected lengths from the chosen lowercase, uppercase, digit, symbol, and additional character pool. Repeated pool characters are removed. Excluded characters are removed from the pool.
- **Keyword rules** emits each base word and, if enabled, every ordered pair of words. It can add case variants, apply each listed one-character substitution independently at every matching position, and prepend or append one listed affix or none. Prefix and suffix lists accept one entry per line. Rule candidates containing excluded characters are skipped. Character pool checkboxes and additional characters apply only to exhaustive mode.
- The **estimates** update as settings change. Candidate count and plain UTF-8 bytes are exact before global deduplication, so deduplicated output may be smaller. Plain output without deduplication has an exact size estimate. Gzip size uses a rough 50% compression assumption, and actual size depends on content. The time estimate starts from a planning rate of 1,000,000 candidates/s for plain output, 500,000 for gzip, or 100,000 with disk deduplication. For plain and gzip output, the displayed rate increases conservatively with additional workers, up to four times the base rate. Actual speed depends on the computer, storage, and settings.
- **Deduplicate on disk** uses a temporary SQLite index for keyword rules so memory consumption stays bounded. It costs disk space and throughput. Exhaustive candidates are already unique, so the index is skipped in that mode even if the option is selected.
- **Gzip compression** writes a `.gz` file at compression level 3. Plain output uses `.txt`. UTF-8 text is written with one candidate per line.
- **Workers** runs candidate generation in separate CPU processes, up to 32. The desktop app defaults to the smaller of eight workers or the detected CPU count. Results are written in deterministic order. Multiple workers help most on large jobs; process startup can make small jobs slower.

Generation takes place on a background job thread. With multiple workers selected, separate processes build candidate batches while a dedicated writer thread saves completed batches in order. Bounded queues limit memory use and let generation overlap with disk output. Pause and resume are cooperative. Output is written directly to the selected file as generation proceeds. Cancel or a generation error keeps the partial output at that path; a clean cancel also closes gzip output so the saved portion can be read. If an existing file is selected, generation overwrites it once started. A completed run creates a `.summary.json` file beside the output with settings, entry count, byte size, duration, and completion time. Keep summaries and wordlists secure because they may contain sensitive keywords.

If writing the summary fails after the wordlist has been committed, the interface reports a warning and retains the completed output.

Large exhaustive searches grow exponentially and may require substantial time and disk space. Check the estimate before starting. Throughput depends on storage speed, candidate length, compression, deduplication, and worker count. Disk deduplication still uses a temporary SQLite index, which is removed after the run.

## Test and benchmark

```bash
python -m unittest discover -s tests -v
python -m benchmarks.benchmark
python -m benchmarks.benchmark --workers 1,4
```

By default, the benchmark generates one million six-character candidates into a temporary directory. It prints an aligned table for plain text and gzip with worker count, processed and written candidates, time, throughput, output bytes, and speedup relative to the first requested worker count. `--length`, `--alphabet`, and `--compression` change the workload. The benchmark uses exhaustive generation, so `--deduplicate` is skipped. See `benchmarks/RESULTS.md` for measured runs and their environments. The implementation uses `itertools.product` for enumeration, a 64 KiB write buffer, streaming gzip, and an optional SQLite unique index for keyword rules. The background thread keeps the interface responsive, and multiple worker processes can use multiple CPU cores.

GitHub Actions runs the test suite on Python 3.10 and 3.13 on Linux and Python 3.12 on Windows for each push and pull request.

## Project layout

- `wordlist_studio/model.py` - validated settings and live candidate estimate
- `wordlist_studio/generator.py` - lazy exhaustive and rule based iteration
- `wordlist_studio/output.py` - direct streamed output and deduplication
- `wordlist_studio/job.py` - threaded writer, progress, and pause, resume, cancel controls
- `wordlist_studio/parallel.py` - bounded, ordered process work units
- `wordlist_studio/ui.py` - Tkinter and ttk interface
- `wordlist_studio/cli.py` - terminal generation and benchmark commands
- `wordlist_studio/display.py` - shared estimate formatting
- `tests/` - generation and file safety tests
- `benchmarks/` - reproducible throughput measurement
