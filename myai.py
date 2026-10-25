import json
import queue
import threading
import urllib.error
import urllib.request
import tkinter as tk
from tkinter import scrolledtext, ttk


OLLAMA_URL = "http://localhost:11434"


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
        self.model = tk.StringVar()
        self.status = tk.StringVar(value="Verbinde mit Ollama...")

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
            "Deine Nachrichten werden an Ollama auf diesem PC gesendet. "
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

    def refresh_models(self):
        if self.busy:
            return
        self.status.set("Lade lokale Modelle...")
        self.refresh_button.configure(state="disabled")

        def load():
            try:
                with urllib.request.urlopen(f"{OLLAMA_URL}/api/tags", timeout=5) as response:
                    data = json.loads(response.read().decode("utf-8"))
                names = [item["name"] for item in data.get("models", []) if item.get("name")]
                self.events.put(("models", names))
            except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError) as error:
                self.events.put(("models_error", str(error)))

        threading.Thread(target=load, daemon=True).start()

    def send_message(self):
        if self.busy:
            return
        text = self.prompt.get("1.0", "end").strip()
        if not text:
            return
        model = self.model.get()
        if not model:
            self.status.set("Kein Modell gefunden. Installiere ein Modell und lade erneut.")
            return

        self.prompt.delete("1.0", "end")
        self._append_text("Du\n", "user")
        self._append_text(f"{text}\n\n", "body")
        self.messages.append({"role": "user", "content": text})
        self.busy = True
        self.send_button.configure(state="disabled")
        self.refresh_button.configure(state="disabled")
        self.status.set(f"{model} antwortet...")
        self._append_text("MyAI\n", "assistant")

        def generate():
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

    def _process_events(self):
        try:
            while True:
                event, data = self.events.get_nowait()
                if event == "models":
                    self.model_picker.configure(values=data)
                    if data:
                        if self.model.get() not in data:
                            self.model.set(data[0])
                        self.status.set(f"{len(data)} lokales Modell(e) verfügbar")
                    else:
                        self.model.set("")
                        self.status.set("Keine Modelle installiert. Siehe Anleitung in README.")
                    self.refresh_button.configure(state="normal")
                elif event == "models_error":
                    self.status.set(f"Ollama nicht erreichbar: {data}")
                    self.refresh_button.configure(state="normal")
                elif event == "chunk":
                    self._append_text(data, "body")
                elif event == "complete":
                    self._append_text("\n\n", "body")
                    self.messages.append({"role": "assistant", "content": data})
                    self.busy = False
                    self.send_button.configure(state="normal")
                    self.refresh_button.configure(state="normal")
                    self.status.set(f"{self.model.get()} ist bereit")
                elif event == "chat_error":
                    self._append_text(f"\nFehler: {data}\n\n", "hint")
                    self.busy = False
                    self.send_button.configure(state="normal")
                    self.refresh_button.configure(state="normal")
                    self.status.set("Die Antwort konnte nicht geladen werden.")
        except queue.Empty:
            pass
        self.root.after(50, self._process_events)


def main():
    root = tk.Tk()
    MyAI(root)
    root.mainloop()


if __name__ == "__main__":
    main()
