import queue
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from myai import MyAI
import local_model


class LocalModelTests(unittest.TestCase):
    def test_downloads_configured_model_and_reports_progress(self):
        huggingface_hub = MagicMock()
        huggingface_hub.snapshot_download.return_value = "downloaded-model"
        with patch.dict(sys.modules, {"huggingface_hub": huggingface_hub}):
            progress = []
            model_path = local_model.download_model(progress.append)

        self.assertEqual(model_path, "downloaded-model")
        huggingface_hub.snapshot_download.assert_called_once_with(
            repo_id=local_model.MODEL_ID,
            cache_dir=str(local_model.MODEL_CACHE_DIR),
        )
        self.assertEqual(
            progress,
            [
                f"Lade {local_model.MODEL_ID} herunter...",
                f"{local_model.MODEL_ID} ist bereit",
            ],
        )

    def test_refresh_downloads_model_when_missing(self):
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

        with (
            patch("myai.threading.Thread", ImmediateThread),
            patch("myai.TRAINED_MODELS_DIR", Path("missing-trained-models")),
            patch("myai.local_model.find_downloaded_model", return_value=None),
            patch(
                "myai.local_model.download_model",
                side_effect=lambda progress: progress("download progress") or "downloaded-model",
            ) as download,
        ):
            app.refresh_models(auto_download=True)

        download.assert_called_once()
        events = [app.events.get_nowait() for _ in range(2)]
        self.assertEqual(events[0], ("model_download", "download progress"))
        self.assertEqual(events[1][0], "models")
        self.assertEqual(events[1][1]["model_path"], "downloaded-model")
        self.assertEqual(events[1][1]["trained"], [])
        self.assertIsNone(events[1][1]["model_error"])


if __name__ == "__main__":
    unittest.main()
