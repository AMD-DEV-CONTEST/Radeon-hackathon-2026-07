# -*- coding: utf-8 -*-

from __future__ import annotations

import sys
import json
from pathlib import Path

import pytest

TRAINING = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TRAINING))

import train_lora_rocm


def test_qwen_revision_is_pinned() -> None:
    assert train_lora_rocm.QWEN3_14B_REVISION == "40c069824f4251a91eefaf281ebe4c544efd3e18"


def test_smoke_vram_gate_is_45_gib() -> None:
    source = Path(train_lora_rocm.__file__).read_text(encoding="utf-8")
    assert 'default=45.0' in source
    assert 'peakReservedGiB' in source


def test_defaults_match_frozen_v3_training_recipe() -> None:
    source = Path(train_lora_rocm.__file__).read_text(encoding="utf-8")
    assert '"--learning-rate", type=float, default=3e-5' in source
    assert '"--lora-rank", type=int, default=8' in source
    assert '"--lora-alpha", type=int, default=16' in source
    assert '"--lora-dropout", type=float, default=.10' in source
    assert 'default="q_proj,k_proj,v_proj,o_proj"' in source


def test_micro_and_full_learning_gates_are_enforced() -> None:
    source = Path(train_lora_rocm.__file__).read_text(encoding="utf-8")
    assert 'minimum-relative-loss-drop' in source
    assert 'relativeLossDrop' in source
    assert 'require-dev-loss-drop' in source
    assert 'best adapter dev loss did not improve' in source
    assert 'require-dev-task-gates' in source
    assert 'regressedMoreThanTenPercent' in source
    assert 'expected-optimizer-steps' in source
    assert 'expected-epochs' in source
    assert 'metrics["passed"] = True' in source


class FakeTokenizer:
    def apply_chat_template(
        self, messages, *, tokenize, add_generation_prompt, enable_thinking
    ):
        assert tokenize is True
        assert enable_thinking is False
        values = [10]
        for message in messages:
            role = {"system": 11, "user": 12, "assistant": 13}[message["role"]]
            values.extend([role, *[100 + ord(char) % 50 for char in message["content"]], 14])
        if add_generation_prompt:
            values.append(13)
        return values


def row() -> dict:
    return {
        "messages": [
            {"role": "system", "content": "规则"},
            {"role": "user", "content": "问题"},
            {"role": "assistant", "content": "回答"},
        ],
        "metadata": {"sourceCaseId": "case-1"},
    }


def test_encode_example_masks_everything_before_final_assistant():
    encoded = train_lora_rocm.encode_example(FakeTokenizer(), row(), 100)
    first_loss = next(
        index for index, value in enumerate(encoded["labels"]) if value != -100
    )
    assert encoded["labels"][:first_loss] == [-100] * first_loss
    assert encoded["labels"][first_loss:] == encoded["input_ids"][first_loss:]
    assert encoded["loss_tokens"] > 0


def test_encode_example_refuses_silent_truncation():
    with pytest.raises(ValueError, match="禁止静默截断"):
        train_lora_rocm.encode_example(FakeTokenizer(), row(), 5)


def test_encode_example_requires_final_assistant():
    value = row()
    value["messages"][-1]["role"] = "user"
    with pytest.raises(ValueError, match="最后一条必须是assistant"):
        train_lora_rocm.encode_example(FakeTokenizer(), value, 100)


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.write_text(
        "".join(json.dumps(value, ensure_ascii=False) + "\n" for value in rows),
        encoding="utf-8",
    )


def test_v3_manifest_binds_train_dev_roles_and_rejects_sealed(tmp_path: Path) -> None:
    train = tmp_path / "train.jsonl"
    dev = tmp_path / "dev.jsonl"
    sealed = tmp_path / "sealed.jsonl"
    base = row()
    base["metadata"]["split"] = "train"
    _write_jsonl(train, [base])
    dev_row = json.loads(json.dumps(base))
    dev_row["metadata"]["split"] = "dev"
    _write_jsonl(dev, [dev_row])
    sealed_row = json.loads(json.dumps(base))
    sealed_row["metadata"]["split"] = "sealed"
    _write_jsonl(sealed, [sealed_row])
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({
        "schemaVersion": "yijian-agent-sft-v3",
        "passed": True,
        "artifacts": {
            "train": {"role": "train", "filename": train.name, "sha256": train_lora_rocm.sha256_file(train), "rows": 1},
            "dev": {"role": "dev", "filename": dev.name, "sha256": train_lora_rocm.sha256_file(dev), "rows": 1},
            "sealed": {"role": "sealed", "sourceFilename": sealed.name, "sha256": train_lora_rocm.sha256_file(sealed), "rows": 1},
        },
    }), encoding="utf-8")

    assert train_lora_rocm._validate_manifest(manifest, train, dev)["passed"] is True
    with pytest.raises(SystemExit, match="sealed test"):
        train_lora_rocm._validate_manifest(manifest, train, sealed)
