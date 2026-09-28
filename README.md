# Wordlist Studio

A desktop wordlist generator for authorized security testing and lawful password strength audits. It enumerates candidates deterministically, reports an estimate before generation, and writes output to disk without storing the entire wordlist in memory.

## Install and launch

Use Python 3.10 or later with Tk support. Tkinter ships with most Python desktop installers. Some Linux distributions require a separate `python3-tk` operating system package.

```bash
python -m wordlist_studio
```

No Python packages are required. The `requirements.txt` file is intentionally empty.

## Configuration

- **Exhaustive combinations** enumerates all strings of the selected lengths from the chosen lowercase, uppercase, digit, symbol, and additional character pool. Repeated pool characters are removed. Excluded characters are removed from the pool.
- **Keyword rules** emits each base word and, if enabled, every ordered pair of words. It can add case variants, apply each listed one-character substitution independently at every matching position, and prepend or append one listed affix or none. Prefix and suffix lists accept one entry per line. Rule candidates containing excluded characters are skipped. Character pool checkboxes and additional characters apply only to exhaustive mode.
- The **estimate** counts emitted candidates before global deduplication. It respects length limits and excluded characters. It can exceed the number of unique output lines.
- **Deduplicate on disk** uses a temporary SQLite index so memory consumption stays bounded. It costs disk space and throughput. Without it, repeated candidates remain in the output.
- **Gzip compression** writes a `.gz` file at compression level 3. Plain output uses `.txt`. UTF-8 text is written with one candidate per line.

Generation takes place on a background thread. Pause and resume are cooperative. Cancel removes temporary output and leaves an existing destination unchanged. Successful output replaces its destination atomically and creates a `.summary.json` file beside it with settings, entry count, byte size, duration, and completion time. Keep summaries and wordlists secure because they may contain sensitive keywords.

If writing the summary fails after the wordlist has been committed, the interface reports a warning and retains the completed output.

Large exhaustive searches grow exponentially and may require substantial time and disk space. Check the estimate before starting. Throughput depends on storage speed, candidate length, compression, and deduplication.

## Test and benchmark

```bash
python -m unittest discover -s tests -v
python -m benchmarks.benchmark
```

The benchmark generates one million six-character candidates into a temporary directory. It reports plain text and gzip throughput on the current machine. See `benchmarks/RESULTS.md` for a measured run and its environment. The implementation uses `itertools.product` for enumeration, a 64 KiB write buffer, streaming gzip, and an optional SQLite unique index. The background thread keeps the interface responsive. It does not claim multicore speedup for Python candidate generation.

GitHub Actions runs the test suite on Python 3.10 and 3.13 on Linux and Python 3.12 on Windows for each push and pull request.

## Project layout

- `wordlist_studio/model.py` - validated settings and live candidate estimate
- `wordlist_studio/generator.py` - lazy exhaustive and rule based iteration
- `wordlist_studio/output.py` - streamed output, atomic replacement, and deduplication
- `wordlist_studio/job.py` - progress and pause, resume, cancel controls
- `wordlist_studio/ui.py` - Tkinter and ttk interface
- `tests/` - generation and file safety tests
- `benchmarks/` - reproducible throughput measurement
