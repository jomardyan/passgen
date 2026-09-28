# Benchmark result

Measured on 2026-09-28 in a Linux x86_64 container using Python 3.12.14. The input was one million exhaustive six-character strings from ten custom characters. Output was written to a temporary directory on the container filesystem. Deduplication was disabled. Each run includes generation, encoding, disk output, and close time.

| Mode | Entries | Output bytes | Elapsed seconds | Candidates per second |
| --- | ---: | ---: | ---: | ---: |
| Plain UTF-8 | 1,000,000 | 7,000,000 | 0.867 | 1,153,403 |
| Gzip, level 3 | 1,000,000 | 1,721,582 | 1.059 | 944,287 |

Run `python -m benchmarks.benchmark` from the project root to reproduce the measurement. Results depend on hardware, storage, selected rules, and system load. Rule mutations and SQLite deduplication will have different throughput.
