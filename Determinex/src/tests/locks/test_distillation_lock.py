"""
DISTILLATION_LOCK_001 acceptance tests.

Locks the compression/deployment control plane: specialist units cannot deploy
without eval/safety/license locks, signed corpus, deduped splits, cards, and
safety regression evidence.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))

from units.distillation_guard import DistillationManifest, validate_distillation_manifest
from units.unit_registry import UnitRegistry, UnitSpec


def _locks(lock_dir: Path) -> None:
    lock_dir.mkdir(parents=True, exist_ok=True)
    for name in (
        "RUST_REPAIR_LOCK_001.json",
        "SENTINEL_LOCK_001.json",
        "CORPUS_LICENSE_LOCK_001.json",
    ):
        (lock_dir / name).write_text("{}", encoding="utf-8")


def _unit() -> UnitSpec:
    return UnitSpec(
        unit_id="rust_repair_v001",
        specialty="rust.unwrap.result.repair",
        model="T:/determinex-models/rust-repair-v001",
        training_corpus=["T:/determinex_corpus/code_verdict/rust/2026-05-27.jsonl"],
        eval_lock="RUST_REPAIR_LOCK_001.json",
        safety_lock="SENTINEL_LOCK_001.json",
        license_clearance="CORPUS_LICENSE_LOCK_001.json",
        allowed_tasks=["rust_compile_repair", "cargo_test_repair"],
        blocked_tasks=["security_exploit", "unknown_network_code"],
    )


def _manifest(root: Path) -> DistillationManifest:
    (root / "MODEL_CARD.md").write_text("# Model Card\n", encoding="utf-8")
    (root / "DATA_CARD.md").write_text("# Data Card\n", encoding="utf-8")
    return DistillationManifest(
        unit_id="rust_repair_v001",
        corpus_signed=True,
        no_unsigned_rows=True,
        license_policy_enforced=True,
        train_eval_split_deduped=True,
        specialist_beats_baseline=True,
        safety_regression_passed=True,
        model_card_path="MODEL_CARD.md",
        data_card_path="DATA_CARD.md",
        eval_lock="RUST_REPAIR_LOCK_001.json",
    )


class TestUnitRegistry:
    def test_register_and_reload_unit(self, tmp_path):
        registry = UnitRegistry(tmp_path / "units.json", tmp_path / "locks")
        registry.register(_unit())
        reloaded = UnitRegistry(tmp_path / "units.json", tmp_path / "locks")
        assert "rust_repair_v001" in reloaded.units

    def test_duplicate_unit_rejected(self, tmp_path):
        registry = UnitRegistry(tmp_path / "units.json", tmp_path / "locks")
        registry.register(_unit())
        try:
            registry.register(_unit())
        except ValueError as exc:
            assert "already exists" in str(exc)
        else:
            raise AssertionError("duplicate unit must be rejected")

    def test_invalid_status_rejected(self, tmp_path):
        registry = UnitRegistry(tmp_path / "units.json", tmp_path / "locks")
        unit = _unit()
        unit.status = "wild"
        try:
            registry.register(unit)
        except ValueError as exc:
            assert "invalid unit status" in str(exc)
        else:
            raise AssertionError("invalid status must be rejected")

    def test_status_regression_rejected(self, tmp_path):
        registry = UnitRegistry(tmp_path / "units.json", tmp_path / "locks")
        registry.register(_unit())
        registry.promote("rust_repair_v001", "evaluated")
        try:
            registry.promote("rust_repair_v001", "trained")
        except ValueError as exc:
            assert "status regression" in str(exc)
        else:
            raise AssertionError("status regression must be rejected")

    def test_missing_locks_block_deploy(self, tmp_path):
        registry = UnitRegistry(tmp_path / "units.json", tmp_path / "locks")
        registry.register(_unit())
        registry.promote("rust_repair_v001", "safety_checked")
        ok, reason = registry.can_deploy("rust_repair_v001")
        assert ok is False
        assert "missing_lock" in reason

    def test_deploy_requires_safety_checked_status(self, tmp_path):
        _locks(tmp_path / "locks")
        registry = UnitRegistry(tmp_path / "units.json", tmp_path / "locks")
        registry.register(_unit())
        ok, reason = registry.can_deploy("rust_repair_v001")
        assert ok is False
        assert "status_not_safety_checked" in reason

    def test_deploy_succeeds_with_all_locks(self, tmp_path):
        _locks(tmp_path / "locks")
        registry = UnitRegistry(tmp_path / "units.json", tmp_path / "locks")
        registry.register(_unit())
        registry.promote("rust_repair_v001", "safety_checked")
        deployed = registry.deploy("rust_repair_v001")
        assert deployed.status == "deployed"

    def test_route_returns_only_deployed_allowed_units(self, tmp_path):
        _locks(tmp_path / "locks")
        registry = UnitRegistry(tmp_path / "units.json", tmp_path / "locks")
        registry.register(_unit())
        registry.promote("rust_repair_v001", "safety_checked")
        registry.deploy("rust_repair_v001")
        assert [u.unit_id for u in registry.route("cargo_test_repair")] == ["rust_repair_v001"]
        assert registry.route("security_exploit") == []


class TestDistillationGuard:
    def test_valid_manifest_passes(self, tmp_path):
        manifest = _manifest(tmp_path)
        ok, reason = validate_distillation_manifest(manifest, tmp_path)
        assert ok is True
        assert reason == "ok"

    def test_unsigned_corpus_blocks(self, tmp_path):
        manifest = _manifest(tmp_path)
        manifest.corpus_signed = False
        ok, reason = validate_distillation_manifest(manifest, tmp_path)
        assert ok is False
        assert reason == "corpus_not_signed"

    def test_unsigned_rows_block(self, tmp_path):
        manifest = _manifest(tmp_path)
        manifest.no_unsigned_rows = False
        ok, reason = validate_distillation_manifest(manifest, tmp_path)
        assert ok is False
        assert reason == "unsigned_rows_present"

    def test_license_policy_required(self, tmp_path):
        manifest = _manifest(tmp_path)
        manifest.license_policy_enforced = False
        ok, reason = validate_distillation_manifest(manifest, tmp_path)
        assert ok is False
        assert reason == "license_policy_not_enforced"

    def test_deduped_split_required(self, tmp_path):
        manifest = _manifest(tmp_path)
        manifest.train_eval_split_deduped = False
        ok, reason = validate_distillation_manifest(manifest, tmp_path)
        assert ok is False
        assert reason == "train_eval_split_not_deduped"

    def test_specialist_must_beat_baseline(self, tmp_path):
        manifest = _manifest(tmp_path)
        manifest.specialist_beats_baseline = False
        ok, reason = validate_distillation_manifest(manifest, tmp_path)
        assert ok is False
        assert reason == "specialist_does_not_beat_baseline"

    def test_safety_regression_required(self, tmp_path):
        manifest = _manifest(tmp_path)
        manifest.safety_regression_passed = False
        ok, reason = validate_distillation_manifest(manifest, tmp_path)
        assert ok is False
        assert reason == "safety_regression_failed"

    def test_model_card_required(self, tmp_path):
        manifest = _manifest(tmp_path)
        (tmp_path / "MODEL_CARD.md").unlink()
        ok, reason = validate_distillation_manifest(manifest, tmp_path)
        assert ok is False
        assert reason == "missing_model_card"

    def test_data_card_required(self, tmp_path):
        manifest = _manifest(tmp_path)
        (tmp_path / "DATA_CARD.md").unlink()
        ok, reason = validate_distillation_manifest(manifest, tmp_path)
        assert ok is False
        assert reason == "missing_data_card"

    def test_eval_lock_required(self, tmp_path):
        manifest = _manifest(tmp_path)
        manifest.eval_lock = ""
        ok, reason = validate_distillation_manifest(manifest, tmp_path)
        assert ok is False
        assert reason == "missing_eval_lock"
