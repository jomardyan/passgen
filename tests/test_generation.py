import gzip
import json
import tempfile
import threading
import time
import unittest
from pathlib import Path
from random import Random
from unittest.mock import patch

from wordlist_studio.generator import candidates
from wordlist_studio.job import Cancelled, JobControl, run
from wordlist_studio.model import Config, EstimateCancelled, estimate


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

    def test_pause_resume_completes(self):
        config = Config(min_length=2, max_length=2, lowercase=False, digits=False,
                        extra_chars="ab")
        control = JobControl()
        control.pause()
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder) / "list.txt"
            results = []
            worker = threading.Thread(target=lambda: self._record(run, config, output, control, results))
            worker.start()
            time.sleep(0.05)
            self.assertTrue(worker.is_alive())
            self.assertFalse(output.exists())
            control.resume()
            worker.join(3)
            self.assertFalse(worker.is_alive())
            self.assertEqual(results[0]["total_entries"], 4)

    def test_failed_replace_preserves_original_and_removes_temps(self):
        config = Config(min_length=1, max_length=1, lowercase=False, digits=False,
                        extra_chars="ab", deduplicate=True)
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder) / "list.txt"
            output.write_text("previous\n")
            with patch("wordlist_studio.output.os.replace", side_effect=OSError("replace denied")):
                with self.assertRaisesRegex(OSError, "replace denied"):
                    run(config, output)
            self.assertEqual(output.read_text(), "previous\n")
            self.assertEqual(list(Path(folder).iterdir()), [output])

    def test_summary_failure_reports_saved_output(self):
        config = Config(min_length=1, max_length=1, lowercase=False, digits=False,
                        extra_chars="a")
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder) / "list.txt"
            with patch("wordlist_studio.job.write_summary", side_effect=OSError("log denied")):
                summary = run(config, output)
            self.assertEqual(output.read_text(), "a\n")
            self.assertIn("log denied", summary["summary_error"])

    def test_estimate_matches_rule_iterator_for_varied_inputs(self):
        random = Random(40)
        for _ in range(100):
            config = Config(mode="rules", min_length=1, max_length=8,
                            words=tuple(random.choice(("a", "b", "ab", "B"))
                                        for _ in range(random.randint(1, 3))),
                            combine_words=random.choice((False, True)),
                            substitutions=tuple(random.choice((("a", "@"), ("a", "A"),
                                                               ("b", "8")))
                                                for _ in range(random.randint(0, 2))),
                            prefixes=("1",), suffixes=("b",),
                            case_variants=random.choice((False, True)),
                            exclude_chars=random.choice(("", "a", "@", "b")))
            self.assertEqual(estimate(config), sum(1 for _ in candidates(config)))

    def test_stale_estimate_stops(self):
        config = Config(mode="rules", words=("a", "b"), combine_words=True)
        with self.assertRaises(EstimateCancelled):
            estimate(config, cancelled=lambda: True)

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
