#!/usr/bin/env python3
from __future__ import annotations

import json
from dataclasses import asdict
from enum import Enum
from pathlib import Path
from typing import Any

from prooflaunch_remix.files import atomic_write_text
from prooflaunch_remix.v10_distillation_stack import (
    HiddenFeaturePair,
    capability_retention,
    expected_calibration_error,
    freeze_distillation_stack_v1,
    logits_kl_loss,
    teacher_elimination_reasons,
    TeacherCandidate,
    token_efficiency,
    wall_clock_benefit,
)
from prooflaunch_remix.v10_distillation import OutputRightsStatus
from prooflaunch_remix.v10_supply_chain import stable_sha256


ROOT = Path(__file__).resolve().parents[1]


def normalize(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, dict):
        return {str(normalize(key)): normalize(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [normalize(item) for item in value]
    return value


def main() -> int:
    stack = normalize(freeze_distillation_stack_v1())
    mechanical = {
        "schema": "ProofLaunchDistillationStackMechanicalFixtureV1",
        "fixture_scope": "synthetic deterministic contract verification only",
        "stack_content_sha256": stack["content_sha256"],
        "computed_examples": {
            "logits_kl": logits_kl_loss((0.7, 0.3), (0.4, 0.6)),
            "hidden_feature_masked_mse": HiddenFeaturePair(
                teacher=(1.0, 2.0, 100.0),
                student_projected=(0.0, 4.0, -100.0),
                projection_revision="synthetic-projection@v1",
                attention_mask=(True, True, False),
            ).masked_mse(),
            "capability_retention": capability_retention(
                {"vision": 0.8, "agent": 0.8},
                {"vision": 1.0, "agent": 0.4},
            ),
            "expected_calibration_error": expected_calibration_error(
                (0.8, 0.6), (1, 0), (1, 1), bins=5
            ),
            "token_efficiency_per_1k": token_efficiency(5, 100),
            "wall_clock_benefit": wall_clock_benefit(120, 60),
        },
        "unresolved_teacher_probe": {
            "teacher_id": "minimax-unresolved-h3-claim",
            "reasons": teacher_elimination_reasons(
                TeacherCandidate(
                    teacher_id="minimax-unresolved-h3-claim",
                    revision="UNRESOLVED",
                    revision_verified=False,
                    rights_status=OutputRightsStatus.REVIEW_REQUIRED,
                    information_gain=None,
                    observed_examples=0,
                )
            ),
        },
        "runtime_truth": {
            "training_observed": False,
            "radeon_execution_observed": False,
            "external_teacher_calls_observed": False,
            "real_metric_values": None,
            "selected_adapter": None,
        },
        "closure_basis": "Executable lane, target, control, metric, elimination and card contracts plus deterministic synthetic unit tests; not a training result.",
    }
    mechanical["content_sha256"] = stable_sha256(mechanical)
    atomic_write_text(
        ROOT / "config/cortex_x_v10_distillation_stack_v1.json",
        json.dumps(stack, ensure_ascii=False, indent=2) + "\n",
    )
    atomic_write_text(
        ROOT / "evidence/v10/distillation-stack-v1-mechanical-fixture.json",
        json.dumps(normalize(mechanical), ensure_ascii=False, indent=2) + "\n",
    )
    print(
        json.dumps(
            {
                "status": stack["status"],
                "lane_count": len(stack["lanes"]),
                "control_count": len(stack["controls"]["arms"]),
                "training_observed": stack["runtime_truth"]["training_observed"],
                "content_sha256": stack["content_sha256"],
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
