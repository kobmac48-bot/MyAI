import json
import queue
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from myai import (
    MyAI,
    ask_anthropic,
    ask_openai,
    load_ai_provider_keys,
    save_ai_provider_keys,
)


class AIProviderTests(unittest.TestCase):
    def test_openai_request_uses_chat_completions(self):
        response = MagicMock()
        response.__enter__.return_value.read.return_value = json.dumps(
            {"choices": [{"message": {"content": "OpenAI answer"}}]}
        ).encode("utf-8")
        with patch("myai.urllib.request.build_opener") as build_opener:
            build_opener.return_value.open.return_value = response
            answer = ask_openai("test-openai-key", [{"role": "user", "content": "Hi"}])

        self.assertEqual(answer, "OpenAI answer")
        request = build_opener.return_value.open.call_args.args[0]
        self.assertEqual(request.full_url, "https://api.openai.com/v1/chat/completions")
        self.assertEqual(request.get_header("Authorization"), "Bearer test-openai-key")
        self.assertEqual(json.loads(request.data)["model"], "gpt-4.1-mini")

    def test_anthropic_request_extracts_text_blocks(self):
        response = MagicMock()
        response.__enter__.return_value.read.return_value = json.dumps(
            {"content": [{"type": "text", "text": "Claude answer"}]}
        ).encode("utf-8")
        with patch("myai.urllib.request.build_opener") as build_opener:
            build_opener.return_value.open.return_value = response
            answer = ask_anthropic(
                "test-anthropic-key",
                [{"role": "user", "content": "Hi"}],
            )

        self.assertEqual(answer, "Claude answer")
        request = build_opener.return_value.open.call_args.args[0]
        self.assertEqual(request.full_url, "https://api.anthropic.com/v1/messages")
        self.assertEqual(request.get_header("X-api-key"), "test-anthropic-key")
        self.assertEqual(json.loads(request.data)["model"], "claude-haiku-5-5")

    def test_saves_and_loads_provider_keys_locally(self):
        with tempfile.TemporaryDirectory() as directory:
            settings_file = Path(directory) / "ai-provider-keys.json"
            with (
                patch("myai.DATA_DIR", Path(directory)),
                patch("myai.AI_PROVIDER_SETTINGS_FILE", settings_file),
            ):
                save_ai_provider_keys({"openai": "openai-key", "anthropic": "anthropic-key"})
                self.assertEqual(
                    load_ai_provider_keys(),
                    {"openai": "openai-key", "anthropic": "anthropic-key"},
                )

    def test_combines_provider_replies_for_local_synthesis(self):
        app = MyAI.__new__(MyAI)
        app.events = queue.Queue()
        messages = [{"role": "user", "content": "Explain this"}]
        with (
            patch("myai.ask_openai", return_value="OpenAI response"),
            patch("myai.ask_anthropic", return_value="Claude response"),
        ):
            combined = app._get_collaborative_messages(
                messages,
                {"openai": "openai-key", "anthropic": "anthropic-key"},
            )

        self.assertEqual(messages[0]["content"], "Explain this")
        self.assertIn("OpenAI response", combined[-1]["content"])
        self.assertIn("Claude response", combined[-1]["content"])
        self.assertIn("eigenstaendige Zusammenfassung", combined[-1]["content"])
        self.assertTrue(app.events.empty())

    def test_continues_if_one_provider_fails(self):
        app = MyAI.__new__(MyAI)
        app.events = queue.Queue()
        with (
            patch("myai.ask_openai", side_effect=RuntimeError("unavailable")),
            patch("myai.ask_anthropic", return_value="Claude response"),
        ):
            combined = app._get_collaborative_messages(
                [{"role": "user", "content": "Explain this"}],
                {"openai": "openai-key", "anthropic": "anthropic-key"},
            )

        self.assertIn("Claude response", combined[-1]["content"])
        self.assertEqual(
            app.events.get_nowait(),
            ("collaboration_warning", "Ein Anbieter ist fehlgeschlagen: ChatGPT: unavailable"),
        )

    def test_fails_if_both_providers_fail(self):
        app = MyAI.__new__(MyAI)
        app.events = queue.Queue()
        with (
            patch("myai.ask_openai", side_effect=RuntimeError("OpenAI unavailable")),
            patch("myai.ask_anthropic", side_effect=RuntimeError("Claude unavailable")),
        ):
            with self.assertRaisesRegex(RuntimeError, "Keine externe KI konnte antworten"):
                app._get_collaborative_messages(
                    [{"role": "user", "content": "Explain this"}],
                    {"openai": "openai-key", "anthropic": "anthropic-key"},
                )


if __name__ == "__main__":
    unittest.main()
