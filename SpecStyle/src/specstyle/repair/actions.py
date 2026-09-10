"""Repair policy 1.0 action allowlist and pure child request construction."""

from __future__ import annotations

from specstyle.domain.identifiers import AttemptId, DecisionId, Identifier, RuleId
from specstyle.errors import DomainError
from specstyle.generation.requests import GenerationParameters, GenerationRequest
from specstyle.repair.models import RepairDecision, RepairPatch, RepairPolicy

INCREASE_STYLE_SCALE = Identifier("INCREASE_STYLE_SCALE")
DECREASE_STYLE_SCALE = Identifier("DECREASE_STYLE_SCALE")
REDUCE_DENOISE = Identifier("REDUCE_DENOISE")
INCREASE_STRUCTURE = Identifier("INCREASE_STRUCTURE")
RENDER_OUTPUT_PROFILE = Identifier("RENDER_OUTPUT_PROFILE")
RETRY_SAMPLING = Identifier("RETRY_SAMPLING")

KNOWN_ACTION_IDS = (
    INCREASE_STYLE_SCALE,
    DECREASE_STYLE_SCALE,
    REDUCE_DENOISE,
    INCREASE_STRUCTURE,
    RENDER_OUTPUT_PROFILE,
    RETRY_SAMPLING,
)
EXECUTABLE_ACTION_IDS = (
    INCREASE_STYLE_SCALE,
    DECREASE_STYLE_SCALE,
    REDUCE_DENOISE,
    INCREASE_STRUCTURE,
    RETRY_SAMPLING,
)

_STEP = 0.10
_MAX_VARIATION_INDEX = 2**31 - 1


def _request(value: object) -> GenerationRequest:
    if type(value) is not GenerationRequest:
        raise DomainError("invalid generation request")
    try:
        rebuilt = GenerationRequest(
            value.job_id,
            value.attempt_id,
            value.parent_attempt_id,
            value.compiled_spec,
            value.generation_profile,
            value.output_profile,
            value.source,
            value.style_references,
            value.prompt,
            value.control_input,
            value.variation_index,
            value.environment_hash,
            value.execution_parameters,
        )
        if rebuilt != value:
            raise DomainError("forged generation request")
    except DomainError:
        raise
    except Exception as error:
        raise DomainError("invalid generation request") from error
    return rebuilt


def _identifier(value: object, expected: type[Identifier], name: str) -> Identifier:
    if type(value) is not expected:
        raise DomainError(f"invalid {name}")
    rebuilt = expected(value.value)
    if rebuilt != value:
        raise DomainError(f"forged {name}")
    return rebuilt


def _action(value: object) -> Identifier:
    action = _identifier(value, Identifier, "action id")
    if action not in KNOWN_ACTION_IDS:
        raise DomainError("unknown repair action")
    return action


def _decision(value: object) -> RepairDecision:
    if type(value) is not RepairDecision:
        raise DomainError("invalid repair decision")
    rebuilt = RepairDecision(
        value.decision_id,
        value.policy_version,
        value.trigger_rule_id,
        value.action_id,
        value.patch,
    )
    if rebuilt != value:
        raise DomainError("forged repair decision")
    return rebuilt


def _policy(request: GenerationRequest) -> RepairPolicy:
    repair = request.compiled_spec.source_spec.repair
    return RepairPolicy(
        repair.policy_version, repair.max_rounds, repair.stop_after_no_improvement
    )


def _patch_for(request: GenerationRequest, action: Identifier) -> RepairPatch:
    parameters = request.execution_parameters
    if action == INCREASE_STYLE_SCALE:
        after = GenerationParameters(
            min(1.0, parameters.ip_adapter_scale + _STEP),
            parameters.img2img_strength,
            parameters.controlnet_scale,
        )
        return RepairPatch(
            parameters, after, request.variation_index, request.variation_index
        )
    if action == DECREASE_STYLE_SCALE:
        after = GenerationParameters(
            max(0.0, parameters.ip_adapter_scale - _STEP),
            parameters.img2img_strength,
            parameters.controlnet_scale,
        )
        return RepairPatch(
            parameters, after, request.variation_index, request.variation_index
        )
    if action == REDUCE_DENOISE:
        after = GenerationParameters(
            parameters.ip_adapter_scale,
            max(0.0, parameters.img2img_strength - _STEP),
            parameters.controlnet_scale,
        )
        return RepairPatch(
            parameters, after, request.variation_index, request.variation_index
        )
    if action == INCREASE_STRUCTURE:
        after = GenerationParameters(
            parameters.ip_adapter_scale,
            parameters.img2img_strength,
            min(1.0, parameters.controlnet_scale + _STEP),
        )
        return RepairPatch(
            parameters, after, request.variation_index, request.variation_index
        )
    if action == RETRY_SAMPLING:
        return RepairPatch(
            parameters,
            parameters,
            request.variation_index,
            request.variation_index + 1,
        )
    raise DomainError("repair action is unavailable")


def repair_policy_from_request(request: GenerationRequest) -> RepairPolicy:
    """Get and validate the built-in policy from a defensively rebuilt request."""
    return _policy(_request(request))


def is_action_executable(request: GenerationRequest, action_id: Identifier) -> bool:
    """Check whether an allowlisted action still yields a valid patch."""
    rebuilt_request = _request(request)
    action = _action(action_id)
    if action not in EXECUTABLE_ACTION_IDS:
        return False
    try:
        _patch_for(rebuilt_request, action)
    except DomainError:
        return False
    return True


def plan_repair_action(
    request: GenerationRequest,
    decision_id: DecisionId,
    trigger_rule_id: RuleId,
    action_id: Identifier,
) -> RepairDecision:
    """Compute exactly one typed repair patch for the current request."""
    rebuilt_request = _request(request)
    policy = _policy(rebuilt_request)
    decision = _identifier(decision_id, DecisionId, "decision id")
    trigger = _identifier(trigger_rule_id, RuleId, "trigger rule id")
    action = _action(action_id)
    if not is_action_executable(rebuilt_request, action):
        raise DomainError("repair action is not executable")
    return RepairDecision(
        decision,
        policy.policy_version,
        trigger,
        action,
        _patch_for(rebuilt_request, action),
    )


def build_repair_request(
    parent: GenerationRequest,
    decision: RepairDecision,
    next_attempt_id: AttemptId,
) -> GenerationRequest:
    """Validate the decision and build the next request with parent material."""
    rebuilt_parent = _request(parent)
    rebuilt_decision = _decision(decision)
    next_attempt = _identifier(next_attempt_id, AttemptId, "next attempt id")
    if next_attempt == rebuilt_parent.attempt_id:
        raise DomainError("next attempt id must differ from parent")
    policy = _policy(rebuilt_parent)
    if rebuilt_decision.policy_version != policy.policy_version:
        raise DomainError("repair decision policy does not match parent")
    expected = plan_repair_action(
        rebuilt_parent,
        rebuilt_decision.decision_id,
        rebuilt_decision.trigger_rule_id,
        rebuilt_decision.action_id,
    )
    if rebuilt_decision.patch != expected.patch:
        raise DomainError("repair decision patch does not match action")
    return GenerationRequest(
        rebuilt_parent.job_id,
        next_attempt,
        rebuilt_parent.attempt_id,
        rebuilt_parent.compiled_spec,
        rebuilt_parent.generation_profile,
        rebuilt_parent.output_profile,
        rebuilt_parent.source,
        rebuilt_parent.style_references,
        rebuilt_parent.prompt,
        rebuilt_parent.control_input,
        expected.patch.after_variation_index,
        rebuilt_parent.environment_hash,
        expected.patch.after_parameters,
    )
