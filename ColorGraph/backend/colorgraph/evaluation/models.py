from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class StrictEvaluationModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class HardwareSnapshot(StrictEvaluationModel):
    operating_system: str
    python_version: str
    torch_version: str | None = None
    runtime: str
    device_name: str
    device_memory_mb: int | None = None


class EvaluatedMaterial(StrictEvaluationModel):
    id: str
    task: str
    split: str
    media_sha256: str
    annotation_sha256: str


class GoldGateRule(StrictEvaluationModel):
    minimum: float | None = None
    maximum: float | None = None

    @model_validator(mode="after")
    def validate_bound(self) -> GoldGateRule:
        if (self.minimum is None) == (self.maximum is None):
            raise ValueError(
                "Gold gate rule requires exactly one of minimum or maximum"
            )
        return self


class GoldGatePolicy(StrictEvaluationModel):
    schema_version: str = "colorgraph.gold-gate-policy/v1"
    policy_id: str = Field(min_length=1)
    created_at: datetime
    manifest_id: str = Field(min_length=1)
    manifest_version: str = Field(min_length=1)
    manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    annotation_guideline_version: str = Field(min_length=1)
    calibration_observation_path: str = Field(min_length=1)
    calibration_observation_sha256: str = Field(
        pattern=r"^[0-9a-f]{64}$"
    )
    calibration_material_ids: dict[str, list[str]]
    gates: dict[str, GoldGateRule]
    approved_by: list[str] = Field(min_length=1)
    test_materials_accessed: bool = False

    @model_validator(mode="after")
    def validate_policy(self) -> GoldGatePolicy:
        calibration_path = Path(self.calibration_observation_path)
        if (
            calibration_path.is_absolute()
            or ".." in calibration_path.parts
            or calibration_path == Path(".")
        ):
            raise ValueError(
                "Gold calibration observation path must be a contained "
                "relative path"
            )
        if self.test_materials_accessed:
            raise ValueError(
                "Gold gate policy cannot be frozen after test access"
            )
        if not self.calibration_material_ids:
            raise ValueError(
                "Gold gate policy requires calibration material bindings"
            )
        for section, material_ids in self.calibration_material_ids.items():
            if not section.strip() or not material_ids:
                raise ValueError(
                    "Gold gate policy calibration bindings cannot be empty"
                )
            if (
                any(not value.strip() for value in material_ids)
                or len(material_ids) != len(set(material_ids))
            ):
                raise ValueError(
                    "Gold gate policy material IDs must be non-empty and unique"
                )
        if not self.gates:
            raise ValueError("Gold gate policy requires metric gates")
        if (
            any(not value.strip() for value in self.approved_by)
            or len(self.approved_by) != len(set(self.approved_by))
        ):
            raise ValueError(
                "Gold gate policy approver IDs must be non-empty and unique"
            )
        return self


class GoldEvaluationEvidence(StrictEvaluationModel):
    audit_path: str
    audit_sha256: str
    audit_passed: bool
    annotation_guideline_version: str
    gate_policy_path: str
    gate_policy_sha256: str
    gate_policy_id: str
    calibration_observation_path: str
    calibration_observation_sha256: str
    qualified_test_material_ids: list[str]
    section_material_ids: dict[str, list[str]]
    all_sections_fully_bound: bool


class EvaluationReport(StrictEvaluationModel):
    schema_version: str = "colorgraph.evaluation-report/v1"
    evaluator_version: str = "colorgraph.evaluator/v1"
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    manifest_id: str
    manifest_version: str
    manifest_sha256: str
    observation_sha256: str
    configuration: dict[str, Any]
    hardware: HardwareSnapshot
    materials: list[EvaluatedMaterial]
    metrics: dict[str, dict[str, float]]
    gates: dict[str, bool] = Field(default_factory=dict)
    evidence_status: Literal["engineering_only", "gold_qualified"] = (
        "engineering_only"
    )
    release_eligible: bool = False
    gold_evidence: GoldEvaluationEvidence | None = None
    notes: list[str] = Field(default_factory=list)
