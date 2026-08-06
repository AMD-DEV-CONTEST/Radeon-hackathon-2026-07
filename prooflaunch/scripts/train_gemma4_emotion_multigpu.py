#!/usr/bin/env python3
"""Distributed, multimodal-safe Gemma 4 E4B-it emotion LoRA training.

This is deliberately a script, not a Jupyter cell: ``accelerate launch`` owns
one process per GPU. No ``device_map`` is used during training.

The training/evaluation contract is accelerator-neutral across ROCm and CUDA.
Hardware receipts remain explicit so a CUDA run can never be represented as
the competition's required Radeon evidence.
"""

from __future__ import annotations

import argparse
import glob
import hashlib
import json
import os
import re
import sys
from pathlib import Path
from typing import Any


SOURCE_ROOT = Path(__file__).resolve().parents[1] / "src"
if str(SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(SOURCE_ROOT))


LABEL_NAMES = ["sadness", "joy", "love", "anger", "fear", "surprise"]
SYSTEM_PROMPT = """You are an emotion classification assistant.
Read the user's text and answer with exactly one label.
Only choose from: sadness, joy, love, anger, fear, surprise.
Return only the label and nothing else."""

# This positive allowlist is intentionally narrower than ``language_model``.
# It excludes token embeddings, PLE inputs, the LM head, vision/audio towers,
# and every multimodal projection by construction.
TEXT_LORA_PATTERN = re.compile(
    r"(?:^|\.)model\.language_model\.layers\.\d+\."
    r"(?:self_attn\.(?:q_proj|k_proj|v_proj|o_proj)|"
    r"mlp\.(?:gate_proj|up_proj|down_proj))$"
)
FORBIDDEN_TRAINABLE_TOKENS = (
    "vision_tower",
    "audio_tower",
    "embed_vision",
    "embed_audio",
    "vision_projection",
    "audio_projection",
    "multi_modal",
    "multimodal",
    "mm_projector",
    "lm_head",
    "embed_tokens",
    "embed_tokens_per_layer",
    "per_layer_model_projection",
)

RUN_PROFILES = {
    "smoke": {
        "train_limit": 256,
        "validation_limit": 64,
        "max_length": 128,
        "epochs": 0.1,
        "per_device_train_batch_size": 1,
        "gradient_accumulation_steps": 2,
        "eval_steps": 10,
        "save_steps": 10,
    },
    "candidate": {
        "train_limit": 4000,
        "validation_limit": 400,
        "max_length": 256,
        "epochs": 1.0,
        "per_device_train_batch_size": 2,
        "gradient_accumulation_steps": 4,
        "eval_steps": 25,
        "save_steps": 25,
    },
    "final": {
        "train_limit": 16000,
        "validation_limit": 2000,
        "max_length": 512,
        "epochs": 2.0,
        "per_device_train_batch_size": 1,
        "gradient_accumulation_steps": 8,
        "eval_steps": 100,
        "save_steps": 100,
    },
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model-id", default="google/gemma-4-E4B-it")
    parser.add_argument("--dataset-id", default="AI-ModelScope/emotion")
    parser.add_argument("--model-revision", required=True)
    parser.add_argument("--dataset-revision", required=True)
    parser.add_argument(
        "--output-dir",
        default="./gemma4-it-emotion-lora-ms-multigpu",
    )
    parser.add_argument("--cache-dir", default="./.cache/modelscope")
    parser.add_argument(
        "--run-profile",
        choices=tuple(RUN_PROFILES),
        default="candidate",
    )
    parser.add_argument("--train-limit", type=int)
    parser.add_argument("--validation-limit", type=int)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--max-length", type=int)
    parser.add_argument("--epochs", type=float)
    parser.add_argument("--learning-rate", type=float, default=1e-4)
    parser.add_argument("--per-device-train-batch-size", type=int)
    parser.add_argument("--gradient-accumulation-steps", type=int)
    parser.add_argument("--eval-steps", type=int)
    parser.add_argument("--save-steps", type=int)
    parser.add_argument("--expected-world-size", type=int, required=True)
    parser.add_argument(
        "--accelerator-backend",
        choices=("auto", "rocm", "cuda"),
        default="auto",
        help="Select the observed PyTorch GPU runtime; receipts preserve its identity.",
    )
    parser.add_argument(
        "--expected-global-batch-size",
        type=int,
        required=True,
    )
    parser.add_argument(
        "--parallelism",
        choices=("single", "ddp", "fsdp2"),
        required=True,
        help="Evidence label; the matching Accelerate YAML selects the backend.",
    )
    args = parser.parse_args()
    profile = RUN_PROFILES[args.run_profile]
    for name, value in profile.items():
        if getattr(args, name) is None:
            setattr(args, name, value)
    return args


def _bounded(split: Any, limit: int, seed: int) -> Any:
    split = split.shuffle(seed=seed)
    return split.select(range(min(limit, len(split))))


def _parquet_files(dataset_dir: str, split: str) -> list[str]:
    files = sorted(glob.glob(os.path.join(dataset_dir, "data", f"{split}-*.parquet")))
    if not files:
        raise FileNotFoundError(f"No parquet shards found for {split!r}")
    return files


def _tree_fingerprint(root: str) -> str:
    """Hash repository layout, file sizes, and small control files.

    Weight bytes are not re-read here because ModelScope already verifies the
    downloaded snapshot. The immutable requested revision remains mandatory.
    """

    digest = hashlib.sha256()
    base = Path(root)
    for path in sorted(item for item in base.rglob("*") if item.is_file()):
        relative = path.relative_to(base).as_posix()
        size = path.stat().st_size
        digest.update(f"{relative}\0{size}\0".encode())
        if size <= 8 * 1024 * 1024:
            digest.update(path.read_bytes())
    return digest.hexdigest()


def _atomic_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


def _discover_lora_targets(model: Any, linear_type: type) -> list[str]:
    targets = [
        name
        for name, module in model.named_modules()
        if isinstance(module, linear_type) and TEXT_LORA_PATTERN.search(name)
    ]
    if not targets:
        raise RuntimeError(
            "No allowlisted Gemma 4 text projection matched; stop instead of "
            "falling back to all-linear"
        )
    forbidden = [
        name
        for name in targets
        if any(token in name for token in FORBIDDEN_TRAINABLE_TOKENS)
    ]
    if forbidden:
        raise RuntimeError(f"Forbidden LoRA targets: {forbidden[:20]}")
    return sorted(targets)


def _assert_trainable_boundary(model: Any) -> tuple[int, int, list[str]]:
    trainable = []
    trainable_count = 0
    total_count = 0
    for name, parameter in model.named_parameters():
        total_count += parameter.numel()
        if parameter.requires_grad:
            trainable.append(name)
            trainable_count += parameter.numel()
    if not trainable:
        raise RuntimeError("No trainable parameters were attached")
    violations = [
        name
        for name in trainable
        if "lora_" not in name
        or ".model.language_model.layers." not in name
        or any(token in name for token in FORBIDDEN_TRAINABLE_TOKENS)
    ]
    if violations:
        raise RuntimeError(f"Trainable-boundary violations: {violations[:20]}")
    return trainable_count, total_count, trainable


def main() -> None:
    args = parse_args()

    import torch
    from accelerate import PartialState
    from datasets import ClassLabel, DatasetDict, load_dataset
    from modelscope import snapshot_download
    from modelscope.hub.snapshot_download import dataset_snapshot_download
    from peft import LoraConfig
    from transformers import AutoModelForMultimodalLM, AutoProcessor, set_seed
    from trl import SFTConfig, SFTTrainer
    from prooflaunch_remix.accelerator_portability import (
        AcceleratorPortabilityError,
        resolve_accelerator_backend,
    )

    state = PartialState()
    if state.num_processes != args.expected_world_size:
        raise RuntimeError(
            f"Expected {args.expected_world_size} ranks, got {state.num_processes}"
        )
    for label, revision in (
        ("model", args.model_revision),
        ("dataset", args.dataset_revision),
    ):
        if not re.fullmatch(r"[0-9a-f]{40}", revision):
            raise RuntimeError(
                f"{label} revision must be an immutable 40-character Git SHA"
            )
    observed_distributed_type = str(state.distributed_type).split(".")[-1]
    expected_distributed_type = {
        "single": "NO",
        "ddp": "MULTI_GPU",
        "fsdp2": "FSDP",
    }[args.parallelism]
    if observed_distributed_type != expected_distributed_type:
        raise RuntimeError(
            "Accelerate distributed type does not match --parallelism: "
            f"expected {expected_distributed_type}, got "
            f"{observed_distributed_type}"
        )
    try:
        accelerator = resolve_accelerator_backend(
            args.accelerator_backend,
            gpu_available=bool(torch.cuda.is_available()),
            hip_version=str(torch.version.hip) if torch.version.hip else None,
            cuda_version=str(torch.version.cuda) if torch.version.cuda else None,
        )
    except AcceleratorPortabilityError as error:
        raise RuntimeError(f"Accelerator preflight failed: {error}") from error
    if torch.cuda.device_count() < state.num_processes:
        raise RuntimeError("Visible GPU count is below the Accelerate world size")
    if not torch.cuda.is_bf16_supported():
        raise RuntimeError("This training contract requires a BF16-capable GPU")
    effective_batch = (
        args.per_device_train_batch_size
        * args.gradient_accumulation_steps
        * state.num_processes
    )
    if effective_batch != args.expected_global_batch_size:
        raise RuntimeError(
            "Global batch invariant failed: "
            f"expected {args.expected_global_batch_size}, got "
            f"{effective_batch}"
        )

    current_device = torch.cuda.current_device()
    device_properties = torch.cuda.get_device_properties(current_device)
    free_memory, total_memory = torch.cuda.mem_get_info(current_device)
    rank_receipt = {
        "schema": "ProofLaunchGemma4DistributedRankReceiptV1",
        "status": "preflight_passed",
        "global_rank": state.process_index,
        "local_rank": state.local_process_index,
        "world_size": state.num_processes,
        "device_index": current_device,
        "device_name": device_properties.name,
        "device_total_memory_bytes": device_properties.total_memory,
        "device_free_memory_bytes_at_preflight": free_memory,
        "device_total_memory_bytes_at_preflight": total_memory,
        "requested_accelerator_backend": accelerator.requested_backend,
        "accelerator_backend": accelerator.selected_backend.value,
        "hip_version": str(torch.version.hip),
        "cuda_version": str(torch.version.cuda),
        "torch_version": torch.__version__,
        "parallelism": args.parallelism,
        "run_profile": args.run_profile,
        "expected_global_batch_size": args.expected_global_batch_size,
        "training_complete": False,
    }
    rank_receipt_path = (
        Path(args.output_dir)
        / "distributed-ranks"
        / f"rank-{state.process_index:04d}.json"
    )
    _atomic_json(rank_receipt_path, rank_receipt)
    state.wait_for_everyone()

    set_seed(args.seed)
    with state.local_main_process_first():
        model_dir = snapshot_download(
            args.model_id,
            revision=args.model_revision,
            cache_dir=os.path.join(args.cache_dir, "models"),
        )
        dataset_dir = dataset_snapshot_download(
            args.dataset_id,
            revision=args.dataset_revision,
            cache_dir=os.path.join(args.cache_dir, "datasets"),
        )
    state.wait_for_everyone()

    processor = AutoProcessor.from_pretrained(
        model_dir,
        padding_side="left",
        trust_remote_code=False,
    )
    tokenizer = processor.tokenizer
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token

    raw = load_dataset(
        "parquet",
        data_files={
            "train": _parquet_files(dataset_dir, "train"),
            "validation": _parquet_files(dataset_dir, "validation"),
        },
    )
    for split in tuple(raw.keys()):
        if not isinstance(raw[split].features.get("label"), ClassLabel):
            raw[split] = raw[split].cast_column(
                "label",
                ClassLabel(names=LABEL_NAMES),
            )
    dataset = DatasetDict(
        {
            "train": _bounded(raw["train"], args.train_limit, args.seed),
            "validation": _bounded(
                raw["validation"],
                args.validation_limit,
                args.seed,
            ),
        }
    )

    def to_prompt_completion(example: dict[str, Any]) -> dict[str, Any]:
        return {
            "prompt": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": (
                        "Classify the emotion of this text:\n\n"
                        + example["text"]
                    ),
                },
            ],
            "completion": [
                {
                    "role": "assistant",
                    "content": LABEL_NAMES[example["label"]],
                }
            ],
        }

    sft_dataset = dataset.map(
        to_prompt_completion,
        remove_columns=dataset["train"].column_names,
    )

    # Accelerate/Trainer places and wraps the model. ``device_map`` is
    # intentionally absent because it is an inference sharding mechanism.
    model = AutoModelForMultimodalLM.from_pretrained(
        model_dir,
        dtype=torch.bfloat16,
        low_cpu_mem_usage=True,
        trust_remote_code=False,
        attn_implementation="sdpa",
    )
    model.config.use_cache = False
    model.config.pad_token_id = tokenizer.pad_token_id

    targets = _discover_lora_targets(model, torch.nn.Linear)
    lora = LoraConfig(
        r=16,
        lora_alpha=32,
        lora_dropout=0.05,
        bias="none",
        task_type="CAUSAL_LM",
        target_modules=targets,
    )
    training = SFTConfig(
        output_dir=args.output_dir,
        per_device_train_batch_size=args.per_device_train_batch_size,
        per_device_eval_batch_size=1,
        gradient_accumulation_steps=args.gradient_accumulation_steps,
        learning_rate=args.learning_rate,
        weight_decay=0.01,
        lr_scheduler_type="linear",
        warmup_ratio=0.03,
        num_train_epochs=args.epochs,
        logging_steps=5,
        eval_strategy="steps",
        eval_steps=args.eval_steps,
        save_strategy="steps",
        save_steps=args.save_steps,
        save_total_limit=2,
        load_best_model_at_end=True,
        metric_for_best_model="eval_loss",
        greater_is_better=False,
        gradient_checkpointing=(args.parallelism != "fsdp2"),
        gradient_checkpointing_kwargs={"use_reentrant": False},
        bf16=True,
        fp16=False,
        tf32=False,
        max_length=args.max_length,
        packing=False,
        completion_only_loss=True,
        optim="adamw_torch",
        report_to="none",
        ddp_find_unused_parameters=False,
        seed=args.seed,
        data_seed=args.seed,
    )
    trainer = SFTTrainer(
        model=model,
        train_dataset=sft_dataset["train"],
        eval_dataset=sft_dataset["validation"],
        peft_config=lora,
        args=training,
        processing_class=tokenizer,
    )
    trainable_count, total_count, trainable_names = _assert_trainable_boundary(
        trainer.model
    )
    result = trainer.train()
    final_validation_metrics = trainer.evaluate(
        eval_dataset=sft_dataset["validation"]
    )
    trainer.save_model(args.output_dir)
    rank_receipt["status"] = "training_complete"
    rank_receipt["training_complete"] = True
    rank_receipt["train_metrics"] = result.metrics
    rank_receipt["final_validation_metrics"] = (
        final_validation_metrics
    )
    _atomic_json(rank_receipt_path, rank_receipt)
    state.wait_for_everyone()

    if state.is_main_process:
        rank_receipts = []
        for rank in range(state.num_processes):
            receipt_path = (
                Path(args.output_dir)
                / "distributed-ranks"
                / f"rank-{rank:04d}.json"
            )
            receipt_bytes = receipt_path.read_bytes()
            receipt_payload = json.loads(receipt_bytes)
            if (
                receipt_payload["global_rank"] != rank
                or not receipt_payload["training_complete"]
            ):
                raise RuntimeError(
                    f"Rank receipt {rank} is missing or incomplete"
                )
            rank_receipts.append(
                {
                    "rank": rank,
                    "path": str(receipt_path),
                    "sha256": hashlib.sha256(receipt_bytes).hexdigest(),
                }
            )
        manifest = {
            "schema": "ProofLaunchGemma4EmotionDistributedTrainingV1",
            "model": {
                "id": args.model_id,
                "revision": args.model_revision,
                "snapshot_fingerprint": _tree_fingerprint(model_dir),
                "loader": "AutoModelForMultimodalLM",
            },
            "dataset": {
                "id": args.dataset_id,
                "revision": args.dataset_revision,
                "snapshot_fingerprint": _tree_fingerprint(dataset_dir),
                "train_count": len(dataset["train"]),
                "validation_count": len(dataset["validation"]),
                "test_used_during_training": False,
            },
            "hardware": {
                "requested_accelerator_backend": accelerator.requested_backend,
                "accelerator_backend": accelerator.selected_backend.value,
                "hip_version": str(torch.version.hip),
                "cuda_version": str(torch.version.cuda),
                "torch_version": torch.__version__,
                "world_size": state.num_processes,
                "parallelism": args.parallelism,
                "distributed_type": observed_distributed_type,
                "rank_receipts": rank_receipts,
                "radeon_competition_evidence_eligible": (
                    accelerator.selected_backend.value == "rocm"
                ),
            },
            "optimization": {
                "run_profile": args.run_profile,
                "seed": args.seed,
                "dtype": "bfloat16",
                "attention": "sdpa",
                "per_device_train_batch_size": args.per_device_train_batch_size,
                "gradient_accumulation_steps": args.gradient_accumulation_steps,
                "effective_global_batch_size": effective_batch,
                "expected_global_batch_size": (
                    args.expected_global_batch_size
                ),
                "lora_rank": 16,
                "lora_target_count": len(targets),
                "trainable_parameters": trainable_count,
                "total_parameters": total_count,
                "trainable_ratio": trainable_count / total_count,
            },
            "multimodal_safety": {
                "positive_text_projection_allowlist": True,
                "forbidden_trainable_count": 0,
                "trainable_parameter_count": len(trainable_names),
                "post_training_image_audio_retention_required": True,
            },
            "train_metrics": result.metrics,
            "final_validation_metrics": final_validation_metrics,
        }
        output = Path(args.output_dir) / "distributed-training-manifest.json"
        _atomic_json(output, manifest)


if __name__ == "__main__":
    main()
