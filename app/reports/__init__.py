"""Reports package — weekly report, risk list, next week plan (Phase C)."""

from app.reports.generator import (
    generate_weekly_report,
    generate_risk_csv,
    generate_next_week_plan,
    evaluate_with_rules,
    evaluate_with_llm,
    batch_evaluate_with_llm,
    build_evaluation_prompt,
    build_explanation_prompt,
    parse_llm_response,
    TaskEvaluation,
    TaskStatus,
)

__all__ = [
    "generate_weekly_report",
    "generate_risk_csv",
    "generate_next_week_plan",
    "evaluate_with_rules",
    "evaluate_with_llm",
    "batch_evaluate_with_llm",
    "build_evaluation_prompt",
    "build_explanation_prompt",
    "parse_llm_response",
    "TaskEvaluation",
    "TaskStatus",
]
