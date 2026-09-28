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
from wordlist_studio.model import Config, EstimateCancelled, estimate, estimate_output
from wordlist_studio.parallel import generate_batch, tasks
from wordlist_studio.output import StreamingOutput


class GenerationTests(unittest.TestCase):
    def test_parallel_batches_preserve_candidate_order(self):
        configs = (
            Config(min_length=1, max_length=2, lowercase=False, digits=False,
                   extra_chars="abé"),
            Config(mode="rules", min_length=1, max_length=6, words=("ab", "ba"),
                   combine_words=True, substitutions=(("a", "@"),),
                   prefixes=("1",), suffixes=("!",), case_variants=True),
        )
        for config in configs:
            batches = [generate_batch(task, False)[1] for task in tasks(config, batch_size=3)]
            self.assertEqual([candidate for batch in batches for candidate in batch],
                             list(candidates(config)))

    def test_multiple_workers_write_plain_and_deduplicated_gzip(self):
        configs = (
            Config(min_length=2, max_length=3, lowercase=False, digits=False,
                   extra_chars="abc", workers=2),
            Config(mode="rules", min_length=1, max_length=5, words=("a", "aa"),
                   combine_words=True, deduplicate=True, gzip_output=True, workers=2),
        )
        with tempfile.TemporaryDirectory() as folder:
            for index, config in enumerate(configs):
                path = Path(folder) / (f"list{index}.txt.gz" if config.gzip_output
                                       else f"list{index}.txt")
                summary = run(config, path)
                if config.gzip_output:
                    with gzip.open(path, "rt", encoding="utf-8") as source:
                        actual = source.read().splitlines()
                    expected = list(dict.fromkeys(candidates(config)))
                else:
                    actual = path.read_text(encoding="utf-8").splitlines()
                    expected = list(candidates(config))
                self.assertEqual(actual, expected)
                self.assertEqual(summary["processed"], estimate(config))

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

    def test_plain_byte_estimate_matches_unicode_output(self):
        configs = (
            Config(min_length=1, max_length=2, lowercase=False, digits=False,
                   extra_chars="aé"),
            Config(mode="rules", min_length=1, max_length=8, words=("éa", "a"),
                   combine_words=True, substitutions=(("a", "💡"),),
                   prefixes=("ø",), suffixes=("1",), case_variants=True),
        )
        for config in configs:
            result = estimate_output(config)
            self.assertEqual(result.candidates, estimate(config))
            expected = sum(len((candidate + "\n").encode("utf-8"))
                           for candidate in candidates(config))
            self.assertEqual(result.plain_bytes, expected)

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

    def test_exhaustive_dedup_skips_sqlite(self):
        config = Config(min_length=2, max_length=2, lowercase=False, digits=False,
                        extra_chars="aba", deduplicate=True, workers=2)
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder) / "list.txt"
            with patch("wordlist_studio.output.sqlite3.connect",
                       side_effect=AssertionError("SQLite must not be used")):
                summary = run(config, output)
            self.assertEqual(output.read_text(), "aa\nab\nba\nbb\n")
            self.assertEqual(summary["total_entries"], 4)

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

    def test_cancel_keeps_partial_output_at_destination(self):
        class CancelAfter(JobControl):
            def __init__(self, checkpoints):
                super().__init__()
                self.remaining = checkpoints

            def checkpoint(self):
                self.remaining -= 1
                if not self.remaining:
                    self.cancel()
                return super().checkpoint()

        config = Config(min_length=10, max_length=10, lowercase=False, digits=False,
                        extra_chars="ab", gzip_output=True)
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder) / "list.txt.gz"
            output.write_text("previous\n")
            with self.assertRaises(Cancelled) as raised:
                run(config, output, CancelAfter(102))
            self.assertEqual(raised.exception.output_path, str(output.resolve()))
            with gzip.open(output, "rt", encoding="utf-8") as source:
                self.assertEqual(source.read().splitlines(), list(candidates(config))[:100])
            self.assertEqual(list(Path(folder).iterdir()), [output])

    def test_parallel_cancel_keeps_completed_batches(self):
        config = Config(min_length=7, max_length=7, lowercase=False, digits=False,
                        extra_chars="abcdef", workers=2)
        control = JobControl()
        original_write = StreamingOutput.write_batch

        def write_and_cancel(output, data, count):
            original_write(output, data, count)
            control.cancel()

        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder) / "partial.txt"
            with patch.object(StreamingOutput, "write_batch", write_and_cancel):
                with self.assertRaises(Cancelled) as raised:
                    run(config, output, control)
            self.assertEqual(raised.exception.output_path, str(output.resolve()))
            self.assertEqual(output.read_text().splitlines(),
                             list(candidates(config))[:46_656])

    def test_parallel_output_uses_writer_thread(self):
        config = Config(min_length=2, max_length=2, lowercase=False, digits=False,
                        extra_chars="ab", workers=2)
        thread_names = []
        original_write = StreamingOutput.write_batch

        def record_writer(output, data, count):
            thread_names.append(threading.current_thread().name)
            original_write(output, data, count)

        with tempfile.TemporaryDirectory() as folder:
            with patch.object(StreamingOutput, "write_batch", record_writer):
                run(config, Path(folder) / "list.txt")
        self.assertEqual(thread_names, ["wordlist-writer"])

    def test_parallel_writer_failure_keeps_partial_output(self):
        config = Config(min_length=2, max_length=2, lowercase=False, digits=False,
                        extra_chars="ab", workers=2)
        original_write = StreamingOutput.write_batch

        def fail_after_write(output, data, count):
            original_write(output, data, count)
            raise OSError("writer failed")

        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "partial.txt"
            with patch.object(StreamingOutput, "write_batch", fail_after_write):
                with self.assertRaisesRegex(OSError, "writer failed") as raised:
                    run(config, path)
            self.assertEqual(raised.exception.output_path, str(path.resolve()))
            self.assertEqual(path.read_text(), "aa\nab\nba\nbb\n")

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
        with self.assertRaisesRegex(ValueError, "Workers"):
            estimate(Config(workers=0))


if __name__ == "__main__":
    unittest.main()
