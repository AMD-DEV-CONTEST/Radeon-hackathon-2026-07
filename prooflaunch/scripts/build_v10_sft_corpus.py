from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from prooflaunch_remix.files import atomic_write_text  # noqa: E402
from prooflaunch_remix.v10_sft_contract import (  # noqa: E402
    CurriculumInput,
    CurriculumStage,
    default_stage_definitions,
)
from prooflaunch_remix.v10_sft_corpus import (  # noqa: E402
    SFT_CORPUS_SCHEMA,
    SFT_RECORD_SCHEMA,
    TARGET_SFT_EPISODES,
    SFTEpisode,
    stable_sha256,
    verify_sft_summary,
)


SYSTEM_PROMPT = (
    "You are a source-bound GTM employee. Use only supplied evidence metadata. "
    "Never invent media observations, performance claims, hidden reasoning, or external actions. "
    "Return one JSON object matching the requested stage outputs."
)


def _load_sources(path: Path) -> list[dict[str, Any]]:
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]
    admitted = [row for row in rows if row["training_allowed"] and not row["trademark_hold"]]
    if len(rows) != 2_000 or len(admitted) != 1_994:
        raise RuntimeError("source bundle count or rights admission drift")
    return admitted


def _source_pools(rows: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    visual = [row for row in rows if row["media_type"].startswith("image/")]
    video = [row for row in rows if row["kind"] == "video"]
    audio = [row for row in rows if row["kind"] == "audio"]
    text = [row for row in rows if row["media_type"].startswith("text/")]
    pools = {
        CurriculumInput.SHORT_TEXT.value: text,
        CurriculumInput.LONG_DOCUMENT.value: text,
        CurriculumInput.SINGLE_IMAGE.value: visual,
        CurriculumInput.MULTI_IMAGE.value: visual,
        CurriculumInput.VIDEO_FRAMES.value: video,
        CurriculumInput.AUDIO.value: audio,
        CurriculumInput.TOOL_TRAJECTORY.value: rows,
        CurriculumInput.STATE_TRAJECTORY.value: rows,
        CurriculumInput.CROSS_CHANNEL.value: rows,
    }
    if any(not pool for pool in pools.values()):
        raise RuntimeError("one or more SFT modality source pools are empty")
    return pools


def _balanced(pool: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_provider: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in sorted(pool, key=lambda item: item["source_id"]):
        by_provider[row["provider"]].append(row)
    providers = sorted(by_provider)
    result: list[dict[str, Any]] = []
    offsets = {provider: 0 for provider in providers}
    target = max(len(values) for values in by_provider.values()) * len(providers)
    for index in range(target):
        provider = providers[index % len(providers)]
        values = by_provider[provider]
        result.append(values[offsets[provider] % len(values)])
        offsets[provider] += 1
    return result


def _output_value(stage: str, field: str, family: str, sources: list[dict[str, Any]]) -> Any:
    locators = [row["evidence_url"] for row in sources]
    values: dict[str, Any] = {
        "claim_source_locator": locators,
        "evidence_conflict": "none_observed_in_supplied_metadata",
        "icp": "evidence-accountable GTM team",
        "jtbd": "turn licensed inputs into a reviewable campaign decision",
        "audience_uncertainty": "audience response is unobserved",
        "smp": "one source-bound decision before production",
        "rtb": locators,
        "offer": "bounded review artifact; no outcome promise",
        "big_idea": f"Evidence before amplification — {family}",
        "creative_route": "source-led modular system",
        "headline": "Make every launch claim traceable",
        "body_copy": "Use the supplied evidence, preserve uncertainty, and stop before unsupported claims.",
        "cta": "Review the evidence pack",
        "key_visual_brief": "Use the referenced asset only after payload verification; do not infer unseen pixels.",
        "layout_constraints": ["source locator visible", "claim adjacent to evidence", "safe-zone reserved"],
        "channel_adaptation": "preserve the same claim and locator across every channel",
        "cross_channel_claim": "no channel may strengthen an unverified claim",
        "asset_spec": {"status": "materialization_required", "locators": locators},
        "render_checks": ["identity", "legibility", "safe_zone", "claim_evidence"],
        "risk_decision": "hold if payload, consent, trademark, or claim evidence is unresolved",
        "required_disclosure": "Evidence scope and unobserved outcomes must remain visible.",
        "first_error": "none_observed_in_supplied_metadata",
        "propagation": [],
        "severity": "unknown_until_payload_review",
        "minimal_patch": "materialize and verify the referenced payload before adding observations",
        "repair_verification": "re-run schema, rights, claim, and modality-retention gates",
        "memory_operation": "write_source_bound_summary",
        "scope_and_ttl": {"scope": family, "ttl": "campaign_end"},
        "bounded_plan": ["verify source", "materialize payload", "draft", "audit", "request approval"],
        "tool_budget": {"maximum_calls": 5, "publish_calls": 0},
        "stop_retry_fallback_escalate": "stop_and_escalate_if_required_evidence_is_missing",
        "terminal_reason": "external action and unsupported inference are outside this episode",
    }
    return values[field]


def _episode(index: int, source_cycles: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
    stages = tuple(CurriculumStage)
    inputs = tuple(CurriculumInput)
    stage = stages[index % len(stages)].value
    input_kind = inputs[index % len(inputs)].value
    pool = source_cycles[input_kind]
    width = 2 if input_kind in {"multi_image", "cross_channel"} else 1
    sources = [pool[(index * width + offset) % len(pool)] for offset in range(width)]
    family = f"sft-family-{index:05d}"
    split = "validation" if index % 10 == 9 else "train"
    required = next(
        item.required_outputs for item in default_stage_definitions() if item.stage.value == stage
    )
    evidence = [
        {
            "source_id": row["source_id"],
            "provider": row["provider"],
            "title": row["title"],
            "kind": row["kind"],
            "license": row["license_id"],
            "revision": row["revision"],
            "evidence_url": row["evidence_url"],
            "asset_url": row["asset_url"],
        }
        for row in sources
    ]
    # The builder reads the rights manifest and evidence metadata only.  Raw
    # media/document payloads are deliberately not treated as observed.
    payload_observed = False
    prompt = (
        f"Scenario family: {family}\nStage: {stage}\nInput kind: {input_kind}\n"
        f"Payload observed by corpus builder: {str(payload_observed).lower()}\n"
        f"Evidence metadata: {json.dumps(evidence, ensure_ascii=False, sort_keys=True)}\n"
        f"Return outputs: {', '.join(required)}. Keep unobserved modality content unknown."
    )
    completion = {
        "scenario_family_id": family,
        "stage": stage,
        "decision": "bounded_draft",
        "outputs": {
            field: _output_value(stage, field, family, sources) for field in required
        },
        "evidence_source_ids": [row["source_id"] for row in sources],
        "modality_payload_observed": payload_observed,
        "requires_human_approval_for_external_action": True,
    }
    material = {
        "schema": SFT_RECORD_SCHEMA,
        "episode_id": f"sft-{index + 1:05d}",
        "scenario_family_id": family,
        "split": split,
        "stage": stage,
        "input_kind": input_kind,
        "system_prompt": SYSTEM_PROMPT,
        "user_prompt": prompt,
        "completion": completion,
        "source_ids": tuple(row["source_id"] for row in sources),
        "source_revisions": tuple(row["revision"] for row in sources),
        "source_identity_sha256s": tuple(row["identity_sha256"] for row in sources),
        "evidence_urls": tuple(row["evidence_url"] for row in sources),
        "asset_urls": tuple(row["asset_url"] for row in sources),
        "license_ids": tuple(row["license_id"] for row in sources),
        "license_urls": tuple(row["license_url"] for row in sources),
        "rights_verified": True,
        "training_allowed": True,
        "trademark_hold": False,
        "model_generated": False,
        "hidden_reasoning": False,
        "external_side_effect": False,
        "modality_payload_observed": payload_observed,
    }
    material["content_sha256"] = stable_sha256(material)
    SFTEpisode(**material)
    return material


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", default="data/v10_sft_corpus")
    args = parser.parse_args()
    output = ROOT / args.output_dir
    output.mkdir(parents=True, exist_ok=True)
    sources = _load_sources(ROOT / "data/v10_source_bundle/sources.jsonl")
    cycles = {key: _balanced(value) for key, value in _source_pools(sources).items()}

    rows = [_episode(index, cycles) for index in range(TARGET_SFT_EPISODES)]
    lines = [json.dumps(row, ensure_ascii=False, sort_keys=True) for row in rows]
    corpus_text = "\n".join(lines) + "\n"
    corpus_sha = hashlib.sha256(corpus_text.encode("utf-8")).hexdigest()
    corpus_path = output / "episodes.jsonl"
    atomic_write_text(corpus_path, corpus_text)

    stages = Counter(row["stage"] for row in rows)
    inputs = Counter(row["input_kind"] for row in rows)
    splits = Counter(row["split"] for row in rows)
    providers = Counter(
        provider
        for row in rows
        for provider in {
            source["provider"]
            for source in sources
            if source["source_id"] in row["source_ids"]
        }
    )
    provider_mentions = sum(providers.values())
    base = {
        "schema": SFT_CORPUS_SCHEMA,
        "episode_count": len(rows),
        "train_count": splits["train"],
        "validation_count": splits["validation"],
        "test_split_count": 0,
        "stage_counts": dict(sorted(stages.items())),
        "input_counts": dict(sorted(inputs.items())),
        "provider_episode_mentions": dict(sorted(providers.items())),
        "maximum_provider_share": max(providers.values()) / provider_mentions,
        "duplicate_episode_count": len(rows) - len({row["episode_id"] for row in rows}),
        "duplicate_content_count": len(rows) - len({row["content_sha256"] for row in rows}),
        "rights_failure_count": 0,
        "model_generated_count": 0,
        "hidden_reasoning_count": 0,
        "external_side_effect_count": 0,
        "payload_observed_count": sum(row["modality_payload_observed"] for row in rows),
        "payload_materialization_required_count": sum(not row["modality_payload_observed"] for row in rows),
        "source_bundle_sha256": hashlib.sha256(
            (ROOT / "data/v10_source_bundle/sources.jsonl").read_bytes()
        ).hexdigest(),
        "corpus_content_sha256": corpus_sha,
        "training_observed": False,
        "adapter_observed": False,
        "truth_boundary": (
            "This proves 15,000 deterministic, rights-bound SFT episode records. "
            "It does not prove media payload materialization, teacher-model review, human gold review, training, or adapter quality."
        ),
    }
    manifest_material = dict(base)
    base["manifest_sha256"] = stable_sha256(manifest_material)
    verify_sft_summary(base)
    atomic_write_text(output / "manifest.json", json.dumps(base, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"status": "passed_corpus_construction_not_training", **base}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
