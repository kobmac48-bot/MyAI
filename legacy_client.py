import json
import os
import queue
import ssl
import threading
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, scrolledtext, ttk
from urllib.parse import urlsplit
from urllib.request import HTTPSHandler, HTTPRedirectHandler, Request, build_opener

import certifi


if os.environ.get("APPDATA"):
    DATA_DIR = Path(os.environ["APPDATA"]) / "MyAI"
else:
    DATA_DIR = Path.home() / "MyAI"
SETTINGS_FILE = DATA_DIR / "remote-server.json"
TLS_CONTEXT = ssl.create_default_context(cafile=certifi.where())


class NoRedirectHandler(HTTPRedirectHandler):
    def redirect_request(self, request, response, code, message, headers, new_url):
        return None


HTTPS_OPENER = build_opener(HTTPSHandler(context=TLS_CONTEXT), NoRedirectHandler())


def valid_server_url(value):
    try:
        parsed = urlsplit(value.strip())
        port = parsed.port
    except ValueError:
        return False
    return (
        parsed.scheme == "https"
        and parsed.hostname is not None
        and parsed.username is None
        and parsed.password is None
        and parsed.path in {"", "/"}
        and parsed.query == ""
        and parsed.fragment == ""
        and (port is None or 1 <= port <= 65535)
    )


class LegacyMyAI:
    def __init__(self, root):
        self.root = root
        self.root.title("MyAI - Server")
        self.root.geometry("800x620")
        self.root.minsize(620, 460)
        self.root.configure(bg="#111318")
        self.events = queue.Queue()
        self.messages = []
        self.busy = False
        self.models = []
        self.model = tk.StringVar()
        self.status = tk.StringVar(value="Server noch nicht eingerichtet")
        self.server_url = ""
        self.server_token = ""
        self._load_settings()
        self._build_ui()
        self.root.after(50, self._process_events)
        if self.server_url and self.server_token:
            self.refresh_models()
        else:
            self.root.after(200, self.open_settings)

    def _load_settings(self):
        try:
            if SETTINGS_FILE.is_file():
                settings = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
                if not isinstance(settings, dict):
                    raise ValueError("Die Server-Einstellungen muessen ein JSON-Objekt sein.")
                self.server_url = settings.get("server_url", "")
                self.server_token = settings.get("server_token", "")
                if not isinstance(self.server_url, str) or not isinstance(
                    self.server_token, str
                ):
                    raise ValueError("Server-Adresse oder Zugriffstoken ist ungueltig.")
                if self.server_url and not valid_server_url(self.server_url):
                    raise ValueError("Die Server-Adresse muss eine gueltige HTTPS-Adresse sein.")
        except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as error:
            self.root.after(
                100,
                lambda error=error: messagebox.showerror(
                    "Server-Einstellungen konnten nicht geladen werden",
                    str(error),
                    parent=self.root,
                ),
            )

    def _build_ui(self):
        header = tk.Frame(self.root, bg="#181b22", padx=18, pady=12)
        header.pack(fill="x")
        tk.Label(
            header,
            text="MyAI",
            font=("Segoe UI", 18, "bold"),
            fg="#f4f5f7",
            bg="#181b22",
        ).pack(side="left")
        tk.Label(
            header,
            textvariable=self.status,
            font=("Segoe UI", 9),
            fg="#aab2c0",
            bg="#181b22",
        ).pack(side="left", padx=14)
        tk.Button(
            header,
            text="Server einstellen",
            command=self.open_settings,
        ).pack(side="right")

        model_bar = tk.Frame(self.root, bg="#111318", padx=18, pady=10)
        model_bar.pack(fill="x")
        tk.Label(
            model_bar,
            text="MODELL",
            font=("Segoe UI", 8, "bold"),
            fg="#8992a3",
            bg="#111318",
        ).pack(side="left", padx=(0, 10))
        self.model_picker = ttk.Combobox(
            model_bar, textvariable=self.model, state="readonly", width=35
        )
        self.model_picker.pack(side="left")
        self.refresh_button = tk.Button(
            model_bar,
            text="Modelle laden",
            command=self.refresh_models,
        )
        self.refresh_button.pack(side="left", padx=8)

        self.chat = scrolledtext.ScrolledText(
            self.root,
            wrap="word",
            state="disabled",
            bg="#181b22",
            fg="#e6e8ed",
            insertbackground="#e6e8ed",
            relief="flat",
            borderwidth=0,
            padx=16,
            pady=14,
            font=("Segoe UI", 10),
        )
        self.chat.pack(fill="both", expand=True, padx=18, pady=(4, 10))
        self.chat.tag_configure("user", foreground="#8fc6ff", font=("Segoe UI", 10, "bold"))
        self.chat.tag_configure(
            "assistant", foreground="#a8e6bd", font=("Segoe UI", 10, "bold")
        )
        self.chat.tag_configure("body", foreground="#e6e8ed", font=("Segoe UI", 10))
        self.chat.tag_configure("hint", foreground="#929bad", font=("Segoe UI", 9))
        self._append_text(
            "MyAI verbindet sich ueber HTTPS mit deinem Ollama-Server. "
            "Deine Nachrichten werden auf diesem Server verarbeitet.\n",
            "hint",
        )

        composer = tk.Frame(self.root, bg="#111318", padx=18, pady=12)
        composer.pack(fill="x")
        self.prompt = tk.Text(
            composer,
            height=3,
            wrap="word",
            bg="#20232b",
            fg="#f2f3f5",
            insertbackground="#f2f3f5",
            relief="flat",
            padx=12,
            pady=10,
            font=("Segoe UI", 10),
        )
        self.prompt.pack(side="left", fill="both", expand=True)
        self.prompt.bind("<Control-Return>", self._send_from_keyboard)
        self.send_button = tk.Button(
            composer,
            text="Senden",
            command=self.send_message,
            padx=14,
            pady=10,
        )
        self.send_button.pack(side="left", padx=(10, 0), anchor="s")

    def _append_text(self, text, tag):
        self.chat.configure(state="normal")
        self.chat.insert("end", text, tag)
        self.chat.see("end")
        self.chat.configure(state="disabled")

    def _send_from_keyboard(self, _event):
        self.send_message()
        return "break"

    def open_settings(self):
        dialog = tk.Toplevel(self.root)
        dialog.title("MyAI-Server")
        dialog.geometry("560x280")
        dialog.resizable(False, False)
        dialog.configure(bg="#111318")
        dialog.transient(self.root)
        dialog.grab_set()
        content = tk.Frame(dialog, bg="#111318", padx=20, pady=16)
        content.pack(fill="both", expand=True)
        tk.Label(
            content,
            text="Ollama-Server verbinden",
            font=("Segoe UI", 13, "bold"),
            fg="#f4f5f7",
            bg="#111318",
        ).pack(anchor="w")
        tk.Label(
            content,
            text=(
                "Adresse und Zugriffstoken erhaeltst du von der Person, die den "
                "MyAI-Server betreibt. Verwende ausschliesslich eine HTTPS-Adresse."
            ),
            font=("Segoe UI", 9),
            fg="#aab2c0",
            bg="#111318",
            wraplength=510,
            justify="left",
        ).pack(anchor="w", pady=(6, 12))

        url_var = tk.StringVar(value=self.server_url)
        token_var = tk.StringVar(value=self.server_token)
        for label, variable, hidden in (
            ("Server-Adresse (z. B. https://myai.example.com)", url_var, ""),
            ("Zugriffstoken", token_var, "*"),
        ):
            tk.Label(
                content,
                text=label,
                font=("Segoe UI", 9, "bold"),
                fg="#e5e7eb",
                bg="#111318",
            ).pack(anchor="w", pady=(4, 3))
            tk.Entry(
                content,
                textvariable=variable,
                show=hidden,
                bg="#20232b",
                fg="#f2f3f5",
                insertbackground="#f2f3f5",
                relief="flat",
                font=("Segoe UI", 10),
            ).pack(fill="x", ipady=7)

        buttons = tk.Frame(content, bg="#111318")
        buttons.pack(fill="x", pady=(14, 0))

        def save():
            server_url = url_var.get().strip().rstrip("/")
            token = token_var.get().strip()
            if not valid_server_url(server_url):
                messagebox.showerror(
                    "Ungueltige Server-Adresse",
                    "Die Server-Adresse muss HTTPS verwenden, zum Beispiel "
                    "https://myai.example.com.",
                    parent=dialog,
                )
                return
            if len(token) < 32:
                messagebox.showerror(
                    "Ungueltiges Zugriffstoken",
                    "Das Zugriffstoken muss mindestens 32 Zeichen lang sein.",
                    parent=dialog,
                )
                return
            try:
                DATA_DIR.mkdir(parents=True, exist_ok=True)
                descriptor = os.open(
                    str(SETTINGS_FILE),
                    os.O_WRONLY | os.O_CREAT | os.O_TRUNC,
                    0o600,
                )
                with os.fdopen(descriptor, "w", encoding="utf-8") as settings:
                    json.dump(
                        {"server_url": server_url, "server_token": token},
                        settings,
                        ensure_ascii=True,
                        indent=2,
                    )
            except OSError as error:
                messagebox.showerror(
                    "Server-Einstellungen konnten nicht gespeichert werden",
                    str(error),
                    parent=dialog,
                )
                return
            self.server_url = server_url
            self.server_token = token
            dialog.destroy()
            self.refresh_models()

        tk.Button(buttons, text="Speichern und verbinden", command=save).pack(side="left")
        tk.Button(buttons, text="Abbrechen", command=dialog.destroy).pack(side="right")

    def _request(self, path, data=None):
        headers = {"Authorization": "Bearer " + self.server_token}
        if data is not None:
            headers["Content-Type"] = "application/json"
            data = json.dumps(data).encode("utf-8")
        request = Request(self.server_url + path, data=data, headers=headers)
        return HTTPS_OPENER.open(request, timeout=600)

    def refresh_models(self):
        if self.busy or not self.server_url or not self.server_token:
            return
        self.status.set("Lade Modelle vom Server...")
        self.refresh_button.configure(state="disabled")

        def load():
            try:
                with self._request("/api/tags") as response:
                    result = json.loads(response.read().decode("utf-8"))
                names = [
                    item["name"]
                    for item in result.get("models", [])
                    if isinstance(item, dict) and item.get("name")
                ]
                self.events.put(("models", names))
            except (OSError, ValueError) as error:
                self.events.put(("error", str(error)))

        threading.Thread(target=load, daemon=True).start()

    def send_message(self):
        if self.busy:
            return
        text = self.prompt.get("1.0", "end").strip()
        model = self.model.get()
        if not text:
            return
        if not model:
            self.status.set("Kein Modell gefunden. Verbinde den Server und lade Modelle.")
            return
        self.prompt.delete("1.0", "end")
        self._append_text("Du\n", "user")
        self._append_text(text + "\n\n", "body")
        self.messages.append({"role": "user", "content": text})
        self.busy = True
        self.send_button.configure(state="disabled")
        self.refresh_button.configure(state="disabled")
        self.status.set(model + " antwortet...")
        self._append_text("MyAI\n", "assistant")
        messages = list(self.messages)

        def generate():
            try:
                with self._request(
                    "/api/chat",
                    {"model": model, "messages": messages, "stream": True},
                ) as response:
                    answer = []
                    for line in response:
                        if not line.strip():
                            continue
                        result = json.loads(line.decode("utf-8"))
                        if result.get("error"):
                            raise RuntimeError(result["error"])
                        chunk = result.get("message", {}).get("content", "")
                        if chunk:
                            answer.append(chunk)
                            self.events.put(("chunk", chunk))
                self.events.put(("complete", "".join(answer)))
            except (OSError, ValueError, RuntimeError) as error:
                self.events.put(("error", str(error)))

        threading.Thread(target=generate, daemon=True).start()

    def _process_events(self):
        try:
            while True:
                event, data = self.events.get_nowait()
                if event == "models":
                    self.models = data
                    self.model_picker.configure(values=data)
                    if self.model.get() not in data and data:
                        self.model.set("llama3.1" if "llama3.1" in data else data[0])
                    self.status.set(
                        "{} Modell(e) verfuegbar".format(len(data))
                        if data
                        else "Keine Modelle auf dem Server gefunden."
                    )
                    self.refresh_button.configure(state="normal")
                elif event == "chunk":
                    self._append_text(data, "body")
                elif event == "complete":
                    self._append_text("\n\n", "body")
                    self.messages.append({"role": "assistant", "content": data})
                    self.busy = False
                    self.send_button.configure(state="normal")
                    self.refresh_button.configure(state="normal")
                    self.status.set(self.model.get() + " ist bereit")
                elif event == "error":
                    self._append_text("\nFehler: " + data + "\n\n", "hint")
                    self.busy = False
                    self.send_button.configure(state="normal")
                    self.refresh_button.configure(state="normal")
                    self.status.set("Serveranfrage fehlgeschlagen.")
        except queue.Empty:
            pass
        self.root.after(50, self._process_events)


def main():
    root = tk.Tk()
    LegacyMyAI(root)
    root.mainloop()


if __name__ == "__main__":
    main()
