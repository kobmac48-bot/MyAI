import os
import threading
from pathlib import Path


MODEL_ID = "Qwen/Qwen2.5-1.5B-Instruct"
MODEL_CACHE_DIR = Path(
    os.environ.get("MYAI_MODEL_CACHE", Path(__file__).resolve().parent / "models")
)
MAX_NEW_TOKENS = 512
MIN_CUDA_MEMORY = 5 * 1024**3

_MODEL_LOCK = threading.RLock()
_LOADED_MODEL_PATH = None
_LOADED_MODEL = None
_LOADED_TOKENIZER = None


def find_downloaded_model():
    from huggingface_hub import snapshot_download
    from huggingface_hub.errors import LocalEntryNotFoundError

    try:
        return snapshot_download(
            repo_id=MODEL_ID,
            cache_dir=str(MODEL_CACHE_DIR),
            local_files_only=True,
        )
    except LocalEntryNotFoundError:
        return None


def download_model(progress_callback=None):
    from huggingface_hub import snapshot_download

    if progress_callback is not None:
        progress_callback(f"Lade {MODEL_ID} herunter...")
    model_path = snapshot_download(repo_id=MODEL_ID, cache_dir=str(MODEL_CACHE_DIR))
    if progress_callback is not None:
        progress_callback(f"{MODEL_ID} ist bereit")
    return model_path


def release_model():
    global _LOADED_MODEL_PATH, _LOADED_MODEL, _LOADED_TOKENIZER

    with _MODEL_LOCK:
        if _LOADED_MODEL is not None:
            import torch

            del _LOADED_MODEL
            del _LOADED_TOKENIZER
            _LOADED_MODEL_PATH = None
            _LOADED_MODEL = None
            _LOADED_TOKENIZER = None
            if torch.cuda.is_available():
                torch.cuda.empty_cache()


def generate_model(model_path, messages):
    global _LOADED_MODEL_PATH, _LOADED_MODEL, _LOADED_TOKENIZER

    path = str(model_path)
    with _MODEL_LOCK:
        try:
            import torch
            from transformers import AutoModelForCausalLM, AutoTokenizer
        except ImportError as error:
            raise RuntimeError(
                "Zum Ausfuehren lokaler Modelle muessen PyTorch und Transformers installiert sein."
            ) from error

        if _LOADED_MODEL_PATH != path:
            if _LOADED_MODEL is not None:
                del _LOADED_MODEL
                del _LOADED_TOKENIZER
                if torch.cuda.is_available():
                    torch.cuda.empty_cache()
            device = (
                "cuda"
                if torch.cuda.is_available()
                and torch.cuda.get_device_properties(0).total_memory >= MIN_CUDA_MEMORY
                else "cpu"
            )
            dtype = torch.float16 if device == "cuda" else torch.float32
            tokenizer = AutoTokenizer.from_pretrained(path, local_files_only=True)
            model = AutoModelForCausalLM.from_pretrained(
                path,
                local_files_only=True,
                torch_dtype=dtype,
            )
            model.to(device)
            model.eval()
            _LOADED_MODEL_PATH = path
            _LOADED_MODEL = model
            _LOADED_TOKENIZER = tokenizer

        tokenizer = _LOADED_TOKENIZER
        model = _LOADED_MODEL
        prompt = tokenizer.apply_chat_template(
            messages,
            tokenize=False,
            add_generation_prompt=True,
        )
        context_length = getattr(
            model.config,
            "max_position_embeddings",
            getattr(model.config, "n_positions", 2048),
        )
        max_input_tokens = max(1, context_length - MAX_NEW_TOKENS)
        inputs = tokenizer(
            prompt,
            return_tensors="pt",
            truncation=True,
            max_length=max_input_tokens,
        )
        device = next(model.parameters()).device
        input_ids = inputs["input_ids"].to(device)
        max_new_tokens = min(MAX_NEW_TOKENS, max(1, context_length - input_ids.shape[1]))
        with torch.inference_mode():
            output = model.generate(
                input_ids=input_ids,
                max_new_tokens=max_new_tokens,
                do_sample=False,
                repetition_penalty=1.05,
                pad_token_id=tokenizer.eos_token_id,
                eos_token_id=tokenizer.eos_token_id,
            )
        return tokenizer.decode(
            output[0, input_ids.shape[1] :],
            skip_special_tokens=True,
        ).strip()
