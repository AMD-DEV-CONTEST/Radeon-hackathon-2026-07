# -*- coding: utf-8 -*-

from __future__ import annotations

import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import build_public_submission_snapshot as snapshot  # noqa: E402


def test_snapshot_includes_agent_training_and_deploy_but_excludes_private_data(tmp_path: Path) -> None:
    source = tmp_path / "project"
    (source / "backend").mkdir(parents=True)
    (source / "training" / "workspace").mkdir(parents=True)
    (source / "deploy" / "cloud").mkdir(parents=True)
    (source / "backend" / "agent_runtime.py").write_text("PLAN='agent-plan-v1'", encoding="utf-8")
    (source / "training" / "train_lora_rocm.py").write_text("MODEL='Qwen3-14B'", encoding="utf-8")
    (source / "training" / "workspace" / "agent_sft_test.jsonl").write_text("sealed", encoding="utf-8")
    (source / "deploy" / "cloud" / "start.sh").write_text("#!/bin/sh", encoding="utf-8")
    (source / "requirements.txt").write_text("fastapi\n", encoding="utf-8")
    output = tmp_path / "public"
    result = snapshot.build(source, output)
    assert result["passed"] is True
    assert (output / "backend" / "agent_runtime.py").is_file()
    assert (output / "training" / "train_lora_rocm.py").is_file()
    assert not (output / "training" / "workspace").exists()


def test_snapshot_excludes_review_revision_scripts_and_web_archives(tmp_path: Path) -> None:
    source = tmp_path / "project"
    (source / "training").mkdir(parents=True)
    (source / "web" / "archive").mkdir(parents=True)
    (source / "training" / "train_lora_rocm.py").write_text("SAFE=True", encoding="utf-8")
    (source / "training" / "apply_user_gold_revisions_round4.py").write_text(
        "REVIEW_COMMENT='private'", encoding="utf-8"
    )
    (source / "web" / "index.html").write_text("current", encoding="utf-8")
    (source / "web" / "archive" / "old.html").write_text("old", encoding="utf-8")
    output = tmp_path / "public"
    snapshot.build(source, output)
    assert (output / "training" / "train_lora_rocm.py").is_file()
    assert not (output / "training" / "apply_user_gold_revisions_round4.py").exists()
    assert (output / "web" / "index.html").is_file()
    assert not (output / "web" / "archive").exists()


def test_snapshot_excludes_private_game_archive_regression(tmp_path: Path) -> None:
    source = tmp_path / "project"
    private_regression = source / "backend" / "tests" / "test_library_importers_coach.py"
    private_regression.parent.mkdir(parents=True)
    private_regression.write_text("OWNER_DISPLAY_NAME='private'", encoding="utf-8")
    public_test = source / "backend" / "tests" / "test_agent_runtime.py"
    public_test.write_text("SAFE=True", encoding="utf-8")
    output = tmp_path / "public"
    snapshot.build(source, output)
    assert not (output / private_regression.relative_to(source)).exists()
    assert (output / public_test.relative_to(source)).is_file()


def test_snapshot_rejects_absolute_user_paths(tmp_path: Path) -> None:
    source = tmp_path / "project"
    (source / "backend").mkdir(parents=True)
    private_path = "C:/" + "Users/alice/private"
    (source / "backend" / "bad.py").write_text(f"PATH='{private_path}'", encoding="utf-8")
    with pytest.raises(snapshot.SnapshotError, match="safety scan failed"):
        snapshot.build(source, tmp_path / "public")


def test_snapshot_includes_only_explicit_public_training_fixture(tmp_path: Path) -> None:
    source = tmp_path / "project"
    data = source / "training" / "data"
    data.mkdir(parents=True)
    public_fixture = data / "classical_sft_train.jsonl"
    private_fixture = data / "creator_gold.jsonl"
    public_fixture.write_text('{"license":"public-domain"}\n', encoding="utf-8")
    private_fixture.write_text('{"license":"creator-authorized"}\n', encoding="utf-8")
    output = tmp_path / "public"
    snapshot.build(source, output)
    assert (output / public_fixture.relative_to(source)).is_file()
    assert not (output / private_fixture.relative_to(source)).exists()
