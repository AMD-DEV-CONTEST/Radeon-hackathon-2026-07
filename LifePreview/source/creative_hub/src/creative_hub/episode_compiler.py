"""Six-shot Shidu trial workflow compiler.

Freezes the exact script, voice, alignment, generation, machine-QC, and
delivery authorities used by the retained Shidu production runtime.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
import json
import math
import re
from typing import Any, Mapping
from uuid import UUID

from creative_hub.db.canonical import canonical_json_digest
from creative_hub.qc_policy import (
    FactoryQCPolicyPayload,
    compiled_gate_policy,
)
from creative_hub.workflow_catalog import (
    WorkflowDefinition,
    WorkflowNodeDefinition,
    shidu_trial_workflow_definition,
)

EPISODE_PLAN_SCHEMA_VERSION = "factory.episode-plan.v1"
SHIDU_COMPILER_REVISION = "shidu-episode-compiler.v2"
SHIDU_TRIAL_SCRIPT_SCHEMA_VERSION = "factory.shidu-trial-script.v1"


@dataclass(frozen=True)
class CompiledShiduTrialWorkflow:
    """Six-shot Shidu workflow with all immutable production pins embedded."""

    definition: WorkflowDefinition
    definition_digest: str
    policy_snapshot: dict[str, Any]
    run_identity: str


_SHA256 = re.compile(r"^[0-9a-f]{64}$")


def _require_digest(value: str, field: str) -> str:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise ValueError(f"{field} must be a sha256 digest")
    return value


def _frozen_mapping_tuple(
    value: tuple[Mapping[str, Any], ...],
    *,
    field: str,
) -> tuple[dict[str, Any], ...]:
    if not isinstance(value, tuple) or len(value) != 6:
        raise ValueError(f"{field} must contain exactly six frozen objects")
    frozen: list[dict[str, Any]] = []
    for item in value:
        if not isinstance(item, Mapping):
            raise ValueError(f"{field} must contain exactly six frozen objects")
        try:
            rendered = json.dumps(
                dict(item),
                ensure_ascii=False,
                allow_nan=False,
                sort_keys=True,
                separators=(",", ":"),
            )
            normalized = json.loads(rendered)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{field} contains non-canonical content") from exc
        if not isinstance(normalized, dict):
            raise ValueError(f"{field} must contain objects")
        frozen.append(normalized)
    return tuple(frozen)


def _frozen_mapping(value: Mapping[str, Any], *, field: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{field} must be a frozen object")
    try:
        rendered = json.dumps(
            dict(value),
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        normalized = json.loads(rendered)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} contains non-canonical content") from exc
    if not isinstance(normalized, dict):
        raise ValueError(f"{field} must be a frozen object")
    return normalized


def _validate_shidu_authorities(
    *,
    project_id: UUID,
    voice_preset_revision_id: UUID,
    voice_preset_digest: str,
    voice_preset_payload: Mapping[str, Any],
    audio_alignment_policy_revision_id: UUID,
    audio_alignment_policy_digest: str,
    audio_alignment_policy_payload: Mapping[str, Any],
    final_audio_tracks_payload: tuple[Mapping[str, Any], ...],
) -> tuple[dict[str, Any], dict[str, Any], tuple[dict[str, Any], ...]]:
    voice = _frozen_mapping(voice_preset_payload, field="voice_preset_payload")
    if (
        voice.get("project_id") != str(project_id)
        or voice.get("voice_preset_revision_id")
        != str(voice_preset_revision_id)
        or voice.get("digest") != voice_preset_digest
        or voice.get("provider") != "qwen3-tts-custom-voice-mcp"
        or voice.get("model_id")
        != "Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice"
        or voice.get("discovery_tool_name") != "qwen_tts.custom_voice"
        or voice.get("language") != "Chinese"
        or voice.get("enabled") is not True
    ):
        raise ValueError("voice preset snapshot does not match frozen authority")
    alignment = _frozen_mapping(
        audio_alignment_policy_payload,
        field="audio_alignment_policy_payload",
    )
    if (
        alignment.get("project_id") != str(project_id)
        or alignment.get("alignment_policy_revision_id")
        != str(audio_alignment_policy_revision_id)
        or alignment.get("digest") != audio_alignment_policy_digest
    ):
        raise ValueError(
            "audio alignment snapshot does not match frozen authority"
        )
    if not isinstance(final_audio_tracks_payload, tuple) or len(
        final_audio_tracks_payload
    ) != 3:
        raise ValueError("final audio tracks require three frozen authorities")
    tracks = tuple(
        _frozen_mapping(item, field="final_audio_tracks_payload")
        for item in final_audio_tracks_payload
    )
    expected_roles = ("ambience", "sfx", "music")
    if tuple(item.get("role") for item in tracks) != expected_roles:
        raise ValueError("final audio track roles must be canonical and complete")
    for item in tracks:
        artifact = item.get("artifact")
        silence = item.get("silence_policy")
        if (artifact is None) == (silence is None):
            raise ValueError(
                "final audio tracks require accepted artifact or silence authority"
            )
        if silence is not None:
            if (
                not isinstance(silence, dict)
                or silence.get("project_id") != str(project_id)
                or item["role"] not in tuple(silence.get("allowed_roles") or ())
            ):
                raise ValueError("final silence authority is outside the project")
    return voice, alignment, tracks


def _validate_shidu_payloads(
    *,
    shot_keys: tuple[str, ...],
    cue_keys: tuple[str, ...],
    shot_payloads: tuple[Mapping[str, Any], ...],
    cue_payloads: tuple[Mapping[str, Any], ...],
    trial_script_digest: str,
) -> tuple[tuple[dict[str, Any], ...], tuple[dict[str, Any], ...]]:
    shots = _frozen_mapping_tuple(shot_payloads, field="shot_payloads")
    cues = _frozen_mapping_tuple(cue_payloads, field="cue_payloads")
    actual_shot_keys = tuple(str(item.get("unit_key") or "") for item in shots)
    actual_cue_keys = tuple(str(item.get("cue_key") or "") for item in cues)
    if actual_shot_keys != shot_keys or actual_cue_keys != cue_keys:
        raise ValueError("Shidu shot/cue keys must match frozen payload order")
    for index, shot in enumerate(shots, start=1):
        if (
            shot.get("ordinal") != index
            or not str(shot.get("shot_id") or "")
            or not str(shot.get("prompt") or "").strip()
            or shot.get("generation_mode") != "i2v"
        ):
            raise ValueError("Shidu frozen shot payload is invalid")
    for cue in cues:
        text = str(cue.get("text") or "").strip()
        try:
            UUID(str(cue.get("cue_id")))
            start = float(cue.get("start_time"))
            end = float(cue.get("end_time"))
        except (TypeError, ValueError) as exc:
            raise ValueError("Shidu frozen cue payload is invalid") from exc
        if (
            not text
            or not math.isfinite(start)
            or not math.isfinite(end)
            or start < 0
            or end <= start
        ):
            raise ValueError("Shidu frozen cue payload is invalid")
    expected_digest = canonical_json_digest(
        {
            "schema_version": SHIDU_TRIAL_SCRIPT_SCHEMA_VERSION,
            "shots": list(shots),
            "narration_cues": list(cues),
        }
    )
    if trial_script_digest != expected_digest:
        raise ValueError("trial_script_digest does not match frozen payload truth")
    return shots, cues


def compile_shidu_trial_workflow(
    *,
    project_id: UUID,
    book_id: UUID,
    trial_script_revision_id: UUID,
    trial_script_digest: str,
    voice_preset_revision_id: UUID,
    voice_preset_digest: str,
    voice_preset_payload: Mapping[str, Any],
    audio_alignment_policy_revision_id: UUID,
    audio_alignment_policy_digest: str,
    audio_alignment_policy_payload: Mapping[str, Any],
    final_audio_tracks_payload: tuple[Mapping[str, Any], ...],
    shot_keys: tuple[str, ...],
    cue_keys: tuple[str, ...],
    shot_payloads: tuple[Mapping[str, Any], ...],
    cue_payloads: tuple[Mapping[str, Any], ...],
    policy_overrides: Mapping[str, Any] | None = None,
) -> CompiledShiduTrialWorkflow:
    """Compile exact script/voice/alignment lineage into the shipped DAG.

    No public API or media provider is invoked here.  The compiler only freezes
    operation requests; accepted artifacts remain the runtime authority.
    """

    _require_digest(trial_script_digest, "trial_script_digest")
    _require_digest(voice_preset_digest, "voice_preset_digest")
    _require_digest(
        audio_alignment_policy_digest,
        "audio_alignment_policy_digest",
    )
    if (
        len(shot_keys) != 6
        or len(cue_keys) != 6
        or len(set(shot_keys)) != 6
        or len(set(cue_keys)) != 6
        or any(not item or len(item) > 160 for item in (*shot_keys, *cue_keys))
    ):
        raise ValueError("Shidu trial requires six unique shot and cue keys")
    shots, cues = _validate_shidu_payloads(
        shot_keys=shot_keys,
        cue_keys=cue_keys,
        shot_payloads=shot_payloads,
        cue_payloads=cue_payloads,
        trial_script_digest=trial_script_digest,
    )
    voice_snapshot, alignment_snapshot, final_audio_tracks = (
        _validate_shidu_authorities(
            project_id=project_id,
            voice_preset_revision_id=voice_preset_revision_id,
            voice_preset_digest=voice_preset_digest,
            voice_preset_payload=voice_preset_payload,
            audio_alignment_policy_revision_id=(
                audio_alignment_policy_revision_id
            ),
            audio_alignment_policy_digest=audio_alignment_policy_digest,
            audio_alignment_policy_payload=audio_alignment_policy_payload,
            final_audio_tracks_payload=final_audio_tracks_payload,
        )
    )
    target_duration_ms = round(float(cues[-1]["end_time"]) * 1000)
    if not 50_000 <= target_duration_ms <= 70_000:
        raise ValueError("Shidu trial duration must be between 50 and 70 seconds")
    frozen_policy_overrides = dict(policy_overrides or {})
    try:
        policy_text = json.dumps(
            frozen_policy_overrides,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        frozen_policy_overrides = json.loads(policy_text)
    except (TypeError, ValueError) as exc:
        raise ValueError("policy_overrides must be canonical JSON") from exc
    if any(term in policy_text.casefold() for term in ("lipsync", "fallback")):
        raise ValueError("Shidu policy cannot introduce lipsync or fallback")

    script_id = str(trial_script_revision_id)
    common = {
        "project_id": str(project_id),
        "book_id": str(book_id),
        "trial_script_revision_id": script_id,
        "trial_script_digest": trial_script_digest,
        "compiler_revision": SHIDU_COMPILER_REVISION,
    }
    alignment = {
        "audio_alignment_policy_revision_id": str(
            audio_alignment_policy_revision_id
        ),
        "audio_alignment_policy_digest": audio_alignment_policy_digest,
        "maximum_cue_overrun_ms": int(
            alignment_snapshot["maximum_cue_overrun_ms"]
        ),
        "measured_duration_required": True,
        "speed_change_allowed": False,
    }
    episode_plan = {
        "schema_version": EPISODE_PLAN_SCHEMA_VERSION,
        "project_revision_id": script_id,
        "project_id": str(project_id),
        "episode_id": f"shidu-{trial_script_revision_id.hex[:24]}",
        "novel_title": "书单试读",
        "generation_strategy": {
            "generation_mode": "i2v",
            "duration_seconds": 8.0,
            "aspect_ratio": "9:16",
            "resolution": "480p",
            "model_id": "wan2.2-ti2v-5b",
            "audio_intent": "画面轨保持静音；最终声音仅来自已接受音频产物",
        },
        "shots": [
            {
                "unit_key": shot["unit_key"],
                "shot_id": shot["shot_id"],
                "ordinal": index,
                "prompt": shot["prompt"],
                "generation_mode": shot["generation_mode"],
            }
            for index, shot in enumerate(shots, start=1)
        ],
    }
    compiled_nodes: list[WorkflowNodeDefinition] = []
    for node in shidu_trial_workflow_definition().nodes:
        structured = dict(node.structured_inputs)
        if node.key == "trial-plan":
            structured.update(
                {
                    **common,
                    **alignment,
                    "voice_preset_revision_id": str(
                        voice_preset_revision_id
                    ),
                    "voice_preset_digest": voice_preset_digest,
                    "shot_keys": list(shot_keys),
                    "cue_keys": list(cue_keys),
                    "episode_plan": episode_plan,
                    "narration_cues": list(cues),
                    "voice_preset_snapshot": voice_snapshot,
                    "alignment_policy_snapshot": alignment_snapshot,
                    "final_audio_tracks": list(final_audio_tracks),
                    "target_duration_ms": target_duration_ms,
                    "compiler_revision": SHIDU_COMPILER_REVISION,
                }
            )
        elif "." in node.key:
            prefix, raw_ordinal = node.key.rsplit(".", 1)
            if raw_ordinal.isdigit() and 1 <= int(raw_ordinal) <= 6:
                index = int(raw_ordinal) - 1
                structured.update(
                    {
                        **common,
                        "shot_key": shot_keys[index],
                        "compiler_revision": SHIDU_COMPILER_REVISION,
                    }
                )
                if prefix == "shot-plan":
                    structured["unit_key"] = shot_keys[index]
                if prefix in {"generation", "prompt", "clip"}:
                    structured["generation_mode"] = shots[index][
                        "generation_mode"
                    ]
                if prefix == "prompt":
                    structured.update({"steps": 20, "cfg": 4.0})
                if prefix == "clip":
                    structured["mode"] = shots[index]["generation_mode"]
                if prefix in {"speech", "subtitle"}:
                    structured.update(
                        {
                            **alignment,
                            "cue_key": cue_keys[index],
                            "voice_preset_revision_id": str(
                                voice_preset_revision_id
                            ),
                            "voice_preset_digest": voice_preset_digest,
                            "voice_preset_snapshot": voice_snapshot,
                            "cue": cues[index],
                        }
                    )
                    if prefix == "speech":
                        cue_end_ms = round(
                            float(cues[index]["end_time"]) * 1_000
                        )
                        structured["maximum_cue_overrun_ms"] = min(
                            alignment["maximum_cue_overrun_ms"],
                            max(0, target_duration_ms - cue_end_ms),
                        )
        if node.key in {
            "audio-mix",
            "assemble",
            "final-gate",
            "delivery",
        }:
            structured.update({**common, **alignment})
            structured["target_duration_ms"] = target_duration_ms
        if node.key == "audio-mix":
            structured.update(
                {
                    "alignment_policy_snapshot": alignment_snapshot,
                    "final_audio_tracks": list(final_audio_tracks),
                    "narration_cues": list(cues),
                }
            )
        parameters = dict(node.parameter_snapshot)
        if node.key.startswith("shot-plan."):
            ordinal = int(node.key.rsplit(".", 1)[1])
            parameters["video_seed"] = 6200 + ordinal
        compiled_nodes.append(
            replace(
                node,
                structured_inputs=structured,
                parameter_snapshot=parameters,
            )
        )

    definition = WorkflowDefinition(
        workflow_key="factory.shidu-trial.v1",
        name="临界一刻六镜试读真实生产链",
        schema_revision="workflow.v1",
        nodes=tuple(compiled_nodes),
    )
    definition_digest = canonical_json_digest(definition.as_payload())

    raw_qc_policy = frozen_policy_overrides.get("factory_qc_policy")
    if raw_qc_policy is None:
        qc = FactoryQCPolicyPayload(stages={})
    elif isinstance(raw_qc_policy, Mapping):
        qc = FactoryQCPolicyPayload.model_validate(raw_qc_policy)
    else:
        raise ValueError("factory_qc_policy override must be an object")
    clip_policy = qc.stages["clip"].model_copy(
        update={"review_mode": "OFF", "exhaustion_policy": "BLOCK"}
    )
    final_policy = qc.stages["final"].model_copy(
        update={"review_mode": "OFF", "exhaustion_policy": "BLOCK"}
    )
    gate_policies = [
        compiled_gate_policy(
            stage="clip",
            gate_key=f"clip-gate.{index:03d}",
            policy=clip_policy,
            unit_key=shot_keys[index - 1],
            release_scope="current_script_revision",
        )
        for index in range(1, 7)
    ]
    gate_policies.append(
        compiled_gate_policy(
            stage="final",
            gate_key="final-gate",
            policy=final_policy,
            review_phase="machine",
        )
    )
    policy_snapshot = {
        "schema_version": "factory.shidu-trial-policy.v1",
        "compiler_revision": SHIDU_COMPILER_REVISION,
        "gate_policies": gate_policies,
        "trial_script": {
            **common,
            "shot_keys": list(shot_keys),
            "cue_keys": list(cue_keys),
        },
        "voice_preset": {
            "voice_preset_revision_id": str(voice_preset_revision_id),
            "voice_preset_digest": voice_preset_digest,
            "snapshot": voice_snapshot,
        },
        "audio_alignment": {
            **alignment,
            "snapshot": alignment_snapshot,
            "final_audio_tracks": list(final_audio_tracks),
        },
        "delivery_requirements": {
            "machine_qc": True,
            "human_approval": False,
            "exact_artifact_lineage": True,
        },
        "frozen_trial_payload": {
            "schema_version": SHIDU_TRIAL_SCRIPT_SCHEMA_VERSION,
            "shots": list(shots),
            "narration_cues": list(cues),
            "digest": trial_script_digest,
        },
        "policy_overrides": frozen_policy_overrides,
    }
    policy_digest = canonical_json_digest(policy_snapshot)
    run_identity = canonical_json_digest(
        {
            "compiler_revision": SHIDU_COMPILER_REVISION,
            "definition_digest": definition_digest,
            "policy_digest": policy_digest,
            "trial_script_digest": trial_script_digest,
            "project_id": str(project_id),
            "book_id": str(book_id),
            "trial_script_revision_id": script_id,
            "voice_preset_revision_id": str(voice_preset_revision_id),
            "voice_preset_digest": voice_preset_digest,
            "audio_alignment_policy_revision_id": str(
                audio_alignment_policy_revision_id
            ),
            "audio_alignment_policy_digest": audio_alignment_policy_digest,
        }
    )
    return CompiledShiduTrialWorkflow(
        definition=definition,
        definition_digest=definition_digest,
        policy_snapshot=policy_snapshot,
        run_identity=run_identity,
    )


__all__ = [
    "CompiledShiduTrialWorkflow",
    "EPISODE_PLAN_SCHEMA_VERSION",
    "SHIDU_COMPILER_REVISION",
    "SHIDU_TRIAL_SCRIPT_SCHEMA_VERSION",
    "compile_shidu_trial_workflow",
]
