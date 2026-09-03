# -*- coding: utf-8 -*-
"""在 Radeon PRO W7900/ROCm 上训练 Qwen3-14B 弈鉴 Agent BF16 LoRA。"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import importlib.metadata
import json
import math
import os
import platform
from pathlib import Path


EXPECTED_MANIFEST_SCHEMAS = {
    "yijian-agent-sft-v1",
    "yijian-agent-sft-v2",
    "yijian-agent-sft-v3",
}
SEED = 20260803
QWEN3_14B_REVISION = "40c069824f4251a91eefaf281ebe4c544efd3e18"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _token_ids(value: object) -> list[int]:
    if isinstance(value, dict):
        value = value.get("input_ids")
    if not isinstance(value, list) or any(not isinstance(item, int) for item in value):
        raise ValueError("chat template没有返回token id列表")
    return value


def encode_example(tokenizer, example: dict, max_length: int) -> dict:
    """只让最后一条 assistant 回复参与 loss，拒绝静默截断。"""
    messages = example.get("messages")
    if not isinstance(messages, list) or len(messages) < 2:
        raise ValueError("训练记录缺少messages")
    if messages[-1].get("role") != "assistant":
        raise ValueError("训练记录最后一条必须是assistant")
    full_ids = _token_ids(tokenizer.apply_chat_template(
        messages,
        tokenize=True,
        add_generation_prompt=False,
        enable_thinking=False,
    ))
    prompt_ids = _token_ids(tokenizer.apply_chat_template(
        messages[:-1],
        tokenize=True,
        add_generation_prompt=True,
        enable_thinking=False,
    ))
    if full_ids[:len(prompt_ids)] != prompt_ids:
        raise ValueError("chat template无法可靠定位assistant起始位置")
    row_id = str((example.get("metadata") or {}).get("sourceCaseId") or "<unknown>")
    if len(full_ids) > max_length:
        raise ValueError(
            f"训练记录{row_id}共{len(full_ids)} tokens，超过{max_length}；"
            "必须先压缩证据，禁止静默截断答案"
        )
    labels = [-100] * len(prompt_ids) + full_ids[len(prompt_ids):]
    if not any(label != -100 for label in labels):
        raise ValueError(f"训练记录{row_id}没有assistant loss token")
    return {
        "input_ids": full_ids,
        "attention_mask": [1] * len(full_ids),
        "labels": labels,
        "sequence_length": len(full_ids),
        "loss_tokens": sum(label != -100 for label in labels),
    }


def _package_version(name: str) -> str:
    try:
        return importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:
        return "not-installed"


def _validate_manifest(path: Path, train: Path, eval_path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    if value.get("schemaVersion") not in EXPECTED_MANIFEST_SCHEMAS:
        raise SystemExit("多任务训练manifest版本不受支持。")
    if value.get("passed") is not True:
        raise SystemExit("多任务训练manifest未通过全部数据门槛。")
    if value.get("schemaVersion") == "yijian-agent-sft-v3":
        artifacts = value.get("artifacts") or {}
        sealed = artifacts.get("sealed") or {}
        if any(
            artifact.name in {
                sealed.get("filename"), sealed.get("sourceFilename")
            }
            or sha256_file(artifact) == sealed.get("sha256")
            for artifact in (train, eval_path)
        ):
            raise SystemExit("sealed test制品禁止进入Trainer或开发集评测。")
        for role, artifact in (("train", train), ("dev", eval_path)):
            binding = artifacts.get(role) or {}
            if binding.get("role") != role or binding.get("filename") != artifact.name:
                raise SystemExit(f"训练制品角色绑定错误：{role} -> {artifact}")
            if binding.get("sha256") != sha256_file(artifact):
                raise SystemExit(f"训练制品哈希不匹配：{artifact}")
            rows = [
                json.loads(line)
                for line in artifact.read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
            if len(rows) != int(binding.get("rows") or -1):
                raise SystemExit(f"训练制品行数不匹配：{artifact}")
            if any((row.get("metadata") or {}).get("split") != role for row in rows):
                raise SystemExit(f"训练制品含有错误split：{artifact}")
    else:
        expected = value.get("outputs") or {}
        for artifact in (train, eval_path):
            expected_hash = expected.get(artifact.name)
            if not expected_hash or expected_hash != sha256_file(artifact):
                raise SystemExit(f"训练制品哈希不匹配：{artifact}")
    return value


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default="Qwen/Qwen3-14B")
    parser.add_argument("--model-revision", default=QWEN3_14B_REVISION)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--train", type=Path, required=True)
    parser.add_argument("--eval", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--epochs", type=float, default=2.0)
    parser.add_argument("--max-steps", type=int, default=-1)
    parser.add_argument("--gradient-accumulation", type=int, default=16)
    parser.add_argument("--learning-rate", type=float, default=3e-5)
    parser.add_argument("--lora-rank", type=int, default=8)
    parser.add_argument("--lora-alpha", type=int, default=16)
    parser.add_argument("--lora-dropout", type=float, default=.10)
    parser.add_argument(
        "--lora-target-modules",
        default="q_proj,k_proj,v_proj,o_proj",
        help="comma-separated PEFT module suffixes",
    )
    parser.add_argument("--max-length", type=int, default=1536)
    parser.add_argument("--train-limit", type=int, default=0)
    parser.add_argument("--require-loss-drop", action="store_true")
    parser.add_argument("--minimum-relative-loss-drop", type=float, default=0.0)
    parser.add_argument("--require-dev-loss-drop", action="store_true")
    parser.add_argument("--require-dev-task-gates", action="store_true")
    parser.add_argument("--expected-optimizer-steps", type=int, default=0)
    parser.add_argument("--expected-epochs", type=float, default=0.0)
    parser.add_argument("--max-peak-reserved-gib", type=float, default=45.0)
    parser.add_argument("--resume-from-checkpoint", default=None)
    args = parser.parse_args()
    target_modules = [
        name.strip() for name in args.lora_target_modules.split(",") if name.strip()
    ]
    if args.lora_rank < 1 or args.lora_alpha < 1 or not target_modules:
        raise SystemExit("LoRA rank、alpha和target modules必须有效")
    if not 0 <= args.lora_dropout < 1:
        raise SystemExit("LoRA dropout必须在[0, 1)内")

    import torch
    from datasets import load_dataset
    from peft import LoraConfig, get_peft_model
    from transformers import (
        AutoModelForCausalLM,
        AutoTokenizer,
        DataCollatorForSeq2Seq,
        Trainer,
        TrainingArguments,
        set_seed,
    )

    manifest = _validate_manifest(args.manifest, args.train, args.eval)
    if not torch.cuda.is_available():
        raise SystemExit("未检测到ROCm设备；禁止在CPU上误启动完整LoRA训练。")
    props = torch.cuda.get_device_properties(0)
    if props.total_memory < 44 * 1024**3:
        raise SystemExit(
            f"当前显存约{props.total_memory / 1024**3:.1f}GB；"
            "Qwen3-14B BF16 LoRA交付配置要求至少44GB。"
        )
    if not torch.cuda.is_bf16_supported():
        raise SystemExit("当前ROCm/PyTorch组合未确认BF16支持；拒绝静默切换FP16。")

    set_seed(SEED)
    args.output.mkdir(parents=True, exist_ok=True)
    hardware = {
        "createdAt": dt.datetime.now(dt.timezone.utc).isoformat(),
        "host": platform.node(),
        "platform": platform.platform(),
        "python": platform.python_version(),
        "torch": torch.__version__,
        "hip": torch.version.hip,
        "transformers": _package_version("transformers"),
        "peft": _package_version("peft"),
        "datasets": _package_version("datasets"),
        "device": props.name,
        "vramGiB": round(props.total_memory / 1024**3, 3),
        "gfxArch": os.getenv("PYTORCH_ROCM_ARCH", ""),
        "model": args.model,
        "modelRevision": args.model_revision,
        "manifestSha256": sha256_file(args.manifest),
        "trainSha256": sha256_file(args.train),
        "evalSha256": sha256_file(args.eval),
        "trainingScriptSha256": sha256_file(Path(__file__)),
        "seed": SEED,
    }
    (args.output / "hardware.json").write_text(
        json.dumps(hardware, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    tokenizer = AutoTokenizer.from_pretrained(
        args.model, revision=args.model_revision, use_fast=True
    )
    if tokenizer.pad_token_id is None:
        tokenizer.pad_token = tokenizer.eos_token
    raw = load_dataset(
        "json", data_files={"train": str(args.train), "eval": str(args.eval)}
    )
    if args.train_limit:
        if args.train_limit < 2:
            raise SystemExit("小样本学习测试至少需要2条训练记录。")
        raw["train"] = raw["train"].select(
            range(min(args.train_limit, len(raw["train"])))
        )

    def encode(row: dict) -> dict:
        return encode_example(tokenizer, row, args.max_length)

    encoded = {}
    length_audit = {}
    for split in ("train", "eval"):
        dataset = raw[split].map(
            encode,
            remove_columns=raw[split].column_names,
            desc=f"encode-{split}",
        )
        encoded[split] = dataset.remove_columns(["sequence_length", "loss_tokens"])
        lengths = sorted(int(item) for item in dataset["sequence_length"])
        losses = [int(item) for item in dataset["loss_tokens"]]
        length_audit[split] = {
            "examples": len(lengths),
            "min": min(lengths),
            "max": max(lengths),
            "p50": lengths[len(lengths) // 2],
            "p95": lengths[min(len(lengths) - 1, int(len(lengths) * .95))],
            "assistantLossTokens": sum(losses),
        }
    (args.output / "data-audit.json").write_text(
        json.dumps({
            "schemaVersion": "yijian-agent-token-audit-v1",
            "manifest": manifest,
            "splits": length_audit,
        }, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    model = AutoModelForCausalLM.from_pretrained(
        args.model,
        revision=args.model_revision,
        torch_dtype=torch.bfloat16,
        attn_implementation="sdpa",
        low_cpu_mem_usage=True,
    )
    model.config.use_cache = False
    model.gradient_checkpointing_enable(
        gradient_checkpointing_kwargs={"use_reentrant": False}
    )
    model.enable_input_require_grads()
    model = get_peft_model(model, LoraConfig(
        r=args.lora_rank,
        lora_alpha=args.lora_alpha,
        lora_dropout=args.lora_dropout,
        bias="none",
        task_type="CAUSAL_LM",
        target_modules=target_modules,
    ))

    training_args = TrainingArguments(
        output_dir=str(args.output / "checkpoints"),
        num_train_epochs=args.epochs,
        per_device_train_batch_size=1,
        per_device_eval_batch_size=1,
        gradient_accumulation_steps=args.gradient_accumulation,
        learning_rate=args.learning_rate,
        warmup_ratio=.05,
        lr_scheduler_type="cosine",
        logging_steps=5,
        eval_strategy="epoch",
        save_strategy="epoch",
        save_total_limit=3,
        load_best_model_at_end=True,
        metric_for_best_model="eval_loss",
        greater_is_better=False,
        bf16=True,
        fp16=False,
        gradient_checkpointing=True,
        gradient_checkpointing_kwargs={"use_reentrant": False},
        optim="adamw_torch",
        report_to="none",
        seed=SEED,
        data_seed=SEED,
        max_steps=args.max_steps,
        remove_unused_columns=False,
        save_safetensors=True,
    )
    collator = DataCollatorForSeq2Seq(
        tokenizer=tokenizer,
        padding=True,
        label_pad_token_id=-100,
        return_tensors="pt",
    )
    trainer = Trainer(
        model=model,
        args=training_args,
        train_dataset=encoded["train"],
        eval_dataset=encoded["eval"],
        data_collator=collator,
    )
    pretrain_metrics = None
    predev_metrics = None
    predev_task_metrics: dict[str, dict] = {}
    if args.require_loss_drop:
        pretrain_metrics = trainer.evaluate(
            eval_dataset=encoded["train"], metric_key_prefix="pretrain"
        )
    if args.require_dev_loss_drop:
        predev_metrics = trainer.evaluate(
            eval_dataset=encoded["eval"], metric_key_prefix="predev"
        )
    if args.require_dev_task_gates:
        task_indices: dict[str, list[int]] = {
            task: [
                index
                for index, row in enumerate(raw["eval"])
                if (row.get("metadata") or {}).get("taskType") == task
            ]
            for task in ("answer", "planner", "followup")
        }
        missing = [task for task, indices in task_indices.items() if not indices]
        if missing:
            raise SystemExit(f"dev缺少任务类别：{missing}")
        for task, indices in task_indices.items():
            predev_task_metrics[task] = trainer.evaluate(
                eval_dataset=encoded["eval"].select(indices),
                metric_key_prefix=f"predev_{task}",
            )
    train_result = trainer.train(resume_from_checkpoint=args.resume_from_checkpoint)
    metrics = trainer.evaluate()
    if args.require_loss_drop:
        posttrain_metrics = trainer.evaluate(
            eval_dataset=encoded["train"], metric_key_prefix="posttrain"
        )
        relative_drop = (
            (pretrain_metrics["pretrain_loss"] - posttrain_metrics["posttrain_loss"])
            / pretrain_metrics["pretrain_loss"]
        )
        metrics["learningProof"] = {
            "examples": len(encoded["train"]),
            "pretrainLoss": pretrain_metrics["pretrain_loss"],
            "posttrainLoss": posttrain_metrics["posttrain_loss"],
            "lossDropped": (
                posttrain_metrics["posttrain_loss"]
                < pretrain_metrics["pretrain_loss"]
            ),
            "relativeLossDrop": relative_drop,
            "minimumRelativeLossDrop": args.minimum_relative_loss_drop,
        }
    if args.require_dev_loss_drop:
        predev_loss = predev_metrics["predev_loss"]
        postdev_loss = metrics["eval_loss"]
        metrics["devLearningProof"] = {
            "pretrainDevLoss": predev_loss,
            "posttrainDevLoss": postdev_loss,
            "lossDropped": postdev_loss < predev_loss,
            "relativeLossDrop": (predev_loss - postdev_loss) / predev_loss,
        }
    if args.require_dev_task_gates:
        task_proof = {}
        improved = 0
        for task, before in predev_task_metrics.items():
            indices = [
                index
                for index, row in enumerate(raw["eval"])
                if (row.get("metadata") or {}).get("taskType") == task
            ]
            after = trainer.evaluate(
                eval_dataset=encoded["eval"].select(indices),
                metric_key_prefix=f"postdev_{task}",
            )
            pre_loss = before[f"predev_{task}_loss"]
            post_loss = after[f"postdev_{task}_loss"]
            relative_drop = (pre_loss - post_loss) / pre_loss
            improved += int(post_loss < pre_loss)
            task_proof[task] = {
                "examples": len(indices),
                "pretrainDevLoss": pre_loss,
                "posttrainDevLoss": post_loss,
                "relativeLossDrop": relative_drop,
                "improved": post_loss < pre_loss,
                "regressedMoreThanTenPercent": relative_drop < -.10,
            }
        metrics["devTaskLearningProof"] = {
            "tasks": task_proof,
            "improvedTaskCount": improved,
            "requiredImprovedTaskCount": 2,
            "maximumAllowedRegression": .10,
        }
    metrics["trainMetrics"] = train_result.metrics
    metrics["trainExamples"] = len(encoded["train"])
    metrics["evalExamples"] = len(encoded["eval"])
    metrics["optimizerSteps"] = int(trainer.state.global_step)
    metrics["completedEpochs"] = float(trainer.state.epoch or 0.0)
    metrics["trainingConfig"] = {
        "bf16": True,
        "fp16": False,
        "epochs": args.epochs,
        "maxSteps": args.max_steps,
        "gradientAccumulation": args.gradient_accumulation,
        "learningRate": args.learning_rate,
        "maxLength": args.max_length,
        "lora": {
            "rank": args.lora_rank,
            "alpha": args.lora_alpha,
            "dropout": args.lora_dropout,
            "targetModules": target_modules,
        },
    }
    metrics["peakAllocatedGiB"] = round(
        torch.cuda.max_memory_allocated() / 1024**3, 3
    )
    metrics["peakReservedGiB"] = round(
        torch.cuda.max_memory_reserved() / 1024**3, 3
    )
    adapter_dir = args.output / "adapter"
    trainer.save_model(str(adapter_dir))
    tokenizer.save_pretrained(str(adapter_dir))
    metrics["passed"] = False
    metrics_path = args.output / "metrics.json"
    metrics_path.write_text(
        json.dumps(metrics, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    numeric_losses = [
        float(value)
        for key, value in metrics.items()
        if key.endswith("loss") and isinstance(value, (int, float))
    ]
    if any(not math.isfinite(value) for value in numeric_losses):
        raise SystemExit("训练或评测loss出现NaN/Inf")
    if metrics["peakReservedGiB"] > args.max_peak_reserved_gib:
        raise SystemExit(
            f"peak reserved VRAM {metrics['peakReservedGiB']} GiB exceeds "
            f"the {args.max_peak_reserved_gib} GiB gate"
        )
    if args.require_loss_drop and (
        not metrics["learningProof"]["lossDropped"]
        or metrics["learningProof"]["relativeLossDrop"] < args.minimum_relative_loss_drop
    ):
        raise SystemExit("learning-proof loss drop did not meet the configured gate")
    if args.require_dev_loss_drop and not metrics["devLearningProof"]["lossDropped"]:
        raise SystemExit("best adapter dev loss did not improve over the base model")
    if args.require_dev_task_gates:
        proof = metrics["devTaskLearningProof"]
        if proof["improvedTaskCount"] < proof["requiredImprovedTaskCount"]:
            raise SystemExit("少于两个dev任务类别相对基座改善")
        if any(
            value["regressedMoreThanTenPercent"]
            for value in proof["tasks"].values()
        ):
            raise SystemExit("至少一个dev任务类别相对基座恶化超过10%")
    if args.expected_optimizer_steps and metrics["optimizerSteps"] != args.expected_optimizer_steps:
        raise SystemExit(
            f"优化步数{metrics['optimizerSteps']}不等于预期{args.expected_optimizer_steps}"
        )
    if args.expected_epochs and abs(metrics["completedEpochs"] - args.expected_epochs) > 1e-6:
        raise SystemExit(
            f"完成轮数{metrics['completedEpochs']}不等于预期{args.expected_epochs}"
        )
    metrics["passed"] = True
    metrics_path.write_text(
        json.dumps(metrics, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
