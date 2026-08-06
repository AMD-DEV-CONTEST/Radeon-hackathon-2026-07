"""Subscription entitlements and usage quotas."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml
from fastapi import HTTPException, status
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.training import TrainingJob
from app.models.usage_counter import UsageCounter
from app.models.user import User

_PLANS_PATH = Path(__file__).resolve().parents[1] / "data" / "plans.yaml"
_TIER_ORDER = {"free": 0, "pro": 1, "creator": 2}

METRIC_TRAINING_LOCAL = "training_local"
METRIC_TRAINING_QUALIA = "training_qualia"
METRIC_SKILL_RUN = "skill_run"
METRIC_STORAGE_BYTES = "storage_bytes"


class QuotaExceeded(HTTPException):
    def __init__(self, code: str, message: str, *, required_tier: str | None = None):
        detail: dict[str, Any] = {"code": code, "message": message}
        if required_tier:
            detail["required_tier"] = required_tier
        super().__init__(status_code=status.HTTP_402_PAYMENT_REQUIRED, detail=detail)


class TierRequired(HTTPException):
    def __init__(self, code: str, message: str, required_tier: str):
        super().__init__(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": code, "message": message, "required_tier": required_tier},
        )


@dataclass(frozen=True)
class PlanLimits:
    tier: str
    display_name: str
    storage_bytes: int
    training_local_monthly: int
    training_qualia_monthly: int
    training_concurrent_max: int
    skill_runs_monthly: int
    inference_priority: int
    qualia_max_hours: float
    workflow_nodes: frozenset[str]
    verbs: frozenset[str]
    can_publish_paid_skills: bool
    commercial_license: bool
    batch_jobs: bool
    show_legacy_workflow_nodes: bool


_plans_cache: dict[str, Any] | None = None


def _load_plans_raw() -> dict[str, Any]:
    global _plans_cache
    if _plans_cache is None:
        with open(_PLANS_PATH, encoding="utf-8") as f:
            _plans_cache = yaml.safe_load(f)
    return _plans_cache


def _merge_plan(tier: str, raw: dict[str, Any]) -> dict[str, Any]:
    inherits = raw.get("inherits")
    if not inherits:
        return dict(raw)
    parent = _load_plans_raw()["plans"][inherits]
    merged = _merge_plan(inherits, parent)
    merged.update({k: v for k, v in raw.items() if k != "inherits"})
    return merged


def get_plan_limits(tier: str) -> PlanLimits:
    raw_all = _load_plans_raw()
    tier = tier if tier in raw_all["plans"] else "free"
    merged = _merge_plan(tier, raw_all["plans"][tier])
    return PlanLimits(
        tier=tier,
        display_name=str(merged.get("display_name", tier)),
        storage_bytes=int(merged.get("storage_bytes", 0)),
        training_local_monthly=int(merged.get("training_local_monthly", 0)),
        training_qualia_monthly=int(merged.get("training_qualia_monthly", 0)),
        training_concurrent_max=int(merged.get("training_concurrent_max", 1)),
        skill_runs_monthly=int(merged.get("skill_runs_monthly", 0)),
        inference_priority=int(merged.get("inference_priority", 0)),
        qualia_max_hours=float(merged.get("qualia_max_hours", 0)),
        workflow_nodes=frozenset(merged.get("workflow_nodes") or []),
        verbs=frozenset(merged.get("verbs") or []),
        can_publish_paid_skills=bool(merged.get("can_publish_paid_skills", False)),
        commercial_license=bool(merged.get("commercial_license", False)),
        batch_jobs=bool(merged.get("batch_jobs", False)),
        show_legacy_workflow_nodes=bool(merged.get("show_legacy_workflow_nodes", False)),
    )


def effective_tier(user: User) -> str:
    tier = (user.subscription_tier or "free").lower()
    if tier not in _TIER_ORDER:
        tier = "free"
    expires = user.tier_expires_at
    if expires is not None:
        exp = expires if expires.tzinfo else expires.replace(tzinfo=timezone.utc)
        if exp < datetime.now(timezone.utc) and tier != "free":
            return "free"
    return tier


def current_period() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m")


def get_counter(db: Session, user_id, metric: str, period: str | None = None) -> int:
    period = period or current_period()
    row = (
        db.query(UsageCounter)
        .filter(
            UsageCounter.user_id == user_id,
            UsageCounter.metric == metric,
            UsageCounter.period == period,
        )
        .first()
    )
    return int(row.value) if row else 0


def increment_counter(db: Session, user_id, metric: str, amount: int = 1) -> int:
    period = current_period()
    row = (
        db.query(UsageCounter)
        .filter(
            UsageCounter.user_id == user_id,
            UsageCounter.metric == metric,
            UsageCounter.period == period,
        )
        .first()
    )
    if row:
        row.value = int(row.value) + amount
    else:
        row = UsageCounter(user_id=user_id, metric=metric, period=period, value=amount)
        db.add(row)
    db.commit()
    db.refresh(row)
    return int(row.value)


def _active_training_count(db: Session, user_id) -> int:
    return (
        db.query(func.count(TrainingJob.id))
        .filter(
            TrainingJob.created_by == user_id,
            TrainingJob.status.in_(("queued", "running")),
        )
        .scalar()
        or 0
    )


def entitlements_for_user(user: User) -> dict[str, Any]:
    tier = effective_tier(user)
    limits = get_plan_limits(tier)
    return {
        "tier": tier,
        "display_name": limits.display_name,
        "tier_expires_at": user.tier_expires_at.isoformat() if user.tier_expires_at else None,
        "limits": {
            "storage_bytes": limits.storage_bytes,
            "training_local_monthly": limits.training_local_monthly,
            "training_qualia_monthly": limits.training_qualia_monthly,
            "training_concurrent_max": limits.training_concurrent_max,
            "skill_runs_monthly": limits.skill_runs_monthly,
            "inference_priority": limits.inference_priority,
            "qualia_max_hours": limits.qualia_max_hours,
            "workflow_nodes": sorted(limits.workflow_nodes),
            "verbs": sorted(limits.verbs),
            "can_publish_paid_skills": limits.can_publish_paid_skills,
            "commercial_license": limits.commercial_license,
            "batch_jobs": limits.batch_jobs,
            "show_legacy_workflow_nodes": limits.show_legacy_workflow_nodes,
        },
    }


def tier_at_least(user_tier: str, required: str) -> bool:
    return _TIER_ORDER.get(user_tier, 0) >= _TIER_ORDER.get(required, 0)


def require_tier(user: User, required: str, *, code: str = "tier_required") -> PlanLimits:
    tier = effective_tier(user)
    if not tier_at_least(tier, required):
        raise TierRequired(
            code,
            f"This feature requires {required} plan or higher",
            required_tier=required,
        )
    return get_plan_limits(tier)


def check_training_create(
    db: Session,
    user: User,
    *,
    train_backend: str,
    hours: float | None = None,
) -> PlanLimits:
    limits = get_plan_limits(effective_tier(user))
    active = _active_training_count(db, user.id)
    if active >= limits.training_concurrent_max:
        raise QuotaExceeded(
            "quota_training_concurrent",
            (
                f"当前有 {active} 个训练任务在进行中，"
                f"您的套餐最多同时 {limits.training_concurrent_max} 个。"
                "请等待完成，或在训练列表取消旧任务后重试。"
            ),
        )

    if train_backend == "qualia":
        if limits.training_qualia_monthly == 0:
            raise QuotaExceeded(
                "tier_required_pro",
                "Cloud training (Qualia) requires Pro or Creator plan",
                required_tier="pro",
            )
        used = get_counter(db, user.id, METRIC_TRAINING_QUALIA)
        if limits.training_qualia_monthly >= 0 and used >= limits.training_qualia_monthly:
            raise QuotaExceeded(
                "quota_training_qualia_exceeded",
                f"Monthly Qualia training limit reached ({limits.training_qualia_monthly})",
            )
        if hours is not None and hours > limits.qualia_max_hours:
            raise QuotaExceeded(
                "quota_qualia_hours",
                f"Qualia hours exceed plan limit ({limits.qualia_max_hours}h)",
            )
    else:
        if limits.training_local_monthly >= 0:
            used = get_counter(db, user.id, METRIC_TRAINING_LOCAL)
            if used >= limits.training_local_monthly:
                raise QuotaExceeded(
                    "quota_training_local_exceeded",
                    f"Monthly local training limit reached ({limits.training_local_monthly})",
                )
    return limits


def record_training_created(db: Session, user: User, train_backend: str) -> None:
    metric = METRIC_TRAINING_QUALIA if train_backend == "qualia" else METRIC_TRAINING_LOCAL
    increment_counter(db, user.id, metric)


def check_skill_run(db: Session, user: User, verb: str) -> PlanLimits:
    limits = get_plan_limits(effective_tier(user))
    if verb and verb not in limits.verbs:
        required = "pro" if verb in ("pick", "place", "grasp", "release", "push", "pull") else "pro"
        raise TierRequired(
            "verb_not_in_plan",
            f"Verb '{verb}' is not available on your plan",
            required_tier=required,
        )
    if limits.skill_runs_monthly >= 0:
        used = get_counter(db, user.id, METRIC_SKILL_RUN)
        if used >= limits.skill_runs_monthly:
            raise QuotaExceeded(
                "quota_skill_run_exceeded",
                f"Monthly skill run limit reached ({limits.skill_runs_monthly})",
            )
    return limits


def record_skill_run(db: Session, user: User) -> None:
    increment_counter(db, user.id, METRIC_SKILL_RUN)


def check_workflow_node(user: User, node_type: str) -> None:
    limits = get_plan_limits(effective_tier(user))
    if node_type not in limits.workflow_nodes:
        required = "pro" if node_type in ("camera_denoise", "trajectory_optimize") else "pro"
        raise TierRequired(
            "workflow_node_locked",
            f"Workflow node '{node_type}' requires upgrade",
            required_tier=required,
        )


def check_storage_bytes(db: Session, user: User, additional_bytes: int = 0) -> None:
    limits = get_plan_limits(effective_tier(user))
    used = get_counter(db, user.id, METRIC_STORAGE_BYTES)
    if limits.storage_bytes >= 0 and used + additional_bytes > limits.storage_bytes:
        raise QuotaExceeded(
            "quota_storage_exceeded",
            f"Storage quota exceeded ({limits.storage_bytes} bytes)",
            required_tier="pro",
        )


def set_storage_usage(db: Session, user_id, total_bytes: int) -> None:
    period = current_period()
    row = (
        db.query(UsageCounter)
        .filter(
            UsageCounter.user_id == user_id,
            UsageCounter.metric == METRIC_STORAGE_BYTES,
            UsageCounter.period == period,
        )
        .first()
    )
    if row:
        row.value = total_bytes
    else:
        row = UsageCounter(
            user_id=user_id,
            metric=METRIC_STORAGE_BYTES,
            period=period,
            value=total_bytes,
        )
        db.add(row)
    db.commit()
