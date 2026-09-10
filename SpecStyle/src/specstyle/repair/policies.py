"""First-blocking-rule selection for repair policy 1.0."""

from __future__ import annotations

from specstyle.domain.enums import ArtifactStatus as _ArtifactStatus
from specstyle.domain.enums import DecisionReason as _DecisionReason
from specstyle.domain.identifiers import ArtifactId as _ArtifactId
from specstyle.domain.identifiers import DecisionId as _DecisionId
from specstyle.errors import DomainError as _DomainError
from specstyle.generation.requests import GenerationParameters as _Parameters
from specstyle.generation.requests import GenerationRequest as _Request
from specstyle.repair.actions import DECREASE_STYLE_SCALE as _DECREASE
from specstyle.repair.actions import INCREASE_STRUCTURE as _STRUCTURE
from specstyle.repair.actions import INCREASE_STYLE_SCALE as _INCREASE
from specstyle.repair.actions import KNOWN_ACTION_IDS as _KNOWN
from specstyle.repair.actions import REDUCE_DENOISE as _DENOISE
from specstyle.repair.actions import RENDER_OUTPUT_PROFILE as _RENDER
from specstyle.repair.actions import RETRY_SAMPLING as _RETRY
from specstyle.repair.actions import is_action_executable as _executable
from specstyle.repair.actions import plan_repair_action as _plan_action
from specstyle.repair.actions import repair_policy_from_request as _policy
from specstyle.repair.conflict_resolution import _blocking_rules
from specstyle.repair.conflict_resolution import _decision_id
from specstyle.repair.conflict_resolution import _request
from specstyle.repair.conflict_resolution import _safe
from specstyle.repair.conflict_resolution import _validated_context
from specstyle.repair.models import NoAction as _NoAction
from specstyle.repair.models import RepairDecision as _RepairDecision
from specstyle.spec.compiled_models import CompiledVerificationPlan as _Plan
from specstyle.verification.routing import decide_artifact as _decide
from specstyle.verification.rule_models import VerificationReport as _Report

_POLICY_ACTIONS = (
    ("l1_bundle", (_RETRY,)),
    ("STYLE_LOW", (_INCREASE,)),
    ("STYLE_OVERPOWERED", (_DECREASE, _DENOISE)),
    ("CONTENT_DRIFT", (_DENOISE, _STRUCTURE)),
    ("FACE_ID_LOW", (_DENOISE,)),
    ("OUTPUT_PROFILE_INVALID", (_RENDER,)),
    ("SAMPLING_DEFECT", (_RETRY,)),
)
_MAX_INDEX = 2**31 - 1


def _actions(rule_id: str):
    return _safe(
        "invalid repair policy rule",
        lambda: next(
            (actions for name, actions in _POLICY_ACTIONS if name == rule_id), ()
        ),
    )


def _seen(value: object) -> tuple[tuple[_Parameters, int], ...]:
    if type(value) is not tuple:
        raise _DomainError("invalid seen state keys")
    try:
        rebuilt = tuple(
            (
                _Parameters(
                    item[0].ip_adapter_scale,
                    item[0].img2img_strength,
                    item[0].controlnet_scale,
                ),
                item[1],
            )
            for item in value
            if type(item) is tuple
            and len(item) == 2
            and type(item[0]) is _Parameters
            and type(item[1]) is int
            and 0 <= item[1] <= _MAX_INDEX
        )
        if len(rebuilt) != len(value) or len(set(rebuilt)) != len(rebuilt):
            raise _DomainError("invalid seen state keys")
    except _DomainError:
        raise
    except Exception as error:
        raise _DomainError("invalid seen state keys") from error
    return rebuilt


def repair_state_key(request: _Request) -> tuple[_Parameters, int]:
    """Return an auditable state key from a defensively rebuilt request."""
    rebuilt = _request(request)
    return rebuilt.execution_parameters, rebuilt.variation_index


def select_repair(
    request: _Request,
    plan: _Plan,
    report: _Report,
    target_artifact_id: _ArtifactId,
    decision_id: _DecisionId,
    seen_state_keys: tuple[tuple[_Parameters, int], ...] = (),
) -> _RepairDecision | _NoAction:
    """Choose one valid built-in repair action for the first blocking rule."""
    rebuilt_request, rebuilt_plan, rebuilt_report, target = _validated_context(
        request, plan, report, target_artifact_id
    )
    _policy(rebuilt_request)
    decision, seen = _decision_id(decision_id), _seen(seen_state_keys)
    routed = _safe("invalid repair context", lambda: _decide(rebuilt_report, target))
    if not (
        routed.artifact_status is _ArtifactStatus.REJECTED
        and routed.decision_reason is _DecisionReason.REQUIRED_GATE_FAILED
    ):
        raise _DomainError("repair selection requires required gate failure")
    trigger = _blocking_rules(rebuilt_plan, rebuilt_report, target)
    if not trigger:
        raise _DomainError("required gate failure has no blocking rule")
    rule = trigger[0]
    candidates = _actions(rule.definition.rule_id.value)
    for action in candidates:
        eligible = _safe(
            "invalid repair candidate",
            lambda: (
                action in rule.affected_by_actions
                and action in _KNOWN
                and _executable(rebuilt_request, action)
            ),
        )
        if not eligible:
            continue
        selected = _plan_action(
            rebuilt_request, decision, rule.definition.rule_id, action
        )
        unseen = _safe(
            "invalid seen state keys",
            lambda: (
                (
                    selected.patch.after_parameters,
                    selected.patch.after_variation_index,
                )
                not in seen
            ),
        )
        if unseen:
            return selected
    return _NoAction(decision, (rule.definition.rule_id,), candidates)
