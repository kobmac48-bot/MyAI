import io
import json
import queue
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from myai import MyAI, pull_ollama_model


class OllamaModelTests(unittest.TestCase):
    def test_pulls_model_and_reports_progress(self):
        response = io.BytesIO(
            b'{"status":"pulling","total":100,"completed":25}\n'
            b'{"status":"success","total":100,"completed":100}\n'
        )
        progress = []
        with patch("myai.urllib.request.urlopen", return_value=response) as urlopen:
            pull_ollama_model("llama3.1", progress.append)

        request = urlopen.call_args.args[0]
        self.assertEqual(request.full_url, "http://localhost:11434/api/pull")
        self.assertEqual(json.loads(request.data.decode("utf-8")), {
            "model": "llama3.1",
            "stream": True,
        })
        self.assertEqual(progress, [
            "Modell llama3.1 herunterladen - pulling: 25%",
            "Modell llama3.1 herunterladen - success: 100%",
        ])

    def test_reports_ollama_pull_errors(self):
        response = io.BytesIO(b'{"error":"model not found"}\n')
        with patch("myai.urllib.request.urlopen", return_value=response):
            with self.assertRaisesRegex(RuntimeError, "model not found"):
                pull_ollama_model("llama3.1")

    def test_requires_success_confirmation(self):
        response = io.BytesIO(b'{"status":"pulling"}\n')
        with patch("myai.urllib.request.urlopen", return_value=response):
            with self.assertRaisesRegex(RuntimeError, "nicht als abgeschlossen"):
                pull_ollama_model("llama3.1")

    def test_refresh_downloads_missing_llama31(self):
        app = MyAI.__new__(MyAI)
        app.busy = False
        app.training_running = False
        app.model_download_running = False
        app.status = MagicMock()
        app.refresh_button = MagicMock()
        app.events = queue.Queue()

        class ImmediateThread:
            def __init__(self, target, daemon):
                self.target = target

            def start(self):
                self.target()

        responses = [
            io.BytesIO(b'{"models":[]}\n'),
            io.BytesIO(b'{"models":[{"name":"llama3.1:latest"}]}\n'),
        ]
        with (
            patch("myai.threading.Thread", ImmediateThread),
            patch("myai.TRAINED_MODELS_DIR", Path("missing-trained-models")),
            patch("myai.urllib.request.urlopen", side_effect=responses),
            patch(
                "myai.pull_ollama_model",
                side_effect=lambda model, progress: progress("download progress"),
            ) as pull,
        ):
            app.refresh_models(auto_download=True)

        pull.assert_called_once()
        self.assertEqual(pull.call_args.args[0], "llama3.1")
        events = [app.events.get_nowait() for _ in range(3)]
        self.assertEqual(events[0], ("model_download", "Llama 3.1 fehlt; Download wird gestartet..."))
        self.assertEqual(events[1], ("model_download", "download progress"))
        self.assertEqual(events[2][0], "models")
        self.assertEqual(events[2][1]["ollama"], ["llama3.1:latest"])
        self.assertIsNone(events[2][1]["model_pull_error"])


if __name__ == "__main__":
    unittest.main()
