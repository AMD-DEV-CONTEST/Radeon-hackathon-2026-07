from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .rubric import (
    AI_SHORT_DRAMA_RUBRIC_ID,
    AI_SHORT_DRAMA_RUBRIC_VERSION,
    EvaluationStage,
    STAGE_DIMENSIONS,
)


class StrictEvalModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ExpectedScore(StrictEvalModel):
    na: bool = False
    minimum: int | None = Field(default=None, ge=1, le=10)
    maximum: int | None = Field(default=None, ge=1, le=10)

    @model_validator(mode="after")
    def valid_expectation(self):
        if self.na and (self.minimum is not None or self.maximum is not None):
            raise ValueError("N/A expectation cannot define a score range")
        if not self.na and (self.minimum is None or self.maximum is None):
            raise ValueError("scored expectation requires a complete range")
        if (
            self.minimum is not None
            and self.maximum is not None
            and self.minimum > self.maximum
        ):
            raise ValueError("expected minimum cannot exceed maximum")
        return self


class RubricEvalCase(StrictEvalModel):
    case_id: str
    stage: EvaluationStage
    evidence_mode: str = Field(pattern="^(full_video|frames_only)$")
    stimulus: str
    expected: dict[str, ExpectedScore]

    @model_validator(mode="after")
    def applicable_dimensions_only(self):
        unexpected = set(self.expected) - set(STAGE_DIMENSIONS[self.stage])
        if unexpected:
            raise ValueError(
                f"benchmark case contains inapplicable dimensions: "
                f"{sorted(unexpected)}"
            )
        return self


class RubricBenchmark(StrictEvalModel):
    benchmark_id: str
    rubric_id: str
    rubric_version: int
    cases: tuple[RubricEvalCase, ...]

    @model_validator(mode="after")
    def frozen_rubric_only(self):
        if (
            self.rubric_id != AI_SHORT_DRAMA_RUBRIC_ID
            or self.rubric_version != AI_SHORT_DRAMA_RUBRIC_VERSION
        ):
            raise ValueError("benchmark targets an unsupported rubric version")
        if len({case.case_id for case in self.cases}) != len(self.cases):
            raise ValueError("benchmark case ids must be unique")
        return self


def load_rubric_benchmark(path: str | Path) -> RubricBenchmark:
    return RubricBenchmark.model_validate_json(
        Path(path).read_text(encoding="utf-8")
    )


def score_rubric_predictions(
    benchmark: RubricBenchmark,
    predictions: dict[str, dict[str, int | None]],
) -> dict[str, Any]:
    results = []
    for case in benchmark.cases:
        case_predictions = predictions.get(case.case_id, {})
        failures = []
        for dimension_id, expected in case.expected.items():
            predicted = case_predictions.get(dimension_id)
            if expected.na:
                passed = predicted is None and dimension_id in case_predictions
            else:
                passed = (
                    isinstance(predicted, int)
                    and expected.minimum <= predicted <= expected.maximum
                )
            if not passed:
                failures.append(
                    {
                        "dimension_id": dimension_id,
                        "predicted": predicted,
                        "expected": expected.model_dump(mode="json"),
                    }
                )
        results.append(
            {
                "case_id": case.case_id,
                "passed": not failures,
                "failures": failures,
            }
        )
    passed = sum(1 for result in results if result["passed"])
    return {
        "benchmark_id": benchmark.benchmark_id,
        "rubric_id": benchmark.rubric_id,
        "rubric_version": benchmark.rubric_version,
        "cases": len(results),
        "passed": passed,
        "pass_rate": 0.0 if not results else passed / len(results),
        "results": results,
    }
