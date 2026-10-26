import hmac
import json
import os
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import local_model

SERVER_TOKEN = os.environ.get("MYAI_SERVER_TOKEN", "")
SERVER_PORT = int(os.environ.get("MYAI_SERVER_PORT", "8765"))
MAX_REQUEST_BYTES = 8 * 1024 * 1024
local_model.MODEL_CACHE_DIR = Path(
    os.environ.get("MYAI_MODEL_CACHE", "/var/lib/myai/models")
)


def valid_chat_payload(payload):
    if not isinstance(payload, dict):
        return False
    model = payload.get("model")
    messages = payload.get("messages")
    return (
        isinstance(model, str)
        and bool(model.strip())
        and len(model) <= 256
        and isinstance(messages, list)
        and bool(messages)
        and all(
            isinstance(message, dict)
            and isinstance(message.get("role"), str)
            and message.get("role") in {"system", "user", "assistant"}
            and isinstance(message.get("content"), str)
            for message in messages
        )
    )


class MyAIHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, _format, *_args):
        return

    def _send_json(self, status, payload):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _authorized(self):
        authorization = self.headers.get("Authorization", "")
        supplied = authorization[7:] if authorization.startswith("Bearer ") else ""
        return bool(SERVER_TOKEN) and hmac.compare_digest(supplied, SERVER_TOKEN)

    def do_GET(self):
        if self.path != "/api/tags":
            self._send_json(404, {"error": "Not found"})
            return
        if not self._authorized():
            self._send_json(401, {"error": "Unauthorized"})
            return
        try:
            self._send_json(
                200,
                {"models": [{"name": local_model.MODEL_ID}]},
            )
        except (OSError, ValueError) as error:
            self._send_json(500, {"error": f"Could not list models: {error}"})

    def do_POST(self):
        if self.path != "/api/chat":
            self._send_json(404, {"error": "Not found"})
            return
        if not self._authorized():
            self._send_json(401, {"error": "Unauthorized"})
            return
        try:
            content_length = int(self.headers.get("Content-Length", ""))
        except ValueError:
            self._send_json(400, {"error": "Invalid Content-Length"})
            return
        if content_length < 1 or content_length > MAX_REQUEST_BYTES:
            self._send_json(413, {"error": "Request body too large or empty"})
            return
        try:
            body = self.rfile.read(content_length)
            payload = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            self._send_json(400, {"error": "Invalid JSON"})
            return
        if not valid_chat_payload(payload):
            self._send_json(400, {"error": "Invalid messages"})
            return
        if payload["model"] != local_model.MODEL_ID:
            self._send_json(400, {"error": "Unknown model"})
            return
        try:
            model_path = local_model.find_downloaded_model()
            if model_path is None:
                model_path = local_model.download_model()
            answer = local_model.generate_model(model_path, payload["messages"])
        except (ImportError, OSError, RuntimeError, ValueError) as error:
            self._send_json(502, {"error": f"Local model unavailable: {error}"})
            return
        body = json.dumps(
            {"message": {"content": answer}, "done": True}
        ).encode("utf-8") + b"\n"
        self.send_response(200)
        self.send_header("Content-Type", "application/x-ndjson")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)


def main():
    if not SERVER_TOKEN or len(SERVER_TOKEN) < 32:
        raise SystemExit("Set MYAI_SERVER_TOKEN to a random secret of at least 32 characters.")
    server = ThreadingHTTPServer(("127.0.0.1", SERVER_PORT), MyAIHandler)
    print(f"MyAI local model server listening on 127.0.0.1:{SERVER_PORT}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
