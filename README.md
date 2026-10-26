# MyAI

MyAI is a desktop chat app for running a local open-source language model. The interface, conversation history, and model inference stay on your PC. The optional 32-bit Windows 7/8 client sends chats over HTTPS to a MyAI server that you configure.

## Download the desktop app

Download the latest release for your computer from [GitHub Releases](https://github.com/kobmac48-bot/MyAI/releases/latest):

- **Windows (64-bit):** `MyAI-windows-x64.exe` — download and run the executable.
- **Windows 7/8 (32-bit):** `MyAI-windows-x86.exe` — lightweight remote client; connect it to a secured MyAI local-model server. Windows XP/Vista are not supported.
- **macOS (Apple silicon):** `MyAI-macos-arm64.dmg`
- **macOS (Intel):** `MyAI-macos-x64.dmg`
- **Linux (x86_64):** `MyAI-linux-x64.flatpak` — install with `flatpak install --user --bundle ./MyAI-linux-x64.flatpak`, then start with `flatpak run com.kobmac48bot.MyAI`.

MyAI downloads [Qwen2.5-1.5B-Instruct](https://huggingface.co/Qwen/Qwen2.5-1.5B-Instruct) from Hugging Face on first launch. This requires an internet connection and several GB of free disk space. Inference uses CUDA when the installed PyTorch build has at least 5 GB of GPU memory available; otherwise it runs on CPU. MyAI also includes the option to train a small model locally from your own `.txt` files. The release builds use CPU-only PyTorch; the Linux Flatpak uses the Flathub Freedesktop runtime.

The 32-bit Windows 7/8 client does not run models or train locally. It connects over HTTPS to the MyAI server, which runs the model on a VPS. See [`server/README.md`](server/README.md) for secure server setup; configure the client's server URL and bearer token under **Server einstellen**.

The macOS disk images contain the app and installation notes. The app is not code-signed or notarized; on first launch, macOS may require you to confirm it in **System Settings > Privacy & Security** or use **Open** from the app's context menu.

## Requirements for running from source

- Windows, macOS, or Linux
- Python 3.10 or newer with Tkinter
- PyTorch and the packages in `requirements-training.txt`
- Internet connection and several GB of free disk space for the model download

## Get started from source

1. Install PyTorch for your operating system and, if desired, CUDA using the selector at [pytorch.org/get-started/locally](https://pytorch.org/get-started/locally/), then install the model packages:

   ```sh
   python -m pip install torch
   python -m pip install -r requirements-training.txt
   ```

2. Make sure you have an internet connection and several GB of free disk space for the model download.
3. Start MyAI from this folder:

   ```sh
   python myai.py
   ```

The app downloads Qwen2.5-1.5B-Instruct when it is missing and lists it alongside your own trained models. Choose a model, type a message, then press **Ctrl + Enter** or click **Senden**. Use **Modelle laden** to refresh the model list or retry a failed download.

By default, the chat history is kept only in memory for the current app session. Discord logging is optional and disabled until you configure it below.

## Optional ChatGPT and Claude collaboration

Install API access with OpenAI and Anthropic, then use **KI-Zugangsdaten** in MyAI to save both API keys locally. The keys are stored in `ai-provider-keys.json` without encryption, so protect the file like a password. Enable **ChatGPT + Claude** to send the current conversation to both services; the selected local model then compares their replies and writes the final answer. This sends your chat data to OpenAI and Anthropic and may incur charges on both accounts. The feature is off by default. MyAI does not train on these conversations automatically.

## Optional Discord webhook logging

Use **Discord-Webhook einrichten** in the app to opt in. After each completed chat, MyAI sends the exact user message, selected model name, and final assistant response to that Discord channel. It does not send private chain-of-thought or incomplete/failed responses. Configure a webhook only for a channel where you are comfortable sharing all messages; disabling the webhook stops future sends. The webhook URL is stored locally in `discord-webhook.json` alongside MyAI's local data and is not included in the release or sent to any other service.

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
