import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from wordlist_studio.model import Config
from wordlist_studio.ui import App


class Variable:
    def __init__(self, value):
        self.value = value

    def get(self):
        return self.value

    def set(self, value):
        self.value = value


class UiLogicTests(unittest.TestCase):
    def test_zero_estimate_reports_no_candidates(self):
        config = Config(mode="rules", words=("a",), min_length=4, max_length=4)
        fake = SimpleNamespace(_read=lambda: config, estimate_cache=(config, 0),
                               _schedule_estimate=Mock())
        with patch("wordlist_studio.ui.messagebox.showerror") as error:
            App._start(fake)
        self.assertIn("No candidates", error.call_args.args[1])
        fake._schedule_estimate.assert_not_called()

    def test_invalid_model_settings_report_specific_error(self):
        config = Config(min_length=6, max_length=2)
        fake = SimpleNamespace(_read=lambda: config,
                               estimate_cache=(config, ValueError("Invalid lengths")),
                               _schedule_estimate=Mock())
        with patch("wordlist_studio.ui.messagebox.showerror") as error:
            App._start(fake)
        self.assertEqual(error.call_args.args[1], "Invalid lengths")
        fake._schedule_estimate.assert_not_called()

    def test_compression_updates_default_file_extension(self):
        fake = SimpleNamespace(output=Variable("/tmp/list.txt"), compress=Variable(True))
        App._match_output_extension(fake)
        self.assertEqual(fake.output.get(), "/tmp/list.txt.gz")
        fake.compress.set(False)
        App._match_output_extension(fake)
        self.assertEqual(fake.output.get(), "/tmp/list.txt")

    def test_modified_rule_text_triggers_estimate(self):
        widget = Mock()
        widget.edit_modified.return_value = True
        fake = SimpleNamespace(_schedule_estimate=Mock())
        App._rules_modified(fake, SimpleNamespace(widget=widget))
        widget.edit_modified.assert_any_call(False)
        fake._schedule_estimate.assert_called_once()


if __name__ == "__main__":
    unittest.main()
