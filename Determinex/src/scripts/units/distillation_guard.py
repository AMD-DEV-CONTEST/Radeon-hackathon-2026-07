"""
Distillation lock guard.

Compression is allowed only from signed, licensed, deduped, safety-checked
corpus rows with model/data cards and held-out improvement evidence.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass
class DistillationManifest:
    unit_id: str
    corpus_signed: bool
    no_unsigned_rows: bool
    license_policy_enforced: bool
    train_eval_split_deduped: bool
    specialist_beats_baseline: bool
    safety_regression_passed: bool
    model_card_path: str
    data_card_path: str
    eval_lock: str

    def to_dict(self) -> dict:
        return self.__dict__.copy()


def validate_distillation_manifest(manifest: DistillationManifest, root: Path) -> tuple[bool, str]:
    checks = {
        "corpus_not_signed": manifest.corpus_signed,
        "unsigned_rows_present": manifest.no_unsigned_rows,
        "license_policy_not_enforced": manifest.license_policy_enforced,
        "train_eval_split_not_deduped": manifest.train_eval_split_deduped,
        "specialist_does_not_beat_baseline": manifest.specialist_beats_baseline,
        "safety_regression_failed": manifest.safety_regression_passed,
    }
    for reason, passed in checks.items():
        if not passed:
            return False, reason
    if not (root / manifest.model_card_path).is_file():
        return False, "missing_model_card"
    if not (root / manifest.data_card_path).is_file():
        return False, "missing_data_card"
    if not manifest.eval_lock:
        return False, "missing_eval_lock"
    return True, "ok"
