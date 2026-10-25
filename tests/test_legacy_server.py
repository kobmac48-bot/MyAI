import io
import json
import threading
import unittest
from http.server import ThreadingHTTPServer
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from legacy_client import NoRedirectHandler, valid_server_url
from server import myai_server


class StubResponse(io.BytesIO):
    headers = {"Content-Type": "application/x-ndjson"}


class LegacyServerTests(unittest.TestCase):
    def test_accepts_only_public_https_server_urls(self):
        self.assertTrue(valid_server_url("https://myai.example.com"))
        self.assertTrue(valid_server_url("https://myai.example.com:8443/"))
        for value in (
            "http://myai.example.com",
            "https://user:password@myai.example.com",
            "https://myai.example.com/path",
            "https://myai.example.com/?redirect=1",
            "https://myai.example.com:invalid",
        ):
            with self.subTest(value=value):
                self.assertFalse(valid_server_url(value))

    def test_rejects_nonlocal_ollama_addresses(self):
        self.assertTrue(myai_server.valid_ollama_url("http://127.0.0.1:11434"))
        self.assertTrue(myai_server.valid_ollama_url("http://localhost:11434"))
        for value in (
            "https://127.0.0.1:11434",
            "http://localhost.evil.example:11434",
            "http://127.0.0.1.example:11434",
            "http://user@localhost:11434",
            "http://localhost:11434/proxy",
        ):
            with self.subTest(value=value):
                self.assertFalse(myai_server.valid_ollama_url(value))

    def test_server_client_does_not_forward_tokens_to_redirect_targets(self):
        self.assertIsNone(
            NoRedirectHandler().redirect_request(
                None,
                None,
                302,
                "Found",
                {},
                "https://attacker.example/",
            )
        )

    def test_validates_chat_request_shape(self):
        self.assertTrue(
            myai_server.valid_chat_payload(
                {
                    "model": "llama3.1",
                    "messages": [{"role": "user", "content": "Hello"}],
                }
            )
        )
        for payload in (
            None,
            {"model": "", "messages": [{"role": "user", "content": "Hello"}]},
            {"model": "llama3.1", "messages": []},
            {
                "model": "llama3.1",
                "messages": [{"role": "developer", "content": "Hello"}],
            },
            {
                "model": "llama3.1",
                "messages": [{"role": [], "content": "Hello"}],
            },
            {
                "model": "llama3.1",
                "messages": [{"role": "user", "content": {"text": "Hello"}}],
            },
        ):
            with self.subTest(payload=payload):
                self.assertFalse(myai_server.valid_chat_payload(payload))

    def test_proxies_authorized_chat_and_rejects_missing_token(self):
        server = ThreadingHTTPServer(("127.0.0.1", 0), myai_server.MyAIHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        base_url = "http://127.0.0.1:{}".format(server.server_port)
        body = json.dumps(
            {
                "model": "llama3.1",
                "messages": [{"role": "user", "content": "Hello"}],
                "stream": True,
            }
        ).encode("utf-8")
        try:
            with patch.object(myai_server, "SERVER_TOKEN", "x" * 48):
                with self.assertRaises(HTTPError) as unauthorized:
                    urlopen(base_url + "/api/tags")
                self.assertEqual(unauthorized.exception.code, 401)

                with patch.object(
                    myai_server,
                    "ollama_request",
                    return_value=StubResponse(b'{"message":{"content":"Hi"}}\n'),
                ) as ollama_request:
                    request = Request(
                        base_url + "/api/chat",
                        data=body,
                        headers={"Authorization": "Bearer " + "x" * 48},
                    )
                    with urlopen(request) as response:
                        self.assertEqual(
                            response.read(),
                            b'{"message":{"content":"Hi"}}\n',
                        )
                    ollama_request.assert_called_once_with("/api/chat", body)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)


if __name__ == "__main__":
    unittest.main()
