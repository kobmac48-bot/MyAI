import json
import queue
import unittest
from unittest.mock import MagicMock, patch

from myai import (
    MyAI,
    NoRedirectHandler,
    is_valid_discord_webhook,
    split_discord_message,
)


class DiscordWebhookTests(unittest.TestCase):
    def test_accepts_discord_webhook_urls(self):
        self.assertTrue(
            is_valid_discord_webhook(
                "https://discord.com/api/webhooks/1234567890/token_abc-123"
            )
        )
        self.assertTrue(
            is_valid_discord_webhook(
                "https://discordapp.com/api/webhooks/1234567890/token.abc"
            )
        )

    def test_rejects_non_discord_or_malformed_urls(self):
        for url in (
            "http://discord.com/api/webhooks/1234567890/token",
            "https://example.com/api/webhooks/1234567890/token",
            "https://user:pass@discord.com/api/webhooks/1234567890/token",
            "https://discord.com:invalid/api/webhooks/1234567890/token",
            "https://discord.com/api/webhooks/1234567890/token?redirect=1",
            "https://discord.com/api/webhooks/not-an-id/token",
            "https://discord.com/api/webhooks/1234567890/token\n",
        ):
            with self.subTest(url=url):
                self.assertFalse(is_valid_discord_webhook(url))

    def test_splits_long_messages_without_losing_content(self):
        content = ("Aufgabe\n" + "x" * 1905 + "\nAusgabe\n" + "y" * 1905)
        chunks = split_discord_message(content)

        self.assertGreater(len(chunks), 1)
        self.assertTrue(all(len(chunk) <= 1900 for chunk in chunks))
        self.assertEqual("".join(chunks), content)

    def test_webhook_posts_disable_mentions_and_redirects(self):
        app = MyAI.__new__(MyAI)
        app.events = queue.Queue()
        opener = MagicMock()
        with patch("myai.urllib.request.build_opener", return_value=opener):
            app._post_discord_messages(
                "https://discord.com/api/webhooks/1234567890/token",
                ["Task and answer"],
            )

        request = opener.open.call_args.args[0]
        payload = json.loads(request.data.decode("utf-8"))
        self.assertEqual(payload["allowed_mentions"], {"parse": []})
        self.assertEqual(payload["content"], "Task and answer")
        self.assertEqual(app.events.get_nowait(), ("discord_sent", None))
        self.assertIsNone(
            NoRedirectHandler().redirect_request(
                None, None, 302, "Found", {}, "https://example.com/"
            )
        )


if __name__ == "__main__":
    unittest.main()
