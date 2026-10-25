import argparse
import gc
import os
import re
import sys
from array import array
from pathlib import Path
from tempfile import TemporaryDirectory


SPECIAL_TOKENS = ["<unk>", "<bos>", "<eos>", "<pad>"]
QA_PATTERN = re.compile(r"^Eingabe:\s*(.*)$", re.IGNORECASE)
ANSWER_PATTERN = re.compile(r"^Antwort:\s*(.*)$", re.IGNORECASE)


def parse_args():
    parser = argparse.ArgumentParser(
        description="Train a GPT-style language model from random weights and local .txt files."
    )
    parser.add_argument("--data-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--epochs", type=int, default=20)
    parser.add_argument("--hidden-size", type=int, default=128)
    parser.add_argument("--layers", type=int, default=2)
    parser.add_argument("--heads", type=int, default=4)
    parser.add_argument("--sequence-length", type=int, default=128)
    parser.add_argument("--vocab-size", type=int, default=512)
    parser.add_argument("--batch-size", type=int, default=1)
    parser.add_argument("--gradient-accumulation", type=int, default=2)
    return parser.parse_args()


def validate_args(args, text_files):
    if not text_files:
        raise ValueError(f"No .txt files found in {args.data_dir} or its subdirectories.")
    if args.hidden_size < 32 or args.layers < 1 or args.heads < 1:
        raise ValueError("Model dimensions are too small or invalid.")
    if args.hidden_size % args.heads:
        raise ValueError("--hidden-size must be divisible by --heads.")
    if args.sequence_length < 32 or args.vocab_size < 256:
        raise ValueError("Sequence length must be at least 32 and vocabulary at least 256.")
    if min(args.epochs, args.batch_size, args.gradient_accumulation) < 1:
        raise ValueError("Epochs, batch size, and gradient accumulation must be positive.")
    if args.output_dir.exists():
        raise ValueError(f"Output directory already exists: {args.output_dir}")


def write_tokenized_corpus(text_files, tokenizer, eos_id, token_path):
    token_count = 0
    with token_path.open("wb") as token_file:
        tokens = array("I")
        for file_path in text_files:
            with file_path.open("r", encoding="utf-8", errors="replace") as source:
                for line in source:
                    encoded = tokenizer.encode(line.rstrip("\r\n") + "\n").ids
                    if encoded:
                        tokens.extend(encoded)
                        token_count += len(encoded)
                    if len(tokens) >= 262144:
                        tokens.tofile(token_file)
                        tokens = array("I")
            tokens.append(eos_id)
            token_count += 1
            if len(tokens) >= 262144:
                tokens.tofile(token_file)
                tokens = array("I")
        if tokens:
            tokens.tofile(token_file)
    return token_count


def read_dialogue_pairs(file_path):
    pairs = []
    question = None
    answer_lines = None

    def save_pair():
        if question and answer_lines:
            answer = "\n".join(answer_lines).strip()
            if answer:
                pairs.append((question, answer))

    with file_path.open("r", encoding="utf-8", errors="replace") as source:
        for line in source:
            text = line.strip()
            question_match = QA_PATTERN.match(text)
            answer_match = ANSWER_PATTERN.match(text)
            if question_match:
                save_pair()
                question = question_match.group(1).strip()
                answer_lines = None
            elif answer_match and question is not None:
                answer_lines = [answer_match.group(1).strip()]
            elif answer_lines is not None and text:
                answer_lines.append(text)
    save_pair()
    return pairs


def train(args):
    try:
        import numpy as np
        import torch
        from tokenizers import Tokenizer
        from tokenizers.decoders import ByteLevel as ByteLevelDecoder
        from tokenizers.models import BPE
        from tokenizers.pre_tokenizers import ByteLevel
        from tokenizers.trainers import BpeTrainer
        from transformers import (
            GPT2Config,
            GPT2LMHeadModel,
            PreTrainedTokenizerFast,
            Trainer,
            TrainingArguments,
            default_data_collator,
        )
        from torch.utils.data import ConcatDataset, Dataset
    except ImportError as error:
        raise RuntimeError(
            "Training dependencies are missing. Install PyTorch for your GPU from "
            "https://pytorch.org/get-started/locally/, then install requirements-training.txt."
        ) from error

    text_files = sorted(args.data_dir.rglob("*.txt"))
    validate_args(args, text_files)
    args.output_dir.parent.mkdir(parents=True, exist_ok=True)
    torch.manual_seed(42)
    np.random.seed(42)

    dialogue_pairs = []
    plain_text_files = []
    for file_path in text_files:
        pairs = read_dialogue_pairs(file_path)
        if pairs:
            dialogue_pairs.extend(pairs)
        else:
            plain_text_files.append(file_path)

    unique_pairs = {}
    for question, answer in dialogue_pairs:
        key = " ".join(question.split()).casefold()
        unique_pairs[key] = (question, answer)
    duplicate_count = len(dialogue_pairs) - len(unique_pairs)
    dialogue_pairs = list(unique_pairs.values())

    print(f"Found {len(text_files)} text file(s).", flush=True)
    print(
        f"Found {len(dialogue_pairs)} dialogue pair(s) and "
        f"{len(plain_text_files)} plain text file(s); "
        f"replaced {duplicate_count} duplicate question(s).",
        flush=True,
    )
    tokenizer = Tokenizer(BPE(unk_token=SPECIAL_TOKENS[0]))
    tokenizer.pre_tokenizer = ByteLevel(add_prefix_space=False)
    tokenizer.decoder = ByteLevelDecoder()
    tokenizer.train(
        files=[str(file_path) for file_path in text_files],
        trainer=BpeTrainer(
            vocab_size=args.vocab_size,
            min_frequency=2,
            special_tokens=SPECIAL_TOKENS,
            initial_alphabet=ByteLevel.alphabet(),
        ),
    )
    class TokenBlockDataset(Dataset):
        def __init__(self, token_file, start, end):
            self.tokens = np.memmap(token_file, dtype=np.uint32, mode="r")
            self.start = start
            self.end = end
            self.sample_count = max(1, (end - start) // args.sequence_length)

        def __len__(self):
            return self.sample_count

        def __getitem__(self, _index):
            offset = np.random.randint(self.start, self.end - args.sequence_length)
            values = np.asarray(self.tokens[offset : offset + args.sequence_length], dtype=np.int64).copy()
            input_ids = torch.from_numpy(values)
            return {
                "input_ids": input_ids,
                "labels": input_ids.clone(),
            }

        def close(self):
            self.tokens._mmap.close()

    class DialogueDataset(Dataset):
        def __init__(self, pairs):
            self.samples = []
            for question, answer in pairs:
                prompt_ids = fast_tokenizer.encode(
                    f"Eingabe: {question}\nAntwort:",
                    add_special_tokens=False,
                )
                answer_ids = fast_tokenizer.encode(
                    f" {answer}",
                    add_special_tokens=False,
                )[: args.sequence_length - 1]
                answer_ids.append(fast_tokenizer.eos_token_id)
                prompt_limit = args.sequence_length - len(answer_ids)
                prompt_ids = prompt_ids[-prompt_limit:] if prompt_limit else []
                token_ids = prompt_ids + answer_ids
                prompt_length = len(prompt_ids)
                padding_length = args.sequence_length - len(token_ids)
                self.samples.append(
                    {
                        "input_ids": torch.tensor(
                            token_ids + [fast_tokenizer.pad_token_id] * padding_length,
                            dtype=torch.long,
                        ),
                        "labels": torch.tensor(
                            [-100] * prompt_length
                            + answer_ids
                            + [-100] * padding_length,
                            dtype=torch.long,
                        ),
                    }
                )

        def __len__(self):
            return len(self.samples)

        def __getitem__(self, index):
            return self.samples[index]

    with TemporaryDirectory(prefix=f".{args.output_dir.name}.training-", dir=args.output_dir.parent) as workspace:
        temporary_output = Path(workspace) / args.output_dir.name
        temporary_output.mkdir()
        tokenizer_path = temporary_output / "tokenizer.json"
        tokenizer.save(str(tokenizer_path))
        fast_tokenizer = PreTrainedTokenizerFast(
            tokenizer_file=str(tokenizer_path),
            unk_token=SPECIAL_TOKENS[0],
            bos_token=SPECIAL_TOKENS[1],
            eos_token=SPECIAL_TOKENS[2],
            pad_token=SPECIAL_TOKENS[3],
            model_max_length=args.sequence_length,
        )
        train_datasets = []
        if dialogue_pairs:
            train_datasets.append(DialogueDataset(dialogue_pairs))
        with TemporaryDirectory(prefix="myai-training-") as token_workspace:
            if plain_text_files:
                token_path = Path(token_workspace) / "tokens.bin"
                token_count = write_tokenized_corpus(
                    plain_text_files,
                    tokenizer,
                    tokenizer.token_to_id(SPECIAL_TOKENS[2]),
                    token_path,
                )
                if token_count <= args.sequence_length:
                    raise ValueError(
                        f"Not enough text for a {args.sequence_length}-token sequence. "
                        "Add more text or reduce the sequence length."
                    )
                train_datasets.append(TokenBlockDataset(token_path, 0, token_count))
            if not train_datasets:
                raise ValueError("No usable dialogue pairs or plain text were found.")

            train_data = train_datasets[0] if len(train_datasets) == 1 else ConcatDataset(train_datasets)
            config = GPT2Config(
                vocab_size=fast_tokenizer.vocab_size,
                n_positions=args.sequence_length,
                n_ctx=args.sequence_length,
                n_embd=args.hidden_size,
                n_layer=args.layers,
                n_head=args.heads,
                bos_token_id=fast_tokenizer.bos_token_id,
                eos_token_id=fast_tokenizer.eos_token_id,
                pad_token_id=fast_tokenizer.pad_token_id,
                loss_type="ForCausalLMLoss",
            )
            model = GPT2LMHeadModel(config)
            model.config.use_cache = False
            model.config.loss_type = "ForCausalLMLoss"
            parameter_count = sum(parameter.numel() for parameter in model.parameters())
            print(f"Initialized {parameter_count:,} parameters with random weights.", flush=True)
            if torch.cuda.is_available():
                print(f"Training on GPU: {torch.cuda.get_device_name(0)}", flush=True)
            else:
                print("No CUDA GPU detected; training on CPU will be extremely slow.", flush=True)

            training_args = TrainingArguments(
                output_dir=str(temporary_output),
                num_train_epochs=args.epochs,
                per_device_train_batch_size=args.batch_size,
                gradient_accumulation_steps=min(args.gradient_accumulation, len(train_data)),
                learning_rate=5e-4,
                weight_decay=0.1,
                warmup_ratio=0.03,
                lr_scheduler_type="cosine",
                logging_steps=50,
                save_strategy="no",
                report_to="none",
                disable_tqdm=True,
                dataloader_pin_memory=torch.cuda.is_available(),
            )
            try:
                trainer = Trainer(
                    model=model,
                    args=training_args,
                    train_dataset=train_data,
                    data_collator=default_data_collator,
                )
                trainer.train()
                model.config.use_cache = True
                trainer.save_model(str(temporary_output))
                fast_tokenizer.save_pretrained(str(temporary_output))
                del trainer
                del model
                gc.collect()
                os.replace(temporary_output, args.output_dir)
                print(f"Training complete. Model saved to {args.output_dir}", flush=True)
            finally:
                for dataset in train_datasets:
                    if isinstance(dataset, TokenBlockDataset):
                        dataset.close()


def main():
    args = parse_args()
    if not args.data_dir.is_dir():
        print(f"Training data folder does not exist: {args.data_dir}", file=sys.stderr, flush=True)
        return 2
    try:
        train(args)
    except (OSError, RuntimeError, ValueError) as error:
        print(f"Training failed: {error}", file=sys.stderr, flush=True)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
