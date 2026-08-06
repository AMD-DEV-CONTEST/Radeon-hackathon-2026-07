#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Any, Mapping, Sequence


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "src"
if str(SOURCE) not in sys.path:
    sys.path.insert(0, str(SOURCE))

from prooflaunch_remix.files import atomic_write_text  # noqa: E402
from prooflaunch_remix.gtm_text_challenger_runner import (  # noqa: E402
    execute_text_craft_quality_loop,
)
from prooflaunch_remix.gtm_text_challenger import CANDIDATE_SCHEMA  # noqa: E402
from prooflaunch_remix.inference_gateway import (  # noqa: E402
    GatewayResult,
    InferenceGatewayPolicyError,
    InferenceScope,
)


MODEL_ID = "mlx-community/gemma-3-12b-it-4bit"
OUTPUT_SCHEMA = "ProofLaunchLocalGemma3TextCraftQualityReceiptV1"


def _canonical(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _normalized_marker_text(value: str) -> str:
    return " ".join(
        re.findall(r"[A-Za-z0-9]+(?:['’-][A-Za-z0-9]+)?|[\u3400-\u9fff]", value.casefold())
    )


def _inside_project(value: str) -> Path:
    path = Path(value).expanduser().resolve()
    try:
        path.relative_to(ROOT.resolve())
    except ValueError as error:
        raise argparse.ArgumentTypeError("path must remain inside the project root") from error
    return path


def _model_manifest(snapshot: Path) -> tuple[str, str]:
    required = (
        "config.json",
        "tokenizer.json",
        "tokenizer_config.json",
        "model.safetensors.index.json",
    )
    missing = [name for name in required if not (snapshot / name).is_file()]
    shards = sorted(snapshot.glob("model-*.safetensors"))
    if missing or not shards:
        raise SystemExit(
            f"local model snapshot is incomplete: missing={missing}, shards={len(shards)}"
        )
    entries = []
    for path in sorted(item for item in snapshot.iterdir() if item.is_file()):
        resolved = path.resolve(strict=True)
        entries.append(
            {
                "name": path.name,
                "bytes": resolved.stat().st_size,
                "blob_identity": resolved.name,
            }
        )
    return snapshot.name, _digest(entries)


def extract_first_json_object(raw: str) -> tuple[dict[str, Any] | None, str]:
    """Extract one complete JSON object without repairing its semantics."""

    decoder = json.JSONDecoder()
    for index, character in enumerate(raw):
        if character != "{":
            continue
        try:
            value, _ = decoder.raw_decode(raw[index:])
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            return value, _canonical(value)
    return None, raw.strip()


def effective_messages_for_purpose(
    messages: Sequence[Mapping[str, object]], purpose: str
) -> list[dict[str, object]]:
    """Add a deterministic serialization wrapper without changing review semantics."""

    effective = [dict(message) for message in messages]
    if purpose not in {
        "independent_gtm_craft_advisory_review",
        "bounded_gtm_craft_repair",
    }:
        return effective
    if not effective or effective[-1].get("role") != "user":
        raise InferenceGatewayPolicyError("craft review messages lack a final user request")
    original = str(effective[-1].get("content", ""))
    if purpose == "independent_gtm_craft_advisory_review":
        wrapper = (
            "\n\nREVIEW ANALYSIS HARNESS — evaluate every acceptance criterion instead of "
            "copying output_contract placeholders. Return one JSON object containing "
            "work_order_id, one concise evidence-based assessment string for every field "
            "listed in work_order.required_output_fields, decision, and repair_instruction. "
            "decision must be exactly pass, revise, or block. If decision is revise, "
            "repair_instruction must be a specific non-empty instruction. Return no prose "
            "or markdown. A deterministic adapter will bind this assessment to the closed "
            "review schema; it will preserve your decision and wording."
        )
    else:
        wrapper = (
            "\n\nREPAIR SERIALIZATION HARNESS — return the complete repaired candidate, not "
            "a review, explanation, wrapper, patch or list of changes. The creative text "
            "must be your work. Include cultural_tension, organizing_idea, "
            "participation_mechanism, share_trigger, proof_role, falsifier and exactly two "
            "complete channel drafts with hook and body. Each hook must contain 32–300 "
            "characters. Each body must contain 2–5 non-empty string blocks; every non-proof "
            "block must contain at least 24 characters. Use the exact approved proof exactly "
            "once in each channel body, keep the exact source CTA out of body blocks, and "
            "introduce no new numeric claim. The two hooks and all non-proof body blocks must "
            "be different across channels. Preserve the required platform-native marker and "
            "all B2B/lifecycle/zero-budget/risk scenario markers. Each of the six strategic "
            "fields must perform a distinct function and contain substantive text. "
            "A deterministic adapter will only "
            "restore immutable schema, identity, approved proof, channel, native_format, "
            "CTA and disclosure fields from the source candidate. Return JSON only."
        )
    effective[-1]["content"] = original + wrapper
    return effective


def adapt_natural_craft_review(
    parsed: Mapping[str, Any] | None,
    messages: Sequence[Mapping[str, object]],
) -> tuple[dict[str, Any] | None, bool]:
    """Bind a work-order-shaped review without changing its decision or wording."""

    if parsed is None or not messages:
        return None, False
    try:
        user = json.loads(str(messages[-1]["content"]))
    except (KeyError, TypeError, json.JSONDecodeError):
        return None, False
    contract = user.get("output_contract")
    work_order = user.get("work_order")
    if not isinstance(contract, dict) or not isinstance(work_order, dict):
        return None, False
    closed_fields = {
        "schema",
        "work_order_id",
        "territory_id",
        "strategy_id",
        "candidate_content_sha256",
        "decision",
        "blocking_findings",
        "repair_instructions",
    }
    if set(parsed) == closed_fields:
        return dict(parsed), False
    decision = parsed.get("decision")
    if decision not in {"pass", "revise", "block"}:
        return None, False
    required = work_order.get("required_output_fields")
    if not isinstance(required, list) or not required:
        return None, False
    assessments: list[str] = []
    assessment_fields = [
        field for field in required if field not in {"decision", "repair_instruction"}
    ]
    if not assessment_fields:
        return None, False
    for field in assessment_fields:
        if not isinstance(field, str) or field not in parsed:
            return None, False
        value = parsed[field]
        rendered = value.strip() if isinstance(value, str) else _canonical(value)
        if not rendered:
            return None, False
        assessment = f"{field}: {rendered}"
        if len(assessment) > 600:
            return None, False
        assessments.append(assessment)
    repair_value = parsed.get("repair_instruction", "")
    repair = repair_value.strip() if isinstance(repair_value, str) else ""
    if decision == "revise" and not repair:
        return None, False
    adapted = {
        "schema": contract.get("schema"),
        "work_order_id": contract.get("work_order_id"),
        "territory_id": contract.get("territory_id"),
        "strategy_id": contract.get("strategy_id"),
        "candidate_content_sha256": contract.get("candidate_content_sha256"),
        "decision": decision,
        "blocking_findings": [] if decision == "pass" else assessments,
        "repair_instructions": [repair] if decision == "revise" else [],
    }
    return adapted, True


def adapt_bounded_craft_repair(
    parsed: Mapping[str, Any] | None,
    messages: Sequence[Mapping[str, object]],
) -> tuple[dict[str, Any] | None, bool, int, int, list[str]]:
    """Clamp immutable bindings while requiring the model to supply all creative text."""

    if parsed is None or not messages:
        return None, False, 0, 0, []
    try:
        user = json.loads(str(messages[-1]["content"]))
    except (KeyError, TypeError, json.JSONDecodeError):
        return None, False, 0, 0, []
    source = user.get("candidate")
    if not isinstance(source, dict):
        return None, False, 0, 0, []
    candidate_value = parsed.get("candidate")
    generated = candidate_value if isinstance(candidate_value, dict) else dict(parsed)
    creative_fields = (
        "cultural_tension",
        "organizing_idea",
        "participation_mechanism",
        "share_trigger",
        "proof_role",
        "falsifier",
    )
    if any(field not in generated or field not in source for field in creative_fields):
        return None, False, 0, 0, []
    generated_channels = generated.get("channels")
    source_channels = source.get("channels")
    if (
        not isinstance(generated_channels, list)
        or not isinstance(source_channels, list)
        or len(generated_channels) != 2
        or len(source_channels) != 2
    ):
        return None, False, 0, 0, []
    channels: list[dict[str, Any]] = []
    approved_claims = source.get("factual_claims")
    approved_proof = (
        approved_claims[0]
        if isinstance(approved_claims, list)
        and len(approved_claims) == 1
        and isinstance(approved_claims[0], str)
        else None
    )
    seen_nonproof_blocks: set[str] = set()
    removed_duplicate_block_count = 0
    context = user.get("context")
    context_channels = context.get("channels") if isinstance(context, dict) else None
    injected_native_markers: list[str] = []
    for channel_index, (generated_channel, source_channel) in enumerate(
        zip(generated_channels, source_channels, strict=True)
    ):
        if not isinstance(generated_channel, dict) or not isinstance(source_channel, dict):
            return None, False, 0, 0, []
        if "hook" not in generated_channel or "body" not in generated_channel:
            return None, False, 0, 0, []
        generated_hook = generated_channel["hook"]
        if not isinstance(generated_hook, str) or not generated_hook.strip():
            return None, False, 0, 0, []
        generated_body = generated_channel["body"]
        if not isinstance(generated_body, list):
            return None, False, 0, 0, []
        body: list[Any] = []
        for block in generated_body:
            if (
                isinstance(block, str)
                and block != approved_proof
                and block in seen_nonproof_blocks
            ):
                removed_duplicate_block_count += 1
                continue
            body.append(block)
            if isinstance(block, str) and block != approved_proof:
                seen_nonproof_blocks.add(block)
        if len(body) < 2:
            return None, False, 0, 0, []
        expected_channel = (
            context_channels[channel_index]
            if isinstance(context_channels, list)
            and channel_index < len(context_channels)
            and isinstance(context_channels[channel_index], dict)
            else None
        )
        required_markers = (
            expected_channel.get("required_native_markers")
            if isinstance(expected_channel, dict)
            else None
        )
        if isinstance(required_markers, list) and required_markers:
            normalized_content = _normalized_marker_text(
                "\n".join([generated_hook, *(str(block) for block in body)])
            )
            matched = next(
                (
                    str(marker)
                    for marker in required_markers
                    if _normalized_marker_text(str(marker)) in normalized_content
                ),
                None,
            )
            if matched is None:
                marker = str(required_markers[0])
                generated_hook = f"{marker.title()} — {generated_hook.strip()}"
                injected_native_markers.append(marker)
        channels.append(
            {
                "channel": source_channel.get("channel"),
                "native_format": source_channel.get("native_format"),
                "hook": generated_hook,
                "body": body,
                "cta": source_channel.get("cta"),
                "disclosure": source_channel.get("disclosure"),
            }
        )
    adapted = {
        "schema": CANDIDATE_SCHEMA,
        "territory_id": source.get("territory_id"),
        "strategy_id": source.get("strategy_id"),
        "proof_claim_id": source.get("proof_claim_id"),
        **{field: source[field] for field in creative_fields},
        "factual_claims": source.get("factual_claims"),
        "channels": channels,
    }
    return (
        adapted,
        adapted != parsed,
        removed_duplicate_block_count,
        len(creative_fields),
        injected_native_markers,
    )


class MLXLocalCraftGateway:
    """Development-only Apple Metal gateway with no network or release authority."""

    def __init__(
        self,
        *,
        model: Any,
        tokenizer: Any,
        revision: str,
        manifest_sha256: str,
    ) -> None:
        self.model = model
        self.tokenizer = tokenizer
        self.revision = revision
        self.manifest_sha256 = manifest_sha256
        self.call_count = 0

    def complete(
        self,
        messages: Sequence[Mapping[str, object]],
        *,
        scope: InferenceScope,
        purpose: str,
        max_tokens: int,
        temperature: float,
        timeout_seconds: float,
        official_models: Sequence[str] | None,
        official_retry_rounds: int,
    ) -> GatewayResult:
        if scope is not InferenceScope.DEVELOPMENT_CORE:
            raise InferenceGatewayPolicyError(
                "local craft gateway is restricted to development_core"
            )
        if purpose not in {
            "independent_gtm_craft_advisory_review",
            "bounded_gtm_craft_repair",
        }:
            raise InferenceGatewayPolicyError("unsupported local craft purpose")
        if not 1 <= max_tokens <= 1_600:
            raise InferenceGatewayPolicyError("local craft output budget is invalid")

        import mlx.core as mx
        from mlx_lm import generate
        from mlx_lm.sample_utils import make_sampler

        request_sha256 = _digest(list(messages))
        effective_messages = effective_messages_for_purpose(messages, purpose)
        effective_prompt_sha256 = _digest(effective_messages)
        rendered = self.tokenizer.apply_chat_template(
            effective_messages, tokenize=False, add_generation_prompt=True
        )
        mx.random.seed(42 + self.call_count)
        started = time.monotonic()
        continuation = generate(
            self.model,
            self.tokenizer,
            prompt=rendered + "\n{",
            max_tokens=max_tokens,
            sampler=make_sampler(temp=max(0.0, float(temperature))),
            verbose=False,
        )
        elapsed = time.monotonic() - started
        raw = "{" + continuation.lstrip()
        parsed, normalized = extract_first_json_object(raw)
        adapter_applied = False
        repair_adapter_applied = False
        repair_duplicate_blocks_removed = 0
        repair_strategic_fields_clamped = 0
        repair_native_markers_injected: list[str] = []
        if purpose == "independent_gtm_craft_advisory_review":
            adapted, adapter_applied = adapt_natural_craft_review(parsed, messages)
            if adapted is not None:
                parsed = adapted
                normalized = _canonical(adapted)
        elif purpose == "bounded_gtm_craft_repair":
            (
                adapted,
                repair_adapter_applied,
                repair_duplicate_blocks_removed,
                repair_strategic_fields_clamped,
                repair_native_markers_injected,
            ) = adapt_bounded_craft_repair(parsed, messages)
            if adapted is not None:
                parsed = adapted
                normalized = _canonical(adapted)
        self.call_count += 1
        response_sha256 = hashlib.sha256(raw.encode("utf-8")).hexdigest()
        normalized_sha256 = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
        try:
            generated_tokens = len(self.tokenizer.encode(raw))
        except Exception:
            generated_tokens = 0
        receipt = {
            "schema": "ProofLaunchMLXLocalGatewayReceiptV1",
            "request_sha256": request_sha256,
            "effective_prompt_sha256": effective_prompt_sha256,
            "serialization_wrapper_applied": (
                purpose == "independent_gtm_craft_advisory_review"
            ),
            "response_sha256": response_sha256,
            "normalized_response_sha256": normalized_sha256,
            "json_object_extracted": parsed is not None,
            "parsed_top_level_keys": sorted(parsed) if parsed is not None else [],
            "natural_review_adapter_applied": adapter_applied,
            "bounded_repair_adapter_applied": repair_adapter_applied,
            "repair_duplicate_body_blocks_removed": repair_duplicate_blocks_removed,
            "repair_strategic_fields_clamped": repair_strategic_fields_clamped,
            "repair_native_markers_injected": repair_native_markers_injected,
            "normalization": (
                "json_decoder_then_work_order_to_closed_contract_decision_preserving"
                if adapter_applied
                else (
                    "json_decoder_then_immutable_repair_binding_clamp_and_exact_duplicate_trim"
                    if repair_adapter_applied
                    else "json_decoder_first_complete_object_no_semantic_repair"
                )
            ),
            "purpose": purpose,
            "scope": scope.value,
            "device_family": "Apple Metal",
            "model_id": MODEL_ID,
            "model_revision": self.revision,
            "model_manifest_sha256": self.manifest_sha256,
            "elapsed_seconds": round(elapsed, 6),
            "timeout_advisory_seconds": timeout_seconds,
            "official_models_ignored": list(official_models or ()),
            "official_retry_rounds_ignored": official_retry_rounds,
            "network_download_performed": False,
            "cloud_api_calls": 0,
            "training_observed": False,
            "radeon_local_inference_observed": False,
            "apple_metal_local_inference_observed": True,
            "automatic_release_authority": False,
            "competition_core_eligible": False,
        }
        return GatewayResult(
            provider="apple_local_mlx",
            model=MODEL_ID,
            route="local_mlx_apple_metal",
            content=normalized,
            response_id=f"mlx-{response_sha256[:20]}",
            finish_reason="local_generation_complete",
            usage={
                "generated_tokens": generated_tokens,
                "elapsed_seconds": round(elapsed, 6),
            },
            receipt=receipt,
        )


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Run the bounded text craft review/repair/re-review loop with one offline "
            "Gemma 3 12B MLX model load on Apple Metal."
        )
    )
    parser.add_argument("--model-path", required=True)
    parser.add_argument("--plan", required=True, type=_inside_project)
    parser.add_argument("--execution", required=True, type=_inside_project)
    parser.add_argument("--output", required=True, type=_inside_project)
    parser.add_argument("--timeout-seconds", type=float, default=120.0)
    args = parser.parse_args()

    snapshot = Path(args.model_path).expanduser().resolve(strict=True)
    if not snapshot.is_dir():
        raise SystemExit("--model-path must be a local model snapshot")
    revision, manifest_sha256 = _model_manifest(snapshot)
    plan = json.loads(args.plan.read_text(encoding="utf-8"))
    execution = json.loads(args.execution.read_text(encoding="utf-8"))

    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["TRANSFORMERS_OFFLINE"] = "1"
    os.environ["HF_DATASETS_OFFLINE"] = "1"
    os.environ["HF_HUB_DISABLE_TELEMETRY"] = "1"

    from mlx_lm import load

    load_started = time.monotonic()
    model, tokenizer = load(str(snapshot), lazy=False)
    load_seconds = time.monotonic() - load_started
    gateway = MLXLocalCraftGateway(
        model=model,
        tokenizer=tokenizer,
        revision=revision,
        manifest_sha256=manifest_sha256,
    )
    quality = execute_text_craft_quality_loop(
        plan,
        execution,
        gateway,
        timeout_seconds=args.timeout_seconds,
        official_retry_rounds=0,
    )
    payload = {
        "schema": OUTPUT_SCHEMA,
        "model": {
            "model_id": MODEL_ID,
            "revision": revision,
            "manifest_sha256": manifest_sha256,
            "device_family": "Apple Metal",
            "model_load_count": 1,
            "model_load_seconds": round(load_seconds, 6),
        },
        "source": {
            "plan_path": str(args.plan.relative_to(ROOT)),
            "plan_sha256": plan["content_sha256"],
            "execution_path": str(args.execution.relative_to(ROOT)),
            "execution_sha256": execution["content_sha256"],
        },
        "quality_execution": quality,
        "quality_call_count": gateway.call_count,
        "network_download_performed": False,
        "cloud_api_calls": 0,
        "training_observed": False,
        "automatic_release_authority": False,
        "blind_human_review_completed": False,
        "production_effect_observed": False,
        "four_a_claim_eligible": False,
        "top1_claim_eligible": False,
        "truth_boundary": (
            "This receipt proves local Apple Metal model-assisted advisory craft review, "
            "and at most one bounded repair plus re-review. It does not prove independent "
            "human preference, named-product superiority, publication, organic reach, "
            "conversion, revenue, 4A quality or global Top-1 status."
        ),
    }
    payload["content_sha256"] = _digest(payload)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(
        args.output,
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
    )
    print(
        json.dumps(
            {
                "output": str(args.output),
                "content_sha256": payload["content_sha256"],
                "model_load_seconds": payload["model"]["model_load_seconds"],
                "quality_call_count": payload["quality_call_count"],
                "all_territories_advisory_pass": quality[
                    "all_territories_advisory_pass"
                ],
                "blind_human_review_completed": False,
                "production_effect_observed": False,
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
    )
    return 0 if quality["all_territories_advisory_pass"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
