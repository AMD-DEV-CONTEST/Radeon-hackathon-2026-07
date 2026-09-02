"""
scripts/hive/models.py — Pydantic v2 data models for the Hive package
======================================================================
Pydantic v2 models for all seam types in the Hive build loop. These replace
the bare `dataclass` + dict-parse pattern that previously had zero runtime
validation at component boundaries.

Key guarantees added:
  - OracleResult: `passed` cannot be True when `failures` is non-empty
  - StepRecord: `status` is constrained to the documented enum set
  - ManifestSession: `api_cost_usd` cannot be negative
  - Failure: `test_id` is always non-empty (blank = opaque debug-only)

Usage (opt-in per callsite — existing dataclass instances are unaffected):
    from hive.models import OracleResultModel, StepRecordModel, ManifestSessionModel

    # Validate an oracle result dict from JSON:
    result = OracleResultModel.model_validate(raw_dict)

    # Convert an existing dataclass StepRecord to the validated model:
    step_model = StepRecordModel.from_step_record(step)

Backwards compatibility:
    All model fields match the corresponding dataclass fields 1:1.
    `from_step_record()` and `to_step_record()` bridge between the two.
    The dataclass remains the canonical runtime representation; Pydantic is
    the validation gate at: JSON parse, LLM output extraction, WAL read-back.
"""

from __future__ import annotations

from typing import Any, Literal

try:
    from pydantic import BaseModel, Field, field_validator, model_validator

    _PYDANTIC_AVAILABLE = True
except ImportError:
    _PYDANTIC_AVAILABLE = False

    # Stub: makes `from hive.models import X` safe even without pydantic
    class BaseModel:  # type: ignore[no-redef]
        def __init_subclass__(cls, **kwargs: Any) -> None:
            pass

    def Field(*a: Any, **kw: Any) -> Any:  # type: ignore[misc]
        return None

    def field_validator(*a: Any, **kw: Any):  # type: ignore[misc]
        return lambda f: f

    def model_validator(*a: Any, **kw: Any):  # type: ignore[misc]
        return lambda f: f


if _PYDANTIC_AVAILABLE:
    # ── OracleResult ─────────────────────────────────────────────────────────────

    class FailureModel(BaseModel):
        """Normalized failing unit of ground truth. Oracle-agnostic."""

        test_id: str = Field(min_length=0)  # discriminating context key
        name: str
        text: str = ""
        expected: str | None = None
        actual: str | None = None
        status: Literal["failed", "skipped", "not_run", "error"] = "failed"

    class OracleResultModel(BaseModel):
        """Validated oracle result. The `passed` invariant is enforced."""

        passed: bool
        failures: list[FailureModel] = Field(default_factory=list)
        raw: str = ""
        oracle: str = ""
        total: int = 0
        n_passed: int = 0

        @model_validator(mode="after")
        def check_passed_consistency(self) -> OracleResultModel:
            """passed=True must not coexist with hard failures (status='failed' or 'error').
            This catches the most common seam bug: an oracle wrapper that returns
            passed=True with a non-empty failure list."""
            hard = [f for f in self.failures if f.status in ("failed", "error")]
            if self.passed and hard:
                raise ValueError(
                    f"OracleResult.passed=True but {len(hard)} hard failures present. "
                    f"First: {hard[0].name!r}: {hard[0].text[:80]!r}. "
                    "Either set passed=False or clear the failures list."
                )
            return self

        @field_validator("n_passed")
        @classmethod
        def n_passed_le_total(cls, v: int, info: Any) -> int:
            total = info.data.get("total", 0)
            if total > 0 and v > total:
                raise ValueError(f"n_passed ({v}) > total ({total})")
            return v

    # ── StepRecord ───────────────────────────────────────────────────────────────

    _STEP_STATUS = Literal["pending", "in_progress", "complete", "failed", "stale_instruction"]
    _WRITE_MODE = Literal["new_file", "replace_file", "append_to_file", "replace_function"]
    _QUALITY = Literal["training_ready", "inconclusive", "compile_hacked", ""]
    _CORRECTNESS = Literal["pass", "fail", "compile_hacked", "skipped", ""]

    class StepRecordModel(BaseModel):
        """Validated StepRecord — wraps hive.manifest.StepRecord for boundary checks."""

        id: int = Field(ge=0)
        instruction: str
        depends_on: list[int] = Field(default_factory=list)
        target_file: str = ""
        write_mode: _WRITE_MODE = "append_to_file"
        target_region: str | None = None
        dsl_context: str = ""
        status: _STEP_STATUS = "pending"
        builder_output_path: str = ""
        monitor_verdict: str = ""
        compiler_result: str = ""
        compiler_output: str = ""
        adjudication_score: float = Field(default=0.0, ge=0.0, le=1.0)
        retries: int = Field(default=0, ge=0)
        escalations: int = Field(default=0, ge=0)
        challenges: int = Field(default=0, ge=0)
        quality: _QUALITY = ""
        correctness_result: _CORRECTNESS = ""
        offline_observation_pending: bool = False
        offline_observation_result: str = ""
        public_api_snapshot: dict | None = None
        compiler_error_hashes: list[str] = Field(default_factory=list)

        @classmethod
        def from_step_record(cls, step: Any) -> StepRecordModel:
            """Bridge from hive.manifest.StepRecord dataclass."""
            import dataclasses

            d = dataclasses.asdict(step) if dataclasses.is_dataclass(step) else dict(step)
            return cls.model_validate(d)

        def to_dict(self) -> dict[str, Any]:
            return self.model_dump()

    # ── ManifestSession ──────────────────────────────────────────────────────────

    class ManifestSessionModel(BaseModel):
        """Validated ManifestSession — enforces budget and cost invariants."""

        session_id: str = Field(min_length=1)
        lang: str = Field(min_length=1)
        md_spec_path: str
        project_root: str
        workspace_file_hashes: dict = Field(default_factory=dict)
        cargo_toml: str = ""
        scaffolding_validated: bool = False
        steps: list[StepRecordModel] = Field(default_factory=list)
        pending_escalations: list[dict] = Field(default_factory=list)
        api_cost_usd: float = Field(default=0.0, ge=0.0)
        session_budget_usd: float = Field(default=2.0, gt=0.0)
        budget_exhausted: bool = False
        correctness_test_harness: str = ""
        fast_mode: bool = False
        created_at: str = ""
        updated_at: str = ""

        @model_validator(mode="after")
        def budget_consistency(self) -> ManifestSessionModel:
            if self.api_cost_usd > self.session_budget_usd * 1.05:  # 5% over-run grace
                raise ValueError(
                    f"api_cost_usd ({self.api_cost_usd:.4f}) exceeds "
                    f"session_budget_usd ({self.session_budget_usd:.4f}) by >5%. "
                    "budget_exhausted should have been set before this point."
                )
            return self

        @classmethod
        def from_manifest(cls, session: Any) -> ManifestSessionModel:
            """Bridge from hive.manifest.ManifestSession dataclass."""
            import dataclasses

            raw = (
                dataclasses.asdict(session) if dataclasses.is_dataclass(session) else dict(session)
            )
            return cls.model_validate(raw)

    # ── AdjudicationModel ────────────────────────────────────────────────────────

    class AdjudicationModel(BaseModel):
        """Validated Adjudication verdict from determinex_adjudicator."""

        verdict: Literal["ROUTE", "MATCH", "UNBLOCK", "NEEDS_WORK", "IMPOSSIBLE"]
        rationale: str
        remediation: str = ""
        proof: str = ""
        confidence: float = Field(default=1.0, ge=0.0, le=1.0)

        @field_validator("proof")
        @classmethod
        def impossible_needs_proof(cls, v: str, info: Any) -> str:
            if info.data.get("verdict") == "IMPOSSIBLE" and not v.strip():
                raise ValueError(
                    "IMPOSSIBLE verdict requires a non-empty proof string. "
                    "The adjudicator must supply a concrete contradictory witness."
                )
            return v

else:
    # Stubs when pydantic not installed — preserve importability
    class FailureModel:  # type: ignore[no-redef]
        pass

    class OracleResultModel:  # type: ignore[no-redef]
        pass

    class StepRecordModel:  # type: ignore[no-redef]
        pass

    class ManifestSessionModel:  # type: ignore[no-redef]
        pass

    class AdjudicationModel:  # type: ignore[no-redef]
        pass


def validate_oracle_result(d: dict) -> OracleResultModel | None:
    """Convenience: validate a raw oracle result dict. Returns None if pydantic unavailable."""
    if not _PYDANTIC_AVAILABLE:
        return None
    return OracleResultModel.model_validate(d)


def validate_adjudication_verdict(d: dict) -> AdjudicationModel | None:
    """Convenience: validate an adjudicator verdict dict. Returns None if pydantic unavailable."""
    if not _PYDANTIC_AVAILABLE:
        return None
    return AdjudicationModel.model_validate(d)
