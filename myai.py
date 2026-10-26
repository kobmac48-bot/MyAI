import json
import os
import re
import queue
import runpy
import subprocess
import sys
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from urllib.parse import urlsplit
import urllib.error
import urllib.request
import tkinter as tk
from tkinter import filedialog, messagebox, scrolledtext, ttk

import local_model

APP_DIR = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
if getattr(sys, "frozen", False):
    if sys.platform == "win32":
        DATA_DIR = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local")) / "MyAI"
    elif sys.platform == "darwin":
        DATA_DIR = Path.home() / "Library" / "Application Support" / "MyAI"
    else:
        DATA_DIR = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share")) / "myai"
else:
    DATA_DIR = APP_DIR
TRAINED_MODELS_DIR = DATA_DIR / "trained_models"
local_model.MODEL_CACHE_DIR = DATA_DIR / "models"
DISCORD_SETTINGS_FILE = DATA_DIR / "discord-webhook.json"
AI_PROVIDER_SETTINGS_FILE = DATA_DIR / "ai-provider-keys.json"


def is_valid_discord_webhook(url):
    try:
        if any(character.isspace() for character in url):
            return False
        parsed = urlsplit(url.strip())
        port = parsed.port
    except ValueError:
        return False
    return (
        parsed.scheme == "https"
        and parsed.hostname in {"discord.com", "discordapp.com"}
        and parsed.username is None
        and parsed.password is None
        and port is None
        and not parsed.query
        and not parsed.fragment
        and re.fullmatch(r"/api/webhooks/\d+/[A-Za-z0-9._-]+/?", parsed.path) is not None
    )


class NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, response, code, message, headers, new_url):
        return None


def load_ai_provider_keys():
    if not AI_PROVIDER_SETTINGS_FILE.is_file():
        return {"openai": "", "anthropic": ""}
    settings = json.loads(AI_PROVIDER_SETTINGS_FILE.read_text(encoding="utf-8"))
    if not isinstance(settings, dict):
        raise ValueError("KI-Zugangsdaten muessen ein JSON-Objekt sein.")
    keys = {}
    for provider in ("openai", "anthropic"):
        key = settings.get(provider, "")
        if not isinstance(key, str):
            raise ValueError(f"Der {provider}-API-Schluessel ist ungueltig.")
        keys[provider] = key
    return keys


def save_ai_provider_keys(keys):
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    file_descriptor = os.open(
        str(AI_PROVIDER_SETTINGS_FILE),
        os.O_WRONLY | os.O_CREAT | os.O_TRUNC,
        0o600,
    )
    with os.fdopen(file_descriptor, "w", encoding="utf-8") as settings_file:
        json.dump(keys, settings_file, ensure_ascii=True, indent=2)


def _provider_request(url, payload, headers):
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    opener = urllib.request.build_opener(NoRedirectHandler())
    try:
        with opener.open(request, timeout=120) as response:
            result = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        try:
            detail = json.loads(error.read().decode("utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            detail = {}
        if not isinstance(detail, dict):
            detail = {}
        message = detail.get("error", {})
        if isinstance(message, dict):
            message = message.get("message", str(message))
        raise RuntimeError(f"HTTP {error.code}: {message or error.reason}") from error
    except (json.JSONDecodeError, UnicodeDecodeError) as error:
        raise RuntimeError("Der KI-Anbieter hat eine ungueltige Antwort gesendet.") from error
    return result


def ask_openai(api_key, messages):
    result = _provider_request(
        "https://api.openai.com/v1/chat/completions",
        {"model": "gpt-4.1-mini", "messages": messages, "max_tokens": 1200},
        {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
    )
    try:
        return result["choices"][0]["message"]["content"].strip()
    except (KeyError, IndexError, TypeError, AttributeError) as error:
        raise RuntimeError("OpenAI hat keine lesbare Textantwort geliefert.") from error


def ask_anthropic(api_key, messages):
    result = _provider_request(
        "https://api.anthropic.com/v1/messages",
        {"model": "claude-haiku-5-5", "messages": messages, "max_tokens": 1200},
        {
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "Content-Type": "application/json",
        },
    )
    try:
        return "\n".join(
            block["text"] for block in result["content"] if block.get("type") == "text"
        ).strip()
    except (KeyError, TypeError, AttributeError) as error:
        raise RuntimeError("Claude hat keine lesbare Textantwort geliefert.") from error


def split_discord_message(content, max_length=1900):
    chunks = []
    while len(content) > max_length:
        split_at = content.rfind("\n", 0, max_length)
        if split_at < max_length // 2:
            split_at = max_length
        chunks.append(content[:split_at])
        content = content[split_at:]
    if content:
        chunks.append(content)
    return chunks


class MyAI:
    def __init__(self, root):
        self.root = root
        self.root.title("MyAI")
        self.root.geometry("980x720")
        self.root.minsize(720, 520)
        self.root.configure(bg="#111318")

        self.messages = []
        self.events = queue.Queue()
        self.busy = False
        self.training_running = False
        self.training_process = None
        self.training_window = None
        self.training_log = None
        self.training_start_button = None
        self.training_stop_button = None
        self.close_training_when_done = False
        self.model_sources = {}
        self.model = tk.StringVar()
        self.collaboration_enabled = tk.BooleanVar(value=False)
        self.status = tk.StringVar(value="Lade lokales Modell...")
        self.model_download_running = False
        self.discord_webhook = ""
        self.provider_keys = {"openai": "", "anthropic": ""}
        self.pending_discord_task = ""
        self.pending_discord_model = ""
        try:
            if DISCORD_SETTINGS_FILE.is_file():
                settings = json.loads(DISCORD_SETTINGS_FILE.read_text(encoding="utf-8"))
                if not isinstance(settings, dict):
                    raise ValueError("Discord-Einstellungen muessen ein JSON-Objekt sein.")
                webhook = settings.get("webhook_url", "")
                if not isinstance(webhook, str) or (webhook and not is_valid_discord_webhook(webhook)):
                    raise ValueError("Die gespeicherte Discord-Webhook-URL ist ungueltig.")
                self.discord_webhook = webhook
        except (OSError, json.JSONDecodeError, ValueError) as error:
            self.root.after(
                100,
                lambda error=error: messagebox.showerror(
                    "Discord-Einstellungen konnten nicht geladen werden",
                    str(error),
                    parent=self.root,
                ),
            )
        try:
            self.provider_keys = load_ai_provider_keys()
        except (OSError, json.JSONDecodeError, ValueError) as error:
            self.root.after(
                100,
                lambda error=error: messagebox.showerror(
                    "KI-Zugangsdaten konnten nicht geladen werden",
                    str(error),
                    parent=self.root,
                ),
            )

        self._configure_styles()
        self._build_ui()
        self.root.after(50, self._process_events)
        self.refresh_models(auto_download=True)

    def _configure_styles(self):
        style = ttk.Style()
        style.theme_use("clam")
        style.configure(
            "MyAI.TCombobox",
            fieldbackground="#20232b",
            background="#20232b",
            foreground="#f2f3f5",
            arrowcolor="#f2f3f5",
            bordercolor="#343944",
            lightcolor="#343944",
            darkcolor="#343944",
            padding=8,
        )
        style.map(
            "MyAI.TCombobox",
            fieldbackground=[("readonly", "#20232b")],
            foreground=[("readonly", "#f2f3f5")],
        )

    def _build_ui(self):
        header = tk.Frame(self.root, bg="#181b22", padx=24, pady=16)
        header.pack(fill="x")

        title_area = tk.Frame(header, bg="#181b22")
        title_area.pack(side="left")
        tk.Label(
            title_area,
            text="MyAI",
            font=("Segoe UI", 20, "bold"),
            fg="#f4f5f7",
            bg="#181b22",
        ).pack(anchor="w")
        tk.Label(
            title_area,
            text="Dein privater KI-Chat auf diesem PC",
            font=("Segoe UI", 10),
            fg="#9ba3b4",
            bg="#181b22",
        ).pack(anchor="w", pady=(2, 0))

        status_area = tk.Frame(header, bg="#181b22")
        status_area.pack(side="right", pady=8)
        tk.Label(
            status_area,
            textvariable=self.status,
            font=("Segoe UI", 9),
            fg="#aab2c0",
            bg="#181b22",
        ).pack(side="left", padx=(0, 12))
        self.refresh_button = tk.Button(
            status_area,
            text="Modelle laden",
            command=lambda: self.refresh_models(auto_download=True),
            font=("Segoe UI", 9),
            fg="#e5e7eb",
            bg="#292e38",
            activebackground="#373e4b",
            activeforeground="#ffffff",
            relief="flat",
            padx=12,
            pady=7,
            cursor="hand2",
        )
        self.refresh_button.pack(side="left")
        self.train_button = tk.Button(
            status_area,
            text="Eigenes Modell trainieren",
            command=self.open_training_dialog,
            font=("Segoe UI", 9),
            fg="#111318",
            bg="#a8e6bd",
            activebackground="#8fd5a9",
            activeforeground="#111318",
            relief="flat",
            padx=12,
            pady=7,
            cursor="hand2",
        )
        self.train_button.pack(side="left", padx=(8, 0))

        model_bar = tk.Frame(self.root, bg="#111318", padx=24, pady=14)
        model_bar.pack(fill="x")
        tk.Label(
            model_bar,
            text="MODELL",
            font=("Segoe UI", 8, "bold"),
            fg="#8992a3",
            bg="#111318",
        ).pack(side="left", padx=(0, 12))
        self.model_picker = ttk.Combobox(
            model_bar,
            textvariable=self.model,
            state="readonly",
            width=36,
            style="MyAI.TCombobox",
        )
        self.model_picker.pack(side="left")
        tk.Checkbutton(
            model_bar,
            text="ChatGPT + Claude",
            variable=self.collaboration_enabled,
            font=("Segoe UI", 9),
            fg="#e5e7eb",
            bg="#111318",
            activeforeground="#ffffff",
            activebackground="#111318",
            selectcolor="#20232b",
            relief="flat",
        ).pack(side="left", padx=(12, 0))
        self.provider_button = tk.Button(
            model_bar,
            text="KI-Zugangsdaten",
            command=self.open_ai_provider_dialog,
            font=("Segoe UI", 9),
            fg="#e5e7eb",
            bg="#292e38",
            activebackground="#373e4b",
            activeforeground="#ffffff",
            relief="flat",
            padx=12,
            pady=7,
            cursor="hand2",
        )
        self.provider_button.pack(side="right", padx=(8, 0))
        self.discord_button = tk.Button(
            model_bar,
            text=self._discord_button_label(),
            command=self.open_discord_dialog,
            font=("Segoe UI", 9),
            fg="#e5e7eb",
            bg="#292e38",
            activebackground="#373e4b",
            activeforeground="#ffffff",
            relief="flat",
            padx=12,
            pady=7,
            cursor="hand2",
        )
        self.discord_button.pack(side="right")

        chat_frame = tk.Frame(self.root, bg="#111318", padx=24)
        chat_frame.pack(fill="both", expand=True)
        self.chat = scrolledtext.ScrolledText(
            chat_frame,
            wrap="word",
            state="disabled",
            bg="#181b22",
            fg="#e6e8ed",
            insertbackground="#e6e8ed",
            selectbackground="#394354",
            relief="flat",
            borderwidth=0,
            padx=20,
            pady=18,
            font=("Segoe UI", 11),
            spacing1=3,
            spacing3=9,
        )
        self.chat.pack(fill="both", expand=True)
        self.chat.tag_configure("user", foreground="#8fc6ff", font=("Segoe UI", 10, "bold"))
        self.chat.tag_configure("assistant", foreground="#a8e6bd", font=("Segoe UI", 10, "bold"))
        self.chat.tag_configure("body", foreground="#e6e8ed", font=("Segoe UI", 11))
        self.chat.tag_configure("hint", foreground="#929bad", font=("Segoe UI", 10))
        self._append_text(
            "Willkommen bei MyAI\n",
            "assistant",
        )
        self._append_text(
            "Ein lokal gespeichertes Open-Source-Modell und eigene, lokal trainierte Modelle werden unterstützt. "
            "Der Chatverlauf bleibt nur während dieser Sitzung im Arbeitsspeicher.\n",
            "hint",
        )

        composer = tk.Frame(self.root, bg="#111318", padx=24, pady=16)
        composer.pack(fill="x")
        self.prompt = tk.Text(
            composer,
            height=3,
            wrap="word",
            bg="#20232b",
            fg="#f2f3f5",
            insertbackground="#f2f3f5",
            relief="flat",
            padx=14,
            pady=12,
            font=("Segoe UI", 11),
        )
        self.prompt.pack(side="left", fill="both", expand=True)
        self.prompt.insert("1.0", "")
        self.prompt.bind("<Control-Return>", self._send_from_keyboard)
        self.send_button = tk.Button(
            composer,
            text="Senden",
            command=self.send_message,
            font=("Segoe UI", 10, "bold"),
            fg="#111318",
            bg="#a8e6bd",
            activebackground="#8fd5a9",
            activeforeground="#111318",
            disabledforeground="#707785",
            relief="flat",
            padx=18,
            pady=12,
            cursor="hand2",
        )
        self.send_button.pack(side="left", padx=(12, 0), anchor="s")
        tk.Label(
            self.root,
            text="Enter zum Senden mit Strg + Enter",
            font=("Segoe UI", 8),
            fg="#747d8d",
            bg="#111318",
        ).pack(anchor="e", padx=25, pady=(0, 10))

    def _append_text(self, text, tag):
        self.chat.configure(state="normal")
        self.chat.insert("end", text, tag)
        self.chat.see("end")
        self.chat.configure(state="disabled")

    def _send_from_keyboard(self, _event):
        self.send_message()
        return "break"

    def open_ai_provider_dialog(self):
        dialog = tk.Toplevel(self.root)
        dialog.title("KI-Anbieter")
        dialog.geometry("620x390")
        dialog.resizable(False, False)
        dialog.configure(bg="#111318")
        dialog.transient(self.root)
        dialog.grab_set()

        content = tk.Frame(dialog, bg="#111318", padx=22, pady=18)
        content.pack(fill="both", expand=True)
        tk.Label(
            content,
            text="ChatGPT- und Claude-Zugangsdaten",
            font=("Segoe UI", 14, "bold"),
            fg="#f4f5f7",
            bg="#111318",
        ).pack(anchor="w")
        tk.Label(
            content,
            text=(
                "Bei aktivierter Zusammenarbeit sendet MyAI deinen Chatverlauf an OpenAI "
                "und Anthropic und nutzt die Antworten zur lokalen Zusammenfassung. "
                "Dafuer koennen API-Kosten entstehen. Die Schluessel werden lokal in einer "
                "nicht verschluesselten Datei gespeichert; teile diese Datei nicht."
            ),
            font=("Segoe UI", 9),
            fg="#aab2c0",
            bg="#111318",
            wraplength=570,
            justify="left",
        ).pack(anchor="w", pady=(8, 14))

        openai_key = tk.StringVar(value=self.provider_keys["openai"])
        anthropic_key = tk.StringVar(value=self.provider_keys["anthropic"])
        for label, variable in (
            ("OpenAI API-Schluessel", openai_key),
            ("Anthropic API-Schluessel", anthropic_key),
        ):
            tk.Label(
                content,
                text=label,
                font=("Segoe UI", 9, "bold"),
                fg="#e5e7eb",
                bg="#111318",
            ).pack(anchor="w", pady=(6, 4))
            tk.Entry(
                content,
                textvariable=variable,
                show="*",
                bg="#20232b",
                fg="#f2f3f5",
                insertbackground="#f2f3f5",
                relief="flat",
                font=("Segoe UI", 10),
            ).pack(fill="x", ipady=8)

        buttons = tk.Frame(content, bg="#111318")
        buttons.pack(fill="x", pady=(18, 0))

        def save_keys():
            keys = {
                "openai": openai_key.get().strip(),
                "anthropic": anthropic_key.get().strip(),
            }
            try:
                if any(keys.values()):
                    save_ai_provider_keys(keys)
                elif AI_PROVIDER_SETTINGS_FILE.exists():
                    AI_PROVIDER_SETTINGS_FILE.unlink()
            except OSError as error:
                messagebox.showerror(
                    "KI-Zugangsdaten konnten nicht gespeichert werden",
                    str(error),
                    parent=dialog,
                )
                return
            self.provider_keys = keys
            dialog.destroy()

        tk.Button(
            buttons,
            text="Lokal speichern",
            command=save_keys,
            font=("Segoe UI", 9, "bold"),
            fg="#111318",
            bg="#a8e6bd",
            activebackground="#8fd5a9",
            relief="flat",
            padx=12,
            pady=8,
        ).pack(side="left")
        tk.Button(
            buttons,
            text="Abbrechen",
            command=dialog.destroy,
            font=("Segoe UI", 9),
            fg="#e5e7eb",
            bg="#292e38",
            activebackground="#373e4b",
            relief="flat",
            padx=12,
            pady=8,
        ).pack(side="right")

    def _discord_button_label(self):
        return "Discord: aktiv" if self.discord_webhook else "Discord-Webhook einrichten"

    def open_discord_dialog(self):
        dialog = tk.Toplevel(self.root)
        dialog.title("Discord-Webhook")
        dialog.geometry("620x300")
        dialog.resizable(False, False)
        dialog.configure(bg="#111318")
        dialog.transient(self.root)
        dialog.grab_set()

        content = tk.Frame(dialog, bg="#111318", padx=22, pady=18)
        content.pack(fill="both", expand=True)
        tk.Label(
            content,
            text="Chatprotokoll an Discord senden",
            font=("Segoe UI", 14, "bold"),
            fg="#f4f5f7",
            bg="#111318",
        ).pack(anchor="w")
        tk.Label(
            content,
            text=(
                "Wenn aktiviert, sendet MyAI nach jeder fertigen Antwort deine Aufgabe "
                "(Nachricht) und die endgueltige Ausgabe an den Discord-Kanal dieser Webhook-URL. "
                "Interne Gedanken werden nicht bereitgestellt oder gesendet. "
                "Die URL wird nur lokal auf diesem PC gespeichert."
            ),
            font=("Segoe UI", 9),
            fg="#aab2c0",
            bg="#111318",
            wraplength=570,
            justify="left",
        ).pack(anchor="w", pady=(8, 14))

        webhook_url = tk.StringVar(value=self.discord_webhook)
        entry = tk.Entry(
            content,
            textvariable=webhook_url,
            show="*",
            bg="#20232b",
            fg="#f2f3f5",
            insertbackground="#f2f3f5",
            relief="flat",
            font=("Segoe UI", 10),
        )
        entry.pack(fill="x", ipady=9)
        entry.focus_set()

        buttons = tk.Frame(content, bg="#111318")
        buttons.pack(fill="x", pady=(18, 0))

        def save_webhook():
            url = webhook_url.get().strip()
            if not is_valid_discord_webhook(url):
                messagebox.showerror(
                    "Ungueltige Webhook-URL",
                    "Gib eine HTTPS-Webhook-URL von discord.com oder discordapp.com ein.",
                    parent=dialog,
                )
                return
            try:
                DATA_DIR.mkdir(parents=True, exist_ok=True)
                settings = json.dumps({"webhook_url": url}, ensure_ascii=True, indent=2)
                file_descriptor = os.open(
                    str(DISCORD_SETTINGS_FILE),
                    os.O_WRONLY | os.O_CREAT | os.O_TRUNC,
                    0o600,
                )
                with os.fdopen(file_descriptor, "w", encoding="utf-8") as settings_file:
                    settings_file.write(settings)
            except OSError as error:
                messagebox.showerror(
                    "Webhook-Einstellungen konnten nicht gespeichert werden",
                    str(error),
                    parent=dialog,
                )
                return
            self.discord_webhook = url
            self.discord_button.configure(text=self._discord_button_label())
            dialog.destroy()

        def disable_webhook():
            try:
                if DISCORD_SETTINGS_FILE.exists():
                    DISCORD_SETTINGS_FILE.unlink()
            except OSError as error:
                messagebox.showerror(
                    "Webhook konnte nicht deaktiviert werden",
                    str(error),
                    parent=dialog,
                )
                return
            self.discord_webhook = ""
            self.discord_button.configure(text=self._discord_button_label())
            dialog.destroy()

        tk.Button(
            buttons,
            text="Speichern und aktivieren",
            command=save_webhook,
            font=("Segoe UI", 9, "bold"),
            fg="#111318",
            bg="#a8e6bd",
            activebackground="#8fd5a9",
            relief="flat",
            padx=12,
            pady=8,
        ).pack(side="left")
        tk.Button(
            buttons,
            text="Deaktivieren",
            command=disable_webhook,
            font=("Segoe UI", 9),
            fg="#e5e7eb",
            bg="#292e38",
            activebackground="#373e4b",
            relief="flat",
            padx=12,
            pady=8,
        ).pack(side="left", padx=(8, 0))
        tk.Button(
            buttons,
            text="Abbrechen",
            command=dialog.destroy,
            font=("Segoe UI", 9),
            fg="#e5e7eb",
            bg="#292e38",
            activebackground="#373e4b",
            relief="flat",
            padx=12,
            pady=8,
        ).pack(side="right")

    def _send_discord_log(self, task, answer, model):
        webhook = self.discord_webhook
        if not webhook:
            return
        content = (
            f"**MyAI - Aufgabe und Ausgabe**\n"
            f"**Modell:** {model}\n\n"
            f"**Aufgabe:**\n{task}\n\n"
            f"**Ausgabe:**\n{answer or '(Keine Ausgabe)'}"
        )
        chunks = split_discord_message(content)
        threading.Thread(
            target=self._post_discord_messages,
            args=(webhook, chunks),
            daemon=True,
        ).start()

    def _post_discord_messages(self, webhook, chunks):
        try:
            opener = urllib.request.build_opener(NoRedirectHandler())
            for index, chunk in enumerate(chunks, start=1):
                if len(chunks) > 1:
                    chunk = f"**MyAI-Log ({index}/{len(chunks)})**\n{chunk}"
                payload = json.dumps(
                    {"content": chunk, "allowed_mentions": {"parse": []}}
                ).encode("utf-8")
                request = urllib.request.Request(
                    webhook,
                    data=payload,
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with opener.open(request, timeout=15):
                    pass
        except urllib.error.HTTPError as error:
            self.events.put(("discord_error", f"Discord hat HTTP {error.code} zurueckgegeben."))
            return
        except (urllib.error.URLError, TimeoutError, OSError):
            self.events.put(("discord_error", "Discord-Webhook nicht erreichbar. Verbindung pruefen."))
            return
        self.events.put(("discord_sent", None))

    def open_training_dialog(self):
        if self.training_running:
            return
        if self.busy:
            self.status.set("Starte das Training, sobald die aktuelle Antwort fertig ist.")
            return

        dialog = tk.Toplevel(self.root)
        dialog.title("Eigenes Sprachmodell trainieren")
        dialog.geometry("740x760")
        dialog.minsize(650, 650)
        dialog.configure(bg="#111318")
        self.training_window = dialog

        content = tk.Frame(dialog, bg="#111318", padx=22, pady=18)
        content.pack(fill="both", expand=True)
        tk.Label(
            content,
            text="Sprachmodell von Grund auf trainieren",
            font=("Segoe UI", 15, "bold"),
            fg="#f4f5f7",
            bg="#111318",
        ).pack(anchor="w")
        tk.Label(
            content,
            text=(
                "Das Modell startet ohne vortrainiertes Wissen. Es lernt Textmuster aus deinen "
                ".txt-Dateien, wird aber nicht automatisch zu einem guten Chatbot."
            ),
            font=("Segoe UI", 9),
            fg="#aab2c0",
            bg="#111318",
            wraplength=690,
            justify="left",
        ).pack(anchor="w", pady=(6, 14))

        form = tk.Frame(content, bg="#111318")
        form.pack(fill="x")
        data_dir = tk.StringVar()
        model_name = tk.StringVar(value="mein-erstes-modell")
        settings = {
            "Epochen": tk.StringVar(value="20"),
            "Hidden size": tk.StringVar(value="128"),
            "Layer": tk.StringVar(value="2"),
            "Attention heads": tk.StringVar(value="4"),
            "Kontextlaenge": tk.StringVar(value="128"),
            "Vokabulargroesse": tk.StringVar(value="512"),
            "Batch size pro GPU": tk.StringVar(value="1"),
            "Gradient accumulation": tk.StringVar(value="2"),
        }

        tk.Label(
            form,
            text="Ordner mit Trainingsdaten (.txt, Unterordner eingeschlossen)",
            font=("Segoe UI", 9, "bold"),
            fg="#d8dbe2",
            bg="#111318",
        ).grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 5))
        folder_row = tk.Frame(form, bg="#111318")
        folder_row.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(0, 12))
        folder_row.columnconfigure(0, weight=1)
        tk.Entry(
            folder_row,
            textvariable=data_dir,
            bg="#20232b",
            fg="#f2f3f5",
            insertbackground="#f2f3f5",
            relief="flat",
            font=("Segoe UI", 10),
        ).grid(row=0, column=0, sticky="ew", ipady=8, padx=(0, 8))

        def browse_data():
            chosen = filedialog.askdirectory(parent=dialog, title="Trainingsdaten auswählen")
            if chosen:
                data_dir.set(chosen)

        tk.Button(
            folder_row,
            text="Ordner wählen",
            command=browse_data,
            font=("Segoe UI", 9),
            fg="#e5e7eb",
            bg="#292e38",
            relief="flat",
            padx=12,
            pady=7,
            cursor="hand2",
        ).grid(row=0, column=1)

        tk.Label(
            form,
            text="Modellname",
            font=("Segoe UI", 9, "bold"),
            fg="#d8dbe2",
            bg="#111318",
        ).grid(row=2, column=0, columnspan=2, sticky="w", pady=(0, 5))
        tk.Entry(
            form,
            textvariable=model_name,
            bg="#20232b",
            fg="#f2f3f5",
            insertbackground="#f2f3f5",
            relief="flat",
            font=("Segoe UI", 10),
        ).grid(row=3, column=0, columnspan=2, sticky="ew", ipady=8, pady=(0, 12))

        for index, (label, variable) in enumerate(settings.items()):
            row = 4 + index // 2
            column = index % 2
            field = tk.Frame(form, bg="#111318")
            field.grid(
                row=row,
                column=column,
                sticky="ew",
                padx=(0, 10) if column == 0 else (10, 0),
                pady=5,
            )
            tk.Label(
                field,
                text=label,
                font=("Segoe UI", 9),
                fg="#aab2c0",
                bg="#111318",
            ).pack(anchor="w", pady=(0, 4))
            tk.Entry(
                field,
                textvariable=variable,
                bg="#20232b",
                fg="#f2f3f5",
                insertbackground="#f2f3f5",
                relief="flat",
                font=("Segoe UI", 10),
            ).pack(fill="x", ipady=7)

        form.columnconfigure(0, weight=1)
        form.columnconfigure(1, weight=1)
        tk.Label(
            content,
            text=(
                "Das Training laeuft auf dem Rechner, auf dem MyAI gestartet wurde. Fuer eine "
                "GPU-Cloud startest du MyAI auf deinem selbst eingerichteten GPU-Server. "
                "Ohne CUDA-GPU ist das Training sehr langsam. Die Standardwerte sind ein "
                "kleiner Funktionstest, kein grosses Sprachmodell."
            ),
            font=("Segoe UI", 9),
            fg="#e1c58c",
            bg="#111318",
            wraplength=690,
            justify="left",
        ).pack(anchor="w", pady=(12, 10))

        self.training_log = scrolledtext.ScrolledText(
            content,
            height=10,
            wrap="word",
            state="disabled",
            bg="#181b22",
            fg="#d8dbe2",
            relief="flat",
            padx=10,
            pady=8,
            font=("Consolas", 9),
        )
        self.training_log.pack(fill="both", expand=True)
        controls = tk.Frame(content, bg="#111318")
        controls.pack(fill="x", pady=(12, 0))
        start_button = tk.Button(
            controls,
            text="Training starten",
            font=("Segoe UI", 10, "bold"),
            fg="#111318",
            bg="#a8e6bd",
            activebackground="#8fd5a9",
            relief="flat",
            padx=16,
            pady=9,
            cursor="hand2",
        )
        start_button.pack(side="left")
        stop_button = tk.Button(
            controls,
            text="Training abbrechen",
            command=self.stop_training,
            font=("Segoe UI", 9),
            fg="#e5e7eb",
            bg="#292e38",
            relief="flat",
            padx=12,
            pady=9,
            state="disabled",
        )
        stop_button.pack(side="left", padx=(8, 0))

        def start():
            directory = Path(data_dir.get()).expanduser()
            name = model_name.get().strip()
            if not directory.is_dir() or not any(directory.rglob("*.txt")):
                messagebox.showerror(
                    "Trainingsdaten fehlen",
                    "Waehle einen vorhandenen Ordner mit mindestens einer .txt-Datei.",
                    parent=dialog,
                )
                return
            if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,39}", name):
                messagebox.showerror(
                    "Ungueltiger Modellname",
                    "Verwende 1 bis 40 Buchstaben, Zahlen, Bindestriche oder Unterstriche.",
                    parent=dialog,
                )
                return

            try:
                values = {key: int(variable.get()) for key, variable in settings.items()}
            except ValueError:
                messagebox.showerror(
                    "Ungueltige Einstellungen",
                    "Alle Trainingseinstellungen muessen ganze Zahlen sein.",
                    parent=dialog,
                )
                return
            if (
                min(values.values()) < 1
                or values["Hidden size"] < 32
                or values["Kontextlaenge"] < 32
                or values["Vokabulargroesse"] < 256
            ):
                messagebox.showerror(
                    "Ungueltige Modellgroesse",
                    "Werte muessen positiv sein; Hidden size und Kontext mindestens 32, "
                    "Vokabulargroesse mindestens 256.",
                    parent=dialog,
                )
                return
            if values["Hidden size"] % values["Attention heads"]:
                messagebox.showerror(
                    "Ungueltige Modellgroesse",
                    "Hidden size muss durch die Anzahl der Attention heads teilbar sein.",
                    parent=dialog,
                )
                return
            try:
                TRAINED_MODELS_DIR.mkdir(parents=True, exist_ok=True)
            except OSError as error:
                messagebox.showerror("Modellordner konnte nicht erstellt werden", str(error), parent=dialog)
                return
            output_dir = TRAINED_MODELS_DIR / name
            if output_dir.exists():
                messagebox.showerror(
                    "Modell existiert bereits",
                    f"Der Zielordner existiert bereits:\n{output_dir}",
                    parent=dialog,
                )
                return

            command = [sys.executable]
            if getattr(sys, "frozen", False):
                command.append("--training-worker")
            else:
                command.append(str(APP_DIR / "train_from_scratch.py"))
            command.extend([
                "--data-dir",
                str(directory.resolve()),
                "--output-dir",
                str(output_dir),
                "--epochs",
                str(values["Epochen"]),
                "--hidden-size",
                str(values["Hidden size"]),
                "--layers",
                str(values["Layer"]),
                "--heads",
                str(values["Attention heads"]),
                "--sequence-length",
                str(values["Kontextlaenge"]),
                "--vocab-size",
                str(values["Vokabulargroesse"]),
                "--batch-size",
                str(values["Batch size pro GPU"]),
                "--gradient-accumulation",
                str(values["Gradient accumulation"]),
            ])
            try:
                process = subprocess.Popen(
                    command,
                    cwd=DATA_DIR,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    bufsize=1,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                )
            except OSError as error:
                messagebox.showerror("Training konnte nicht starten", str(error), parent=dialog)
                return

            self.training_process = process
            self.training_running = True
            start_button.configure(state="disabled")
            stop_button.configure(state="normal")
            self.send_button.configure(state="disabled")
            self.refresh_button.configure(state="disabled")
            self.train_button.configure(state="disabled")
            self.status.set(f"Trainiere {name}...")
            self._append_training_log(f"Starte Training fuer {name}...\n")
            threading.Thread(
                target=self._read_training_output,
                args=(process,),
                daemon=True,
            ).start()

        start_button.configure(command=start)
        self.training_start_button = start_button
        self.training_stop_button = stop_button

        def close_dialog():
            if self.training_running:
                if messagebox.askyesno(
                    "Training abbrechen?",
                    "Soll das laufende Training beendet werden?",
                    parent=dialog,
                ):
                    self.stop_training()
                    self.close_training_when_done = True
                return
            dialog.destroy()
            self.training_window = None
            self.training_log = None
            self.training_start_button = None
            self.training_stop_button = None

        dialog.protocol("WM_DELETE_WINDOW", close_dialog)

    def _append_training_log(self, text):
        if self.training_log is None or not self.training_log.winfo_exists():
            return
        self.training_log.configure(state="normal")
        self.training_log.insert("end", text)
        self.training_log.see("end")
        self.training_log.configure(state="disabled")

    def _read_training_output(self, process):
        if process.stdout is not None:
            for line in process.stdout:
                self.events.put(("training_log", line))
        self.events.put(("training_complete", process.wait()))

    def stop_training(self):
        if self.training_process is not None and self.training_process.poll() is None:
            self.training_process.terminate()

    def refresh_models(self, auto_download=False):
        if self.busy or self.training_running or self.model_download_running:
            return
        self.model_download_running = auto_download
        self.status.set("Lade lokale Modelle...")
        self.refresh_button.configure(state="disabled")

        def load():
            model_path = None
            model_error = None
            trained_error = None
            try:
                model_path = local_model.find_downloaded_model()
                if model_path is None and auto_download:
                    model_path = local_model.download_model(
                        lambda status: self.events.put(("model_download", status))
                    )
            except (ImportError, OSError, RuntimeError, ValueError) as error:
                model_error = str(error)
            try:
                trained = [
                    path
                    for path in sorted(TRAINED_MODELS_DIR.iterdir())
                    if path.is_dir() and (path / "config.json").is_file()
                ] if TRAINED_MODELS_DIR.is_dir() else []
            except OSError as error:
                trained_error = str(error)
                trained = []
            self.events.put(
                (
                    "models",
                    {
                        "model_path": model_path,
                        "trained": trained,
                        "model_error": model_error,
                        "trained_error": trained_error,
                    },
                )
            )

        threading.Thread(target=load, daemon=True).start()

    def send_message(self):
        if self.busy or self.training_running:
            return
        text = self.prompt.get("1.0", "end").strip()
        if not text:
            return
        collaborate = self.collaboration_enabled.get()
        provider_keys = dict(self.provider_keys)
        if collaborate and not all(provider_keys.values()):
            self.status.set("Bitte OpenAI- und Anthropic-Schluessel einrichten.")
            messagebox.showinfo(
                "KI-Zugangsdaten fehlen",
                "Fuer die Zusammenarbeit benoetigt MyAI sowohl einen OpenAI- als "
                "auch einen Anthropic-API-Schluessel.",
                parent=self.root,
            )
            self.open_ai_provider_dialog()
            return
        selection = self.model_sources.get(self.model.get())
        if selection is None:
            self.status.set("Kein Modell gefunden. Installiere ein Modell und lade erneut.")
            return
        model_type, model = selection
        self.pending_discord_task = text
        self.pending_discord_model = self.model.get()

        self.prompt.delete("1.0", "end")
        self._append_text("Du\n", "user")
        self._append_text(f"{text}\n\n", "body")
        self.messages.append({"role": "user", "content": text})
        self.busy = True
        self.send_button.configure(state="disabled")
        self.refresh_button.configure(state="disabled")
        self.train_button.configure(state="disabled")
        self.provider_button.configure(state="disabled")
        self.status.set("ChatGPT und Claude werden befragt..." if collaborate else f"{model} antwortet...")
        self._append_text("MyAI\n", "assistant")
        messages = list(self.messages)

        def generate():
            if collaborate:
                try:
                    request_messages = self._get_collaborative_messages(messages, provider_keys)
                    if model_type == "trained":
                        self._generate_trained_model(model, request_messages)
                    else:
                        self._generate_local_model(model, request_messages)
                except (
                    urllib.error.URLError,
                    TimeoutError,
                    OSError,
                    json.JSONDecodeError,
                    RuntimeError,
                ) as error:
                    self.events.put(("chat_error", str(error)))
                return
            if model_type == "trained":
                self._generate_trained_model(model, messages)
                return
            self._generate_local_model(model, messages)

        threading.Thread(target=generate, daemon=True).start()

    def _get_collaborative_messages(self, messages, provider_keys):
        providers = {
            "ChatGPT": (ask_openai, provider_keys["openai"]),
            "Claude": (ask_anthropic, provider_keys["anthropic"]),
        }
        answers = {}
        failures = {}
        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = {
                executor.submit(provider, key, messages): name
                for name, (provider, key) in providers.items()
            }
            for future in as_completed(futures):
                name = futures[future]
                try:
                    answers[name] = future.result()
                except (
                    urllib.error.URLError,
                    TimeoutError,
                    OSError,
                    json.JSONDecodeError,
                    RuntimeError,
                ) as error:
                    failures[name] = str(error)

        if not answers:
            details = "; ".join(f"{name}: {error}" for name, error in failures.items())
            raise RuntimeError(f"Keine externe KI konnte antworten. {details}")
        if failures:
            warning = "; ".join(f"{name}: {error}" for name, error in failures.items())
            self.events.put(("collaboration_warning", f"Ein Anbieter ist fehlgeschlagen: {warning}"))

        discussion = "\n\n".join(
            f"Antwort von {name}:\n{answer}" for name, answer in answers.items()
        )
        synthesis_request = (
            "Beantworte die aktuelle Nutzerfrage auf Deutsch. Nutze die folgenden "
            "Antworten von ChatGPT und Claude als Quellen, vergleiche sie kritisch, "
            "korrigiere Widersprueche soweit moeglich und gib eine klare, eigenstaendige "
            "Zusammenfassung. Behaupte nicht, dass du Dinge geprueft hast, die du nicht "
            "geprueft hast.\n\n"
            f"{discussion}"
        )
        combined_messages = list(messages)
        latest = combined_messages[-1]
        combined_messages[-1] = {
            **latest,
            "content": f"{latest['content']}\n\n{synthesis_request}",
        }
        return combined_messages

    def _generate_local_model(self, model_path, messages):
        try:
            answer = local_model.generate_model(model_path, messages)
            self.events.put(("chunk", answer))
            self.events.put(("complete", answer))
        except (ImportError, OSError, RuntimeError, ValueError, KeyError) as error:
            self.events.put(("chat_error", str(error)))

    def _generate_trained_model(self, model_path, messages):
        try:
            local_model.release_model()
            import torch
            from transformers import AutoModelForCausalLM, AutoTokenizer

            tokenizer = AutoTokenizer.from_pretrained(model_path, local_files_only=True)
            tokenizer.truncation_side = "left"
            model = AutoModelForCausalLM.from_pretrained(model_path, local_files_only=True)
            device = "cuda" if torch.cuda.is_available() else "cpu"
            model.to(device)
            model.eval()

            latest_question = next(
                message["content"]
                for message in reversed(messages)
                if message["role"] == "user"
            )
            prompt = f"Eingabe: {latest_question}\nAntwort:"
            context_length = getattr(
                model.config,
                "n_positions",
                getattr(model.config, "max_position_embeddings", 1024),
            )
            max_input_tokens = max(1, context_length // 2)
            inputs = tokenizer(
                prompt,
                return_tensors="pt",
                truncation=True,
                max_length=max_input_tokens,
            )
            input_ids = inputs["input_ids"].to(device)
            max_new_tokens = max(1, context_length - input_ids.shape[1])
            with torch.inference_mode():
                output = model.generate(
                    input_ids=input_ids,
                    max_new_tokens=max_new_tokens,
                    do_sample=False,
                    repetition_penalty=1.1,
                    pad_token_id=tokenizer.pad_token_id,
                    eos_token_id=tokenizer.eos_token_id,
                )
            answer = tokenizer.decode(
                output[0, input_ids.shape[1] :],
                skip_special_tokens=True,
            ).strip()
            self.events.put(("chunk", answer))
            self.events.put(("complete", answer))
        except (ImportError, OSError, RuntimeError, ValueError, KeyError) as error:
            self.events.put(("chat_error", str(error)))

    def _process_events(self):
        try:
            while True:
                event, data = self.events.get_nowait()
                if event == "models":
                    self.model_download_running = False
                    choices = {}
                    model_path = data["model_path"]
                    has_local_model = bool(model_path)
                    if model_path:
                        choices[local_model.MODEL_ID.rsplit("/", 1)[-1]] = (
                            "local",
                            model_path,
                        )
                    for trained_path in data["trained"]:
                        choices[f"MyAI: {trained_path.name}"] = ("trained", trained_path)
                    self.model_sources = choices
                    self.model_picker.configure(values=list(choices))
                    if choices:
                        if self.model.get() not in choices:
                            self.model.set(next(iter(choices)))
                        self.status.set(
                            f"{int(has_local_model)} lokales und "
                            f"{len(data['trained'])} eigenes Modell(e) verfügbar"
                        )
                    else:
                        self.model.set("")
                        self.status.set(
                            f"Kein Modell geladen. {data['model_error'] or 'Lade ein Modell oder trainiere ein eigenes.'}"
                        )
                    if data["model_error"]:
                        messagebox.showerror(
                            "Modell konnte nicht geladen werden",
                            data["model_error"],
                            parent=self.root,
                        )
                    if data["trained_error"]:
                        self.events.put(
                            (
                                "models_error",
                                f"Eigene Modelle konnten nicht geladen werden: {data['trained_error']}",
                            )
                        )
                    self.refresh_button.configure(
                        state="disabled" if self.busy or self.training_running else "normal"
                    )
                elif event == "model_download":
                    self.status.set(data)
                elif event == "models_error":
                    self.status.set(data)
                    self.refresh_button.configure(state="normal")
                elif event == "chunk":
                    self._append_text(data, "body")
                elif event == "complete":
                    self._append_text("\n\n", "body")
                    self.messages.append({"role": "assistant", "content": data})
                    self._send_discord_log(
                        self.pending_discord_task,
                        data,
                        self.pending_discord_model,
                    )
                    self.pending_discord_task = ""
                    self.pending_discord_model = ""
                    self.busy = False
                    self.send_button.configure(state="normal")
                    self.refresh_button.configure(state="normal")
                    self.train_button.configure(state="normal")
                    self.provider_button.configure(state="normal")
                    self.status.set(f"{self.model.get()} ist bereit")
                elif event == "chat_error":
                    self._append_text(f"\nFehler: {data}\n\n", "hint")
                    self.busy = False
                    self.send_button.configure(state="normal")
                    self.refresh_button.configure(state="normal")
                    self.train_button.configure(state="normal")
                    self.provider_button.configure(state="normal")
                    self.status.set("Die Antwort konnte nicht geladen werden.")
                    self.pending_discord_task = ""
                    self.pending_discord_model = ""
                elif event == "collaboration_warning":
                    self._append_text(f"{data}\n", "hint")
                elif event == "collaboration_status":
                    self.status.set(data)
                elif event == "discord_sent":
                    self.status.set("Aufgabe und Ausgabe wurden an Discord gesendet.")
                elif event == "discord_error":
                    self.status.set(f"Discord-Webhook: {data}")
                elif event == "training_log":
                    self._append_training_log(data)
                elif event == "training_complete":
                    self.training_running = False
                    self.training_process = None
                    self.send_button.configure(state="normal")
                    self.refresh_button.configure(state="normal")
                    self.train_button.configure(state="normal")
                    if data == 0:
                        self._append_training_log("\nTraining erfolgreich abgeschlossen.\n")
                        self.status.set("Eigenes Modell wurde trainiert")
                        self.refresh_models()
                    else:
                        self._append_training_log(
                            f"\nTraining mit Fehlercode {data} beendet. Siehe Fehlermeldung oben.\n"
                        )
                        self.status.set("Training fehlgeschlagen oder abgebrochen")
                    if self.training_start_button is not None:
                        self.training_start_button.configure(state="normal")
                    if self.training_stop_button is not None:
                        self.training_stop_button.configure(state="disabled")
                    if (
                        self.close_training_when_done
                        and self.training_window is not None
                        and self.training_window.winfo_exists()
                    ):
                        self.training_window.destroy()
                        self.training_window = None
                        self.training_log = None
                        self.training_start_button = None
                        self.training_stop_button = None
                        self.close_training_when_done = False
        except queue.Empty:
            pass
        self.root.after(50, self._process_events)


def main():
    if getattr(sys, "frozen", False) and len(sys.argv) > 1 and sys.argv[1] == "--training-worker":
        trainer_path = APP_DIR / "train_from_scratch.py"
        sys.argv = [str(trainer_path), *sys.argv[2:]]
        runpy.run_path(str(trainer_path), run_name="__main__")
        return
    root = tk.Tk()
    MyAI(root)
    root.mainloop()


if __name__ == "__main__":
    main()
