# MyAI

MyAI is a private desktop chat app for running local language models with [Ollama](https://ollama.com/). The interface and conversation history stay on your PC; prompts are sent only to the Ollama service running locally.

## Requirements

- Windows, macOS, or Linux
- Python 3.10 or newer with Tkinter
- Ollama installed and running
- At least one model downloaded in Ollama

## Get started

1. Install Ollama from [ollama.com](https://ollama.com/).
2. Download a model, for example: `ollama pull llama3.2`
3. Start MyAI from this folder:

   ```sh
   python myai.py
   ```

MyAI connects to Ollama at `http://localhost:11434` and lists the models available on your computer. Choose a model, type a message, then press **Ctrl + Enter** or click **Senden**. Use **Modelle laden** to refresh the model list.

The chat history is kept in memory for the current app session and is not saved to disk.
