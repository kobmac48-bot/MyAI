# MyAI

MyAI is a private desktop chat app for running local language models with [Ollama](https://ollama.com/). The interface and conversation history stay on your PC; prompts are sent only to the Ollama service running locally.

## Download the desktop app

Download the latest release for your computer from [GitHub Releases](https://github.com/kobmac48-bot/MyAI/releases/latest):

- **Windows (64-bit):** `MyAI-windows-x64.exe` — download and run the executable.
- **macOS (Apple silicon):** `MyAI-macos-arm64.dmg`
- **macOS (Intel):** `MyAI-macos-x64.dmg`
- **Linux (x86_64):** `MyAI-linux-x64.flatpak` — install with `flatpak install --user --bundle ./MyAI-linux-x64.flatpak`, then start with `flatpak run com.kobmac48bot.MyAI`.

Install [Ollama](https://ollama.com/) separately and download a chat model to use general-purpose models. MyAI also includes the option to train a small model locally from your own `.txt` files. The release builds use CPU-only PyTorch so they run without a CUDA setup; local training can be slow. The Linux Flatpak uses the Flathub Freedesktop runtime.

The macOS disk images contain the app and installation notes. The app is not code-signed or notarized; on first launch, macOS may require you to confirm it in **System Settings > Privacy & Security** or use **Open** from the app's context menu.

## Requirements for running from source

- Windows, macOS, or Linux
- Python 3.10 or newer with Tkinter
- Ollama installed and running
- At least one model downloaded in Ollama

## Get started from source

1. Install Ollama from [ollama.com](https://ollama.com/).
2. Download a model, for example: `ollama pull llama3.2`
3. Start MyAI from this folder:

   ```sh
   python myai.py
   ```

MyAI connects to Ollama at `http://localhost:11434` and lists the models available on your computer. Choose a model, type a message, then press **Ctrl + Enter** or click **Senden**. Use **Modelle laden** to refresh the model list.

The chat history is kept in memory for the current app session and is not saved to disk.

## Train your own model from scratch

MyAI can train a GPT-2-style language model with randomly initialized weights using your own `.txt` files. It does not download or start from a pretrained model. The resulting checkpoint is saved under `trained_models/`, appears in the model selector, and can be used directly in MyAI.

Training dependencies:

1. Install Python 3.11 and create a virtual environment:

   ```sh
   py -3.11 -m venv .venv
   ```

2. Install PyTorch for the GPU and operating system on the machine that will run training. Use the selector at [pytorch.org/get-started/locally](https://pytorch.org/get-started/locally/) to choose the appropriate CUDA build. CPU-only PyTorch works, but training will be very slow. Then install the remaining packages:

   ```powershell
   .\.venv\Scripts\python.exe -m pip install -r requirements-training.txt
   ```

3. Start MyAI with the same Python environment and select **Eigenes Modell trainieren**:

   ```powershell
   .\.venv\Scripts\python.exe myai.py
   ```

   Choose a folder containing `.txt` files, name the model, adjust the architecture and training settings, and start training. Files with `Eingabe:` and `Antwort:` pairs train the model to generate the answer for a prompt; other text files train ordinary next-token text completion. If a question appears more than once with different answers, its last answer in the sorted file order is used.

The training dialog runs on the same machine as MyAI; it does not provision or contact a cloud provider. To use a GPU cloud server, install MyAI and its dependencies on that server and run the app there. The default architecture is deliberately small for a smoke test. Increase its width, layer count, context length, vocabulary and training data for a larger run, keeping the GPU memory and disk requirements in mind.

A from-scratch model only learns patterns in its training text. It does not automatically learn to follow chat instructions, and a large useful language model requires a very large, appropriately licensed corpus and substantial GPU compute. Training data is read locally; model outputs are saved locally and appear in the model selector only after training completes successfully.

Packaged builds store trained models in the current user's application data folder: `%LOCALAPPDATA%\MyAI` on Windows, `~/Library/Application Support/MyAI` on macOS, `$XDG_DATA_HOME/myai` (or `~/.local/share/myai`) for the Linux binary, and Flatpak's sandboxed `~/.var/app/com.kobmac48bot.MyAI/data/myai` folder.
