import gzip
import io
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

from benchmarks.benchmark import main as benchmark_main
from wordlist_studio.cli import main as cli_main


class CliTests(unittest.TestCase):
    def test_dry_run_prints_estimates_without_writing(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "list.txt"
            output = io.StringIO()
            with redirect_stdout(output):
                code = cli_main(["generate", "--output", str(path), "--min-length", "2",
                                 "--no-lowercase", "--no-digits", "--extra-chars", "ab",
                                 "--dry-run"])
            self.assertEqual(code, 0)
            self.assertIn("Candidates before deduplication: 4", output.getvalue())
            self.assertIn("Estimated final file size: 12 B", output.getvalue())
            self.assertFalse(path.exists())

    def test_generate_parallel_rules_from_file(self):
        with tempfile.TemporaryDirectory() as folder:
            words = Path(folder) / "words.txt"
            words.write_text("a\na\n", encoding="utf-8")
            path = Path(folder) / "list.txt.gz"
            with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                code = cli_main(["generate", "--output", str(path), "--mode", "rules",
                                 "--min-length", "1", "--max-length", "4",
                                 "--words-file", str(words), "--substitution", "a=@",
                                 "--suffix", "1", "--deduplicate", "--workers", "2",
                                 "--quiet"])
            self.assertEqual(code, 0)
            with gzip.open(path, "rt", encoding="utf-8") as source:
                self.assertEqual(source.read(), "a\n@\na1\n@1\n")
            self.assertTrue(Path(str(path) + ".summary.json").exists())

    def test_existing_output_requires_force(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "list.txt"
            path.write_text("existing\n")
            command = ["generate", "--output", str(path), "--min-length", "1",
                       "--no-lowercase", "--no-digits", "--extra-chars", "a",
                       "--workers", "1", "--quiet"]
            with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                self.assertEqual(cli_main(command), 2)
            self.assertEqual(path.read_text(), "existing\n")
            with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                self.assertEqual(cli_main([*command, "--force"]), 0)
            self.assertEqual(path.read_text(), "a\n")

    def test_benchmark_compares_worker_counts(self):
        output = io.StringIO()
        with redirect_stdout(output):
            code = benchmark_main(["--workers", "1,2", "--length", "2",
                                   "--alphabet", "ab", "--compression", "plain"])
        self.assertEqual(code, 0)
        lines = output.getvalue().splitlines()
        self.assertIn("Speedup", output.getvalue())
        table_lines = [line for line in lines if line.startswith(("|", "+"))]
        self.assertEqual(len(table_lines), 6)
        self.assertEqual(len({len(line) for line in table_lines}), 1)
        self.assertIn("| Plain |       1 |", table_lines[3])
        self.assertIn("| Plain |       2 |", table_lines[4])

    def test_module_entrypoint_runs_parallel_generation(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "list.txt"
            result = subprocess.run(
                [sys.executable, "-m", "wordlist_studio", "generate", "--output", str(path),
                 "--min-length", "2", "--no-lowercase", "--no-digits",
                 "--extra-chars", "ab", "--workers", "2", "--quiet"],
                cwd=Path(__file__).resolve().parents[1], capture_output=True, text=True,
                timeout=20)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(path.read_text(), "aa\nab\nba\nbb\n")


if __name__ == "__main__":
    unittest.main()
