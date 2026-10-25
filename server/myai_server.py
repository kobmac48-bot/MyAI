import hmac
import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://127.0.0.1:11434").rstrip("/")
SERVER_TOKEN = os.environ.get("MYAI_SERVER_TOKEN", "")
SERVER_PORT = int(os.environ.get("MYAI_SERVER_PORT", "8765"))
MAX_REQUEST_BYTES = 8 * 1024 * 1024


def valid_ollama_url(value):
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError:
        return False
    return (
        parsed.scheme == "http"
        and parsed.hostname in {"127.0.0.1", "localhost"}
        and parsed.username is None
        and parsed.password is None
        and parsed.path in {"", "/"}
        and not parsed.query
        and not parsed.fragment
        and (port is None or 1 <= port <= 65535)
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


def ollama_request(path, body=None):
    headers = {"Content-Type": "application/json"} if body is not None else {}
    request = Request(
        f"{OLLAMA_URL}{path}",
        data=body,
        headers=headers,
        method="POST" if body is not None else "GET",
    )
    return urlopen(request, timeout=60 if body is None else 600)


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
            with ollama_request("/api/tags") as response:
                body = response.read(MAX_REQUEST_BYTES + 1)
            if len(body) > MAX_REQUEST_BYTES:
                self._send_json(502, {"error": "Ollama response too large"})
                return
        except (HTTPError, URLError, OSError) as error:
            self._send_json(502, {"error": f"Ollama unavailable: {error}"})
            return
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

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
        try:
            upstream = ollama_request("/api/chat", body)
        except HTTPError as error:
            try:
                response_body = error.read(MAX_REQUEST_BYTES)
            except OSError:
                response_body = b""
            self.send_response(error.code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(response_body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(response_body)
            return
        except (URLError, OSError) as error:
            self._send_json(502, {"error": f"Ollama unavailable: {error}"})
            return
        with upstream:
            self.send_response(200)
            self.send_header(
                "Content-Type",
                upstream.headers.get("Content-Type", "application/x-ndjson"),
            )
            self.send_header("Cache-Control", "no-store")
            self.send_header("Connection", "close")
            self.end_headers()
            self.close_connection = True
            while True:
                chunk = upstream.read(64 * 1024)
                if not chunk:
                    break
                self.wfile.write(chunk)
                self.wfile.flush()


def main():
    if not SERVER_TOKEN or len(SERVER_TOKEN) < 32:
        raise SystemExit("Set MYAI_SERVER_TOKEN to a random secret of at least 32 characters.")
    if not valid_ollama_url(OLLAMA_URL):
        raise SystemExit("OLLAMA_URL must point to Ollama on localhost.")
    server = ThreadingHTTPServer(("127.0.0.1", SERVER_PORT), MyAIHandler)
    print(f"MyAI Ollama proxy listening on 127.0.0.1:{SERVER_PORT}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
