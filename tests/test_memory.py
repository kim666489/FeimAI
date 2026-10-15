import tempfile
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from FeimUI import buildUserMemoryPrompt, loadChatSessions, saveChatSessions


class MemoryStorageTests(unittest.TestCase):
    def test_chat_history_round_trips(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "nested" / "history.json"
            sessions = [{
                "title": "Project",
                "messages": [
                    {"role": "user", "content": "I prefer short answers"},
                    {"role": "assistant", "content": "Understood"},
                ],
            }]
            saveChatSessions(path, sessions)
            self.assertEqual(loadChatSessions(path), sessions)

    def test_missing_history_file_starts_empty(self):
        with tempfile.TemporaryDirectory() as directory:
            self.assertEqual(loadChatSessions(Path(directory) / "missing.json"), [])

    def test_memory_prompt_uses_existing_memory_and_chat_text_only(self):
        prompt = buildUserMemoryPrompt([{
            "title": "Preferences",
            "messages": [
                {"role": "user", "content": "I prefer Thai responses"},
                {"role": "assistant", "content": "I will remember"},
                {"role": "tool", "content": "ignored tool output"},
            ],
        }], "## Existing\nLikes concise answers")
        self.assertIn("Likes concise answers", prompt)
        self.assertIn("I prefer Thai responses", prompt)
        self.assertNotIn("ignored tool output", prompt)

    def test_memory_prompt_truncates_long_history(self):
        prompt = buildUserMemoryPrompt([{
            "title": "Long chat",
            "messages": [{"role": "user", "content": "x" * 2000}],
        }], max_source_chars=1000)
        self.assertIn("[Earlier chat content omitted]", prompt)
        self.assertLess(len(prompt), 2500)


if __name__ == "__main__":
    unittest.main()
