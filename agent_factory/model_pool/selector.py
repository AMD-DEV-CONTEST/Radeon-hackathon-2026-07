from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from agent_factory.model_pool.schema import (
    LocalModelArtifact,
    ModelPoolProfile,
    ModelSelectionRecommendation,
    ModelSelectionRequirement,
    ModelSelectionRequest,
    ModelSelectionResult,
    ModelToolSelectionRecommendation,
)
from agent_factory.model_pool.store import ModelPoolStore


@dataclass(frozen=True, slots=True)
class _Candidate:
    profile: ModelPoolProfile
    artifact: LocalModelArtifact
    score: float
    reason: str
    warnings: list[str]


class ModelPoolSelector:
    def __init__(self, store: ModelPoolStore | None = None) -> None:
        self.store = store or ModelPoolStore()

    def select(self, request: ModelSelectionRequest) -> ModelSelectionResult:
        profiles = self.store.list_profiles()
        enabled_profiles = [profile for profile in profiles if profile.enabled]
        recommendations: list[ModelSelectionRecommendation] = []
        tool_recommendations: list[ModelToolSelectionRecommendation] = []
        unmatched: list[dict[str, Any]] = []
        for requirement in request.requirements:
            candidates = self._rank_candidates(requirement, enabled_profiles)
            if not candidates:
                unmatched.append(_unmatched_requirement(requirement))
                continue
            selected = candidates[0]
            recommendations.append(
                ModelSelectionRecommendation(
                    role=requirement.role,
                    profile_id=selected.profile.profile_id,
                    display_name=selected.profile.display_name,
                    description=selected.profile.description,
                    engine=selected.profile.engine,
                    model_name=selected.profile.model_name,
                    score=round(selected.score, 6),
                    reason=selected.reason,
                    required_capabilities=_requirement_payload(requirement),
                    warnings=selected.warnings,
                    candidates=[_candidate_payload(item) for item in candidates[: requirement.max_candidates]],
                )
            )
        for requirement in request.tool_requirements:
            model_requirement = requirement.as_model_requirement()
            candidates = self._rank_candidates(model_requirement, enabled_profiles)
            if not candidates:
                unmatched.append(
                    {
                        "tool_id": requirement.tool_id,
                        "capability": requirement.capability,
                        "purpose": requirement.purpose,
                        "required_capabilities": _requirement_payload(model_requirement),
                        "reason": "No enabled local model profile matches the required capability.",
                    }
                )
                continue
            selected = candidates[0]
            tool_recommendations.append(
                ModelToolSelectionRecommendation(
                    tool_id=requirement.tool_id,
                    capability=requirement.capability,
                    profile_id=selected.profile.profile_id,
                    display_name=selected.profile.display_name,
                    description=selected.profile.description,
                    engine=selected.profile.engine,
                    model_name=selected.profile.model_name,
                    score=round(selected.score, 6),
                    reason=selected.reason,
                    required_capabilities=_requirement_payload(model_requirement),
                    warnings=selected.warnings,
                    candidates=[_candidate_payload(item) for item in candidates[: requirement.max_candidates]],
                )
            )
        return ModelSelectionResult(
            status="blocked" if unmatched else "completed",
            recommendations=recommendations,
            tool_recommendations=tool_recommendations,
            unmatched=unmatched,
            profile_count=len(profiles),
            enabled_profile_count=len(enabled_profiles),
        )

    def profile_match_issues(
        self,
        profile_id: str,
        requirement: ModelSelectionRequirement,
    ) -> list[str]:
        profile = self.store.require_profile(profile_id)
        if not profile.enabled:
            return ["profile_disabled"]
        artifact = self.store.get_artifact(profile.artifact_id)
        if artifact is None:
            return ["artifact_missing"]
        if not artifact.enabled:
            return ["artifact_disabled"]
        if requirement.kind and profile.kind != requirement.kind:
            return [f"kind:{requirement.kind}"]
        return _missing_capabilities(requirement, profile)

    def _rank_candidates(
        self,
        requirement: ModelSelectionRequirement,
        profiles: list[ModelPoolProfile],
    ) -> list[_Candidate]:
        candidates: list[_Candidate] = []
        excluded = set(requirement.excluded_profile_ids)
        for profile in profiles:
            if profile.profile_id in excluded or (requirement.kind and profile.kind != requirement.kind):
                continue
            artifact = self.store.get_artifact(profile.artifact_id)
            if artifact is None or not artifact.enabled:
                continue
            if _missing_capabilities(requirement, profile):
                continue
            candidates.append(
                _Candidate(
                    profile=profile,
                    artifact=artifact,
                    score=_score_profile(requirement, profile),
                    reason=_selection_reason(requirement, profile),
                    warnings=_candidate_warnings(requirement, profile),
                )
            )
        return sorted(candidates, key=lambda item: (-item.score, item.profile.profile_id))


def _missing_capabilities(requirement: ModelSelectionRequirement, profile: ModelPoolProfile) -> list[str]:
    capabilities = profile.capabilities
    missing: list[str] = []
    inputs = set(capabilities.input_modalities)
    outputs = set(capabilities.output_modalities)
    missing.extend(f"input:{item}" for item in requirement.input_modalities if item not in inputs)
    missing.extend(f"output:{item}" for item in requirement.output_modalities if item not in outputs)
    if requirement.tool_calling is True and not capabilities.tool_calling:
        missing.append("tool_calling")
    if requirement.reasoning_required is True and not capabilities.reasoning_supported:
        missing.append("reasoning")
    if requirement.structured_output_methods:
        supported = set(capabilities.structured_output_methods)
        if not any(method in supported for method in requirement.structured_output_methods):
            missing.append("structured_output")
    if requirement.min_context_window_tokens:
        limit = profile.limits.max_input_tokens
        if limit is None or limit < requirement.min_context_window_tokens:
            missing.append("context_window")
    return missing


def _candidate_payload(candidate: _Candidate) -> dict[str, Any]:
    return {
        "profile_id": candidate.profile.profile_id,
        "display_name": candidate.profile.display_name,
        "description": candidate.profile.description,
        "engine": candidate.profile.engine,
        "model_name": candidate.profile.model_name,
        "score": round(candidate.score, 6),
        "reason": candidate.reason,
        "warnings": candidate.warnings,
    }


def _score_profile(requirement: ModelSelectionRequirement, profile: ModelPoolProfile) -> float:
    score = 0.5
    if requirement.tool_calling is True and profile.capabilities.tool_calling:
        score += 0.08
    if requirement.reasoning_required is True and profile.capabilities.reasoning_supported:
        score += 0.08
    if requirement.min_context_window_tokens and profile.limits.max_input_tokens:
        ratio = min(profile.limits.max_input_tokens / requirement.min_context_window_tokens, 4.0)
        score += 0.04 * ratio
    if requirement.optimize_for == "context" and profile.limits.max_input_tokens:
        score += min(profile.limits.max_input_tokens / 1_000_000, 1.0) * 0.2
    if requirement.optimize_for == "quality":
        score += 0.04 * len(profile.capabilities.structured_output_methods)
        if profile.capabilities.strict_tool_schema:
            score += 0.05
    if requirement.optimize_for == "latency" and profile.limits.timeout_seconds:
        score += max(0.0, 0.12 - min(profile.limits.timeout_seconds, 120.0) / 1000.0)
    return score


def _selection_reason(requirement: ModelSelectionRequirement, profile: ModelPoolProfile) -> str:
    parts = [f"Selected local profile {profile.display_name} for {requirement.role}."]
    if requirement.purpose:
        parts.append(requirement.purpose)
    if requirement.input_modalities:
        parts.append("Required inputs: " + ", ".join(requirement.input_modalities) + ".")
    if requirement.tool_calling:
        parts.append("Tool calling is required.")
    if requirement.reasoning_required:
        parts.append("Reasoning support is required.")
    if profile.description:
        parts.append("Profile guidance: " + profile.description)
    return " ".join(parts)


def _candidate_warnings(requirement: ModelSelectionRequirement, profile: ModelPoolProfile) -> list[str]:
    warnings: list[str] = []
    if requirement.structured_output_methods and not profile.capabilities.strict_tool_schema:
        warnings.append("Profile does not advertise strict tool schema support.")
    return warnings


def _unmatched_requirement(requirement: ModelSelectionRequirement) -> dict[str, Any]:
    return {
        "role": requirement.role,
        "purpose": requirement.purpose,
        "required_capabilities": _requirement_payload(requirement),
        "reason": "No enabled local model profile matches the required capabilities.",
    }


def _requirement_payload(requirement: ModelSelectionRequirement) -> dict[str, Any]:
    return requirement.model_dump(mode="json", exclude_none=True)
