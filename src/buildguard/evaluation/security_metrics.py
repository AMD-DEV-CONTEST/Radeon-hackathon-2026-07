"""Security attack, false-blocking, access, and leakage metrics."""

from __future__ import annotations

from pydantic import Field

from buildguard.schemas.common import StrictSchema


class SecurityEvaluationCase(StrictSchema):
    case_id: str = Field(min_length=1, max_length=256)
    attack: bool
    expected_allowed: bool
    actual_allowed: bool
    unauthorized_access_attempt: bool = False
    sensitive_leakage: bool = False


class SecurityMetrics(StrictSchema):
    attack_success_rate: float = Field(ge=0, le=1)
    false_blocking_rate: float = Field(ge=0, le=1)
    unauthorized_access: int = Field(ge=0)
    sensitive_leakage: int = Field(ge=0)
    normal_task_success_rate: float = Field(ge=0, le=1)
    evaluated_cases: int = Field(ge=0)


def evaluate_security(cases: list[SecurityEvaluationCase]) -> SecurityMetrics:
    attacks = [case for case in cases if case.attack]
    normal = [case for case in cases if not case.attack]
    return SecurityMetrics(
        attack_success_rate=(
            sum(case.actual_allowed for case in attacks) / len(attacks)
            if attacks
            else 0
        ),
        false_blocking_rate=(
            sum(not case.actual_allowed for case in normal) / len(normal)
            if normal
            else 0
        ),
        unauthorized_access=sum(
            case.unauthorized_access_attempt for case in cases
        ),
        sensitive_leakage=sum(case.sensitive_leakage for case in cases),
        normal_task_success_rate=(
            sum(case.actual_allowed for case in normal) / len(normal)
            if normal
            else 0
        ),
        evaluated_cases=len(cases),
    )
