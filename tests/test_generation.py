import gzip
import json
import tempfile
import threading
import time
import unittest
from pathlib import Path

from wordlist_studio.generator import candidates
from wordlist_studio.job import Cancelled, JobControl, run
from wordlist_studio.model import Config, estimate


class GenerationTests(unittest.TestCase):
    def test_exhaustive_estimate_and_output(self):
        config = Config(min_length=1, max_length=2, lowercase=False, digits=False,
                        extra_chars="ab", exclude_chars="b")
        self.assertEqual(estimate(config), 2)
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder) / "list.txt"
            summary = run(config, output)
            self.assertEqual(output.read_text(), "a\naa\n")
            self.assertEqual(summary["total_entries"], 2)
            record = json.loads(Path(str(output) + ".summary.json").read_text())
            self.assertEqual(record["statistics"]["file_size_bytes"], 5)

    def test_rules_estimate_matches_actual_and_dedup(self):
        config = Config(mode="rules", min_length=1, max_length=12, words=("a", "a"),
                        substitutions=(("a", "@"),), suffixes=("1",),
                        exclude_chars="@", deduplicate=True)
        self.assertEqual(estimate(config), len(list(candidates(config))))
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder) / "rules.txt.gz"
            config = Config(**{**config.__dict__, "gzip_output": True})
            summary = run(config, output)
            with gzip.open(output, "rt", encoding="utf-8") as source:
                self.assertEqual(source.read(), "a\na1\n")
            self.assertEqual(summary["processed"], 4)
            self.assertEqual(summary["total_entries"], 2)
            self.assertFalse(list(Path(folder).glob("*.partial")))
            self.assertFalse(list(Path(folder).glob("*.sqlite")))

    def test_dedup_across_base_and_pair(self):
        config = Config(mode="rules", min_length=1, max_length=5,
                        words=("a", "aa"), combine_words=True, deduplicate=True)
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder) / "list.txt"
            summary = run(config, output)
            self.assertEqual(summary["processed"], estimate(config))
            self.assertEqual(len(output.read_text().splitlines()), 4)

    def test_cancel_preserves_existing_file(self):
        config = Config(min_length=8, max_length=8, lowercase=False, digits=False,
                        extra_chars="abcdef")
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder) / "list.txt"
            output.write_text("existing\n")
            control = JobControl()
            control.cancel()
            with self.assertRaises(Cancelled):
                run(config, output, control)
            self.assertEqual(output.read_text(), "existing\n")
            self.assertEqual(len(list(Path(folder).iterdir())), 1)

    def test_pause_resume_cancel(self):
        config = Config(min_length=7, max_length=7, lowercase=False, digits=False,
                        extra_chars="abcd")
        control = JobControl()
        control.pause()
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder) / "list.txt"
            results = []
            worker = threading.Thread(target=lambda: self._record(run, config, output, control, results))
            worker.start()
            time.sleep(0.15)
            self.assertTrue(worker.is_alive())
            control.cancel()
            worker.join(3)
            self.assertFalse(worker.is_alive())
            self.assertIsInstance(results[0], Cancelled)
            self.assertFalse(output.exists())

    @staticmethod
    def _record(function, config, output, control, results):
        try:
            results.append(function(config, output, control))
        except Exception as exc:
            results.append(exc)

    def test_validation(self):
        with self.assertRaisesRegex(ValueError, "Lengths"):
            estimate(Config(min_length=5, max_length=2))
        with self.assertRaisesRegex(ValueError, "base word"):
            estimate(Config(mode="rules"))


if __name__ == "__main__":
    unittest.main()
