# Benchmark result

Measured on 2026-09-28 in a Linux x86_64 container using Python 3.12.14. The input was one million exhaustive six-character strings from ten custom characters. Output was written to a temporary directory on the container filesystem. Deduplication was disabled. Each run includes generation, encoding, disk output, and close time.

| Mode | Entries | Output bytes | Elapsed seconds | Candidates per second |
| --- | ---: | ---: | ---: | ---: |
| Plain UTF-8 | 1,000,000 | 7,000,000 | 0.507 | 1,972,387 |
| Gzip, level 3 | 1,000,000 | 1,721,582 | 0.559 | 1,788,909 |

Run `python -m benchmarks.benchmark` from the project root to reproduce the measurement. Results depend on hardware, storage, selected rules, and system load. Rule mutations and SQLite deduplication will have different throughput.

On 2026-09-28, the same one-million-candidate workload was measured on Windows 11 with Python 3.14.7. Each row is one run and includes generation, encoding, direct disk output, and close time. Multiple workers use the bounded process pool and writer thread.

| Mode | Workers | Entries | Output bytes | Elapsed seconds | Candidates per second |
| --- | ---: | ---: | ---: | ---: | ---: |
| Plain UTF-8 | 1 | 1,000,000 | 7,000,000 | 0.598 | 1,672,241 |
| Plain UTF-8 | 4 | 1,000,000 | 7,000,000 | 0.341 | 2,932,551 |
| Gzip, level 3 | 1 | 1,000,000 | 2,143,916 | 0.676 | 1,479,290 |
| Gzip, level 3 | 4 | 1,000,000 | 2,143,916 | 0.551 | 1,814,882 |

Run `python -m wordlist_studio benchmark --workers 1,4` to compare the serial and parallel paths in one command. These results are illustrative; gains depend on the workload and machine.
