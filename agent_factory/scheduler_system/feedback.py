from __future__ import annotations

import json
from typing import Any

from langchain_core.messages import HumanMessage

from agent_factory.model_pool.runtime_override import (
    main_model_profile_id_from_user_config,
    resolve_runtime_main_chat_model,
    resolve_runtime_reasoning_model,
)
from agent_factory.prompts import PromptId, get_prompt, output_json_schema
from agent_factory.scheduler_system.schema import (
    SchedulerExecutionReport,
    SchedulerFeedbackSummaryDecision,
    SchedulerJob,
    SchedulerRun,
)


SCHEDULER_FEEDBACK_MAX_ATTEMPTS = 5


class SchedulerFeedbackError(RuntimeError):
    pass


def summarize_scheduler_feedback(
    *,
    job: SchedulerJob,
    run: SchedulerRun,
    report: SchedulerExecutionReport,
    completed_count: int,
) -> SchedulerFeedbackSummaryDecision:
    user_config = dict(job.runtime_config.user_config)
    profile_id = main_model_profile_id_from_user_config(user_config)
    if not profile_id:
        raise SchedulerFeedbackError("scheduler main model profile is not selected")
    resolved = resolve_runtime_main_chat_model(profile_id)
    model, _settings = resolve_runtime_reasoning_model(
        resolved.model,
        resolved.settings,
        {"user_config": user_config},
    )
    structured_model = model.with_structured_output(SchedulerFeedbackSummaryDecision, method="json_mode").with_config(
        tags=["nostream", "scheduler-feedback"]
    )
    prompt_value = get_prompt(PromptId.SCHEDULER_FEEDBACK_SUMMARY).invoke(
        {
            "output_json_schema": output_json_schema(SchedulerFeedbackSummaryDecision),
            "feedback_context": json.dumps(
                _feedback_context(
                    job=job,
                    run=run,
                    report=report,
                    completed_count=completed_count,
                ),
                ensure_ascii=False,
                indent=2,
            ),
        }
    )
    messages = prompt_value.to_messages()
    last_error: Exception | None = None
    schema_text = output_json_schema(SchedulerFeedbackSummaryDecision)
    for attempt in range(1, SCHEDULER_FEEDBACK_MAX_ATTEMPTS + 1):
        try:
            result = structured_model.invoke(messages)
            decision = (
                result
                if isinstance(result, SchedulerFeedbackSummaryDecision)
                else SchedulerFeedbackSummaryDecision.model_validate(result)
            )
            if not decision.summary.strip():
                raise SchedulerFeedbackError("scheduler feedback summary is empty")
            return decision.model_copy(update={"summary": decision.summary.strip()})
        except Exception as exc:
            last_error = exc
            if attempt >= SCHEDULER_FEEDBACK_MAX_ATTEMPTS:
                break
            messages.append(
                HumanMessage(
                    content=(
                        "The previous scheduler feedback output failed schema validation.\n"
                        "Regenerate the full response as JSON only. Do not explain the error.\n"
                        "You must obey every JSON schema constraint, including required fields, field types, "
                        "and extra=forbid.\n"
                        f"Validation observation from attempt {attempt}/{SCHEDULER_FEEDBACK_MAX_ATTEMPTS}:\n"
                        f"{type(exc).__name__}: {exc}\n\n"
                        f"Output JSON schema:\n{schema_text}"
                    )
                )
            )
    raise SchedulerFeedbackError(f"{type(last_error).__name__}: {last_error}") from last_error


def _feedback_context(
    *,
    job: SchedulerJob,
    run: SchedulerRun,
    report: SchedulerExecutionReport,
    completed_count: int,
) -> dict[str, Any]:
    return {
        "job": {
            "job_id": job.job_id,
            "task_content": job.task_content or _derived_task_content(job),
            "target_type": job.target.target_type,
            "schedule_type": job.schedule_type,
            "schedule_expr": job.schedule_expr,
            "timezone": job.timezone,
        },
        "run": {
            "run_id": run.run_id,
            "status": report.status,
            "scheduled_at": run.scheduled_at,
            "started_at": report.started_at,
            "completed_at": report.completed_at,
            "duration_ms": report.duration_ms,
            "completed_count": completed_count,
            "completed_count_meaning": "this job's cumulative successful completion count",
        },
        "report": {
            "output_summary": report.output_summary,
            "error_summary": report.error_summary,
            "stdout_preview": report.stdout_preview,
            "stderr_preview": report.stderr_preview,
            "exit_code": report.exit_code,
        },
    }


def _derived_task_content(job: SchedulerJob) -> str:
    if job.target.target_type == "graph_run":
        return str(job.target.payload.get("message") or job.job_id)
    if job.target.target_type == "tool_call":
        return f"调用工具 {job.target.payload.get('tool_id') or job.job_id}"
    return f"执行脚本任务 {job.job_id}"
