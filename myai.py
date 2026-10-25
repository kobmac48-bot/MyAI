import json
import os
import re
import queue
import runpy
import subprocess
import sys
import threading
from pathlib import Path
from urllib.parse import urlsplit
import urllib.error
import urllib.request
import tkinter as tk
from tkinter import filedialog, messagebox, scrolledtext, ttk


OLLAMA_URL = "http://localhost:11434"
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
DISCORD_SETTINGS_FILE = DATA_DIR / "discord-webhook.json"


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


class DiscordNoRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, response, code, message, headers, new_url):
        return None


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
        self.status = tk.StringVar(value="Verbinde mit Ollama...")
        self.discord_webhook = ""
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

        self._configure_styles()
        self._build_ui()
        self.root.after(50, self._process_events)
        self.refresh_models()

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
            command=self.refresh_models,
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
            "Ollama-Modelle und eigene, lokal trainierte Modelle werden unterstützt. "
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
            opener = urllib.request.build_opener(DiscordNoRedirectHandler())
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

    def refresh_models(self):
        if self.busy or self.training_running:
            return
        self.status.set("Lade lokale Modelle...")
        self.refresh_button.configure(state="disabled")

        def load():
            names = []
            ollama_error = None
            trained_error = None
            try:
                with urllib.request.urlopen(f"{OLLAMA_URL}/api/tags", timeout=5) as response:
                    data = json.loads(response.read().decode("utf-8"))
                names = [item["name"] for item in data.get("models", []) if item.get("name")]
            except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError) as error:
                ollama_error = str(error)
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
                        "ollama": names,
                        "trained": trained,
                        "ollama_error": ollama_error,
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
        self.status.set(f"{model} antwortet...")
        self._append_text("MyAI\n", "assistant")

        def generate():
            if model_type == "trained":
                self._generate_trained_model(model, list(self.messages))
                return

            assistant_text = []
            try:
                payload = json.dumps(
                    {
                        "model": model,
                        "messages": self.messages,
                        "stream": True,
                    }
                ).encode("utf-8")
                request = urllib.request.Request(
                    f"{OLLAMA_URL}/api/chat",
                    data=payload,
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with urllib.request.urlopen(request, timeout=600) as response:
                    for line in response:
                        if not line.strip():
                            continue
                        result = json.loads(line.decode("utf-8"))
                        if result.get("error"):
                            raise RuntimeError(result["error"])
                        chunk = result.get("message", {}).get("content", "")
                        if chunk:
                            assistant_text.append(chunk)
                            self.events.put(("chunk", chunk))
                self.events.put(("complete", "".join(assistant_text)))
            except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError, RuntimeError) as error:
                self.events.put(("chat_error", str(error)))

        threading.Thread(target=generate, daemon=True).start()

    def _generate_trained_model(self, model_path, messages):
        try:
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
                    choices = {}
                    for name in data["ollama"]:
                        choices[name] = ("ollama", name)
                    for model_path in data["trained"]:
                        choices[f"MyAI: {model_path.name}"] = ("trained", model_path)
                    self.model_sources = choices
                    self.model_picker.configure(values=list(choices))
                    if choices:
                        if self.model.get() not in choices:
                            llama31 = next(
                                (
                                    name
                                    for name, (source, _) in choices.items()
                                    if source == "ollama"
                                    and name.split(":", 1)[0] == "llama3.1"
                                ),
                                None,
                            )
                            self.model.set(llama31 or next(iter(choices)))
                        if data["ollama_error"]:
                            self.status.set(
                                f"Ollama nicht erreichbar; {len(data['trained'])} eigenes Modell(e) verfügbar"
                            )
                        else:
                            self.status.set(
                                f"{len(data['ollama'])} Ollama- und "
                                f"{len(data['trained'])} eigenes Modell(e) verfügbar"
                            )
                    else:
                        self.model.set("")
                        self.status.set(
                            f"Ollama nicht erreichbar: {data['ollama_error']}"
                            if data["ollama_error"]
                            else "Keine Modelle gefunden. Installiere oder trainiere ein Modell."
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
                    self.status.set(f"{self.model.get()} ist bereit")
                elif event == "chat_error":
                    self._append_text(f"\nFehler: {data}\n\n", "hint")
                    self.busy = False
                    self.send_button.configure(state="normal")
                    self.refresh_button.configure(state="normal")
                    self.train_button.configure(state="normal")
                    self.status.set("Die Antwort konnte nicht geladen werden.")
                    self.pending_discord_task = ""
                    self.pending_discord_model = ""
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
