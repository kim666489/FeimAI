import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from feimvoice.config import DEFAULT_VOICE_CONFIG, load_voice_config, save_voice_config
from feimvoice.stt import matches_wake_word, normalize_wake_word


class FeimVoiceConfigTests(unittest.TestCase):
    def test_missing_config_uses_independent_defaults(self):
        with tempfile.TemporaryDirectory() as directory:
            config = load_voice_config(Path(directory) / "missing.json")
        self.assertEqual(config, DEFAULT_VOICE_CONFIG)
        self.assertNotIn("serverURL", config)

    def test_config_save_and_load_preserve_settings_and_fill_new_defaults(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "nested" / "feimvoice.json"
            save_voice_config(path, {
                "enabled": False,
                "wake": {"enabled": True, "words": ["hello"]},
            })
            loaded = load_voice_config(path)
            raw = json.loads(path.read_text(encoding="utf-8"))
        self.assertFalse(loaded["enabled"])
        self.assertTrue(loaded["wake"]["enabled"])
        self.assertEqual(loaded["wake"]["words"], ["hello"])
        self.assertEqual(loaded["tts"], DEFAULT_VOICE_CONFIG["tts"])
        self.assertEqual(raw["enabled"], False)

    def test_non_object_config_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "feimvoice.json"
            path.write_text("[]", encoding="utf-8")
            with self.assertRaises(ValueError):
                load_voice_config(path)

    def test_wake_word_matching_normalizes_case_and_punctuation(self):
        self.assertEqual(normalize_wake_word("Feim-Voice!"), "feim voice")
        self.assertTrue(matches_wake_word("Hey, FEIM VOICE!", ["feim voice"]))
        self.assertTrue(matches_wake_word("ฟีมวอยซ์ ช่วยหน่อย", ["ฟีมวอยซ์"]))
        self.assertFalse(matches_wake_word("hello assistant", ["feim voice"]))


if __name__ == "__main__":
    unittest.main()
