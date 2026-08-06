#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import platform
import tempfile
import time
from pathlib import Path

import peft
import torch
import transformers
from peft import LoraConfig, PeftModel, TaskType, get_peft_model
from transformers import BertConfig, BertModel

from prooflaunch_remix.files import atomic_write_text
from prooflaunch_remix.v10_adapter_stack import (
    PeftHotSwapBackend,
    adapter_directory_sha256,
)
from prooflaunch_remix.v10_supply_chain import stable_sha256


ROOT = Path(__file__).resolve().parents[1]


def _base(config: BertConfig) -> BertModel:
    torch.manual_seed(7)
    return BertModel(config)


def _set_adapter(model: PeftModel, seed: int) -> None:
    torch.manual_seed(seed)
    with torch.no_grad():
        for name, parameter in model.named_parameters():
            if "lora_A.default" in name or "lora_B.default" in name:
                parameter.copy_(torch.randn_like(parameter) * 0.25)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "evidence/v10/peft-hotswap-local-probe.json",
    )
    args = parser.parse_args()
    config = BertConfig(
        vocab_size=32,
        hidden_size=16,
        num_hidden_layers=1,
        num_attention_heads=2,
        intermediate_size=24,
    )
    peft_config = LoraConfig(
        task_type=TaskType.FEATURE_EXTRACTION,
        r=2,
        lora_alpha=4,
        target_modules=["query", "value"],
        lora_dropout=0.0,
        bias="none",
    )
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        first_path = root / "first"
        second_path = root / "second"
        source = get_peft_model(_base(config), peft_config)
        _set_adapter(source, 31)
        source.save_pretrained(first_path)
        _set_adapter(source, 47)
        source.save_pretrained(second_path)
        model = PeftModel.from_pretrained(_base(config), first_path).eval()
        inputs = {
            "input_ids": torch.tensor([[1, 2, 3, 4]]),
            "attention_mask": torch.ones((1, 4), dtype=torch.long),
        }
        with torch.inference_mode():
            before = model(**inputs).last_hidden_state.detach().clone()
        expected = adapter_directory_sha256(second_path)
        started = time.perf_counter_ns()
        swap = PeftHotSwapBackend().hotswap(
            model,
            second_path,
            adapter_name="default",
            expected_sha256=expected,
            device="cpu",
        )
        elapsed_ns = time.perf_counter_ns() - started
        with torch.inference_mode():
            after = model(**inputs).last_hidden_state.detach().clone()
        maximum_delta = float(torch.max(torch.abs(before - after)).item())
        body = {
            "schema": "ProofLaunchRealPeftHotSwapProbeV1",
            "status": "passed" if maximum_delta > 0 else "failed",
            "actual_peft_runtime": True,
            "backend": swap["backend"],
            "platform": platform.platform(),
            "torch_version": torch.__version__,
            "peft_version": peft.__version__,
            "transformers_version": transformers.__version__,
            "model_fixture": "randomly_initialized_tiny_bert_no_download",
            "adapter_method": "lora",
            "adapter_sha256": expected,
            "in_place_storage_preserved": swap["in_place_storage_preserved"],
            "parameter_slots": swap["parameter_slots"],
            "output_changed": maximum_delta > 0,
            "maximum_output_delta": maximum_delta,
            "cpu_hotswap_latency_ns": elapsed_ns,
            "radeon_metric": False,
            "training_observed": False,
            "truth_boundary": (
                "This is a real PEFT LoRA in-place hotswap integration probe on a "
                "random tiny CPU model. It proves the integration path, not Radeon "
                "latency, GTM capability, adapter training, or model quality."
            ),
        }
        receipt = {**body, "receipt_sha256": stable_sha256(body)}
        atomic_write_text(args.output, json.dumps(receipt, indent=2) + "\n")
        print(json.dumps({"status": receipt["status"], "receipt_sha256": receipt["receipt_sha256"]}))
        return 0 if receipt["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
