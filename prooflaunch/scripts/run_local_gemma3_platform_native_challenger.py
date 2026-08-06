#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
from pathlib import Path
from typing import Any, Mapping


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "src"
if str(SOURCE) not in sys.path:
    sys.path.insert(0, str(SOURCE))

from prooflaunch_remix.files import atomic_write_text  # noqa: E402
from prooflaunch_remix.gtm_platform_native_challenger import (  # noqa: E402
    adapt_platform_native_candidate,
    candidate_failures,
    compile_platform_native_receipt,
    extract_first_json_object,
    verify_platform_native_challenger_plan,
)
from prooflaunch_remix.gtm_platform_generation_quality import (  # noqa: E402
    compile_platform_generation_quality_audit,
    compile_platform_generation_trace_audit,
    generation_quality_failures,
)


MODEL_ID = "mlx-community/gemma-3-12b-it-4bit"
SYSTEM_PROMPT = (
    "You are a platform-native senior GTM creative team working inside a deterministic harness. "
    "Return exactly one JSON object and no markdown. Produce original, evidence-disciplined creative work; "
    "never claim observed results, copy a named campaign, manufacture engagement or bypass platform controls."
)

DECODE_BLOCKED_TERMS = (
    "eliminate",
    "eliminates",
    "eliminated",
    "eliminating",
    "ensure",
    "ensures",
    "ensured",
    "ensuring",
    "increase",
    "increases",
    "increased",
    "increasing",
    "improve",
    "improves",
    "improved",
    "improving",
    "reduce",
    "reduces",
    "reduced",
    "reducing",
    "accelerate",
    "accelerates",
    "accelerated",
    "accelerating",
    "boost",
    "boosts",
    "boosted",
    "boosting",
    "solve",
    "solves",
    "solved",
    "solving",
    "prevent",
    "prevents",
    "prevented",
    "preventing",
    "guarantee",
    "guarantees",
    "guaranteed",
    "guaranteeing",
)


def _canonical(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _inside_project(value: str) -> Path:
    path = Path(value).expanduser().resolve()
    try:
        path.relative_to(ROOT.resolve())
    except ValueError as error:
        raise argparse.ArgumentTypeError("path must remain inside the project root") from error
    return path


def _model_manifest(snapshot: Path) -> tuple[str, str]:
    required = ("config.json", "tokenizer.json", "tokenizer_config.json", "model.safetensors.index.json")
    missing = [name for name in required if not (snapshot / name).is_file()]
    shards = sorted(snapshot.glob("model-*.safetensors"))
    if missing or not shards:
        raise SystemExit(f"local model snapshot is incomplete: missing={missing}, shards={len(shards)}")
    entries = [
        {"name": path.name, "bytes": path.stat().st_size, "blob_identity": path.resolve(strict=True).name}
        for path in sorted(item for item in snapshot.iterdir() if item.is_file())
    ]
    return snapshot.name, hashlib.sha256(_canonical(entries).encode("utf-8")).hexdigest()


def _render_prompt(tokenizer: Any, user_prompt: str) -> str:
    rendered = tokenizer.apply_chat_template(
        [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
        tokenize=False,
        add_generation_prompt=True,
    )
    return rendered + "{"


def _decode_logits_processors(tokenizer: Any) -> tuple[list[Any], int]:
    """Block only complete single-token claim verbs; semantic Harness remains authoritative."""

    from mlx_lm.sample_utils import make_logits_processors

    blocked_ids: set[int] = set()
    for term in DECODE_BLOCKED_TERMS:
        for variant in (term, " " + term, term.title(), " " + term.title()):
            try:
                token_ids = tokenizer.encode(variant, add_special_tokens=False)
            except TypeError:
                token_ids = tokenizer.encode(variant)
            if len(token_ids) == 1:
                blocked_ids.add(int(token_ids[0]))
    return make_logits_processors(
        logit_bias={token_id: -1e9 for token_id in blocked_ids}
    ), len(blocked_ids)


def _generate(model: Any, tokenizer: Any, prompt: str, *, seed: int) -> dict[str, Any]:
    import mlx.core as mx
    from mlx_lm import generate
    from mlx_lm.sample_utils import make_sampler

    mx.random.seed(seed)
    started = time.monotonic()
    logits_processors, blocked_single_token_count = _decode_logits_processors(
        tokenizer
    )
    continuation = generate(
        model,
        tokenizer,
        prompt=_render_prompt(tokenizer, prompt),
        max_tokens=1_350,
        sampler=make_sampler(temp=0.35, top_p=0.92),
        logits_processors=logits_processors,
        verbose=False,
    )
    raw = "{" + continuation.lstrip()
    try:
        token_count = len(tokenizer.encode(raw))
    except Exception:
        token_count = 0
    return {
        "raw_output": raw,
        "elapsed_seconds": time.monotonic() - started,
        "generated_token_count": token_count,
        "decode_blocked_single_token_count": blocked_single_token_count,
    }


def _failures(
    raw: str, *, plan: Mapping[str, Any], request: Mapping[str, Any]
) -> tuple[str, ...]:
    try:
        candidate = adapt_platform_native_candidate(
            extract_first_json_object(raw), plan=plan, request=request
        )
        base = candidate_failures(candidate, plan=plan, request=request)
        if base:
            return base
        return generation_quality_failures(candidate, plan=plan, request=request)
    except Exception as error:
        return (str(error),)


def _base_failures(
    raw: str, *, plan: Mapping[str, Any], request: Mapping[str, Any]
) -> tuple[str, ...]:
    try:
        candidate = adapt_platform_native_candidate(
            extract_first_json_object(raw), plan=plan, request=request
        )
        return candidate_failures(candidate, plan=plan, request=request)
    except Exception as error:
        return (str(error),)


def _repair_prompt(original: str, raw: str, failures: tuple[str, ...]) -> str:
    return (
        original
        + "\n\nPRIOR_DRAFT="
        + raw
        + "\n\nThe prior draft failed the deterministic platform Harness for exactly these reasons:\n- "
        + "\n- ".join(failures)
        + "\nReturn the complete JSON, but edit only the fields implicated by those failures and preserve every passing field verbatim. Do not explain the repair. "
        "Preserve the frozen brief, surface and approved claim. progression must be exactly four different complete sentences with at least nine words each; never output labels such as tension, reveal, proof, action, initial alignment, reality check or mechanism reveal. "
        "body must contain exactly one different plain string for every required body marker and no extra block. "
        "No hook, progression or body string may repeat another string. Outside the exact approved claim, never use "
        "eliminate, ensure, increase, improve, reduce, accelerate, boost, solve, prevent or guarantee in any tense. "
        "Never invent a first-person case history, previous campaign, internal incident, customer anecdote, competitor example, quarter, year, duration or numeric result. "
        "Never reference two responses, examples or versions that are absent from the body. Synthetic, hypothetical or composite capability cases are allowed only when every affected block visibly labels that evidence class; they are never production evidence. CTA and participation_mechanism must perform different jobs and cannot repeat the same sentence. "
        "For TikTok, keep every labeled beat inside the explicit runtime word budget from the original contract. "
        "Outside proof_integration, use approved product fact only as a neutral evidence-object label beside its source or limitation, never as the subject of an added capability, and never paraphrase the approved claim. Quote frozen product_truth exactly only when a product explanation is essential. "
        "Never use reflect on, visibility, transparency, confidence or alignment as a substitute for a concrete action. "
        "proof_integration must equal the exact approved claim with no wrapper. Return only the complete JSON."
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Generate thirteen platform-native challengers in one offline Gemma 3 MLX load."
    )
    parser.add_argument("--model-path", required=True)
    parser.add_argument("--plan", required=True, type=_inside_project)
    parser.add_argument("--output", required=True, type=_inside_project)
    parser.add_argument(
        "--quality-audit-output",
        type=_inside_project,
        help="Sealed deterministic pre-human generation-quality audit.",
    )
    parser.add_argument(
        "--trace-output",
        type=_inside_project,
        help="Private local trace containing raw model attempts for error analysis.",
    )
    parser.add_argument(
        "--resume-trace",
        type=_inside_project,
        help="Revalidate prior raw attempts against this plan and call the model only for still-failing surfaces.",
    )
    args = parser.parse_args()
    snapshot = Path(args.model_path).expanduser().resolve(strict=True)
    plan = json.loads(args.plan.read_text(encoding="utf-8"))
    verify_platform_native_challenger_plan(plan)
    prior_trace = (
        json.loads(args.resume_trace.read_text(encoding="utf-8"))
        if args.resume_trace
        else None
    )
    if prior_trace is not None:
        unsigned_trace = dict(prior_trace)
        supplied_trace_sha256 = unsigned_trace.pop("content_sha256", None)
        expected_trace_sha256 = hashlib.sha256(
            _canonical(unsigned_trace).encode("utf-8")
        ).hexdigest()
        if supplied_trace_sha256 != expected_trace_sha256:
            raise SystemExit("--resume-trace digest is invalid")
        if (
            prior_trace.get("business_model") != plan.get("business_model")
            or prior_trace.get("plan_sha256") != plan.get("content_sha256")
            or not isinstance(prior_trace.get("attempts_by_surface"), dict)
        ):
            raise SystemExit("--resume-trace does not match the current plan")
    revision, manifest_sha256 = _model_manifest(snapshot)
    os.environ.update(
        {
            "HF_HUB_OFFLINE": "1",
            "TRANSFORMERS_OFFLINE": "1",
            "HF_DATASETS_OFFLINE": "1",
            "HF_HUB_DISABLE_TELEMETRY": "1",
        }
    )
    from mlx_lm import load

    load_started = time.monotonic()
    model, tokenizer = load(str(snapshot), lazy=False)
    model_load_seconds = time.monotonic() - load_started
    attempts_by_surface: dict[str, list[dict[str, Any]]] = {}
    carried_surface_count = 0
    resumed_targeted_repair_count = 0
    trace_output = args.trace_output or args.output.with_name(
        args.output.stem + ".private-trace.json"
    )
    resume_seed_offset = (
        int(str(prior_trace["content_sha256"])[:8], 16) % 1_000_000
        if prior_trace is not None
        else 0
    )

    def checkpoint_trace() -> None:
        trace = {
            "schema": "ProofLaunchPlatformNativePrivateTraceV1",
            "plan_sha256": plan["content_sha256"],
            "business_model": plan["business_model"],
            "model_id": MODEL_ID,
            "model_revision": revision,
            "model_manifest_sha256": manifest_sha256,
            "attempts_by_surface": attempts_by_surface,
            "resume_from_trace_sha256": (
                prior_trace.get("content_sha256") if prior_trace is not None else None
            ),
            "completed_surface_count": len(attempts_by_surface),
            "carried_surface_count": carried_surface_count,
            "resumed_targeted_repair_count": resumed_targeted_repair_count,
            "contains_secrets": False,
            "external_publish_executed": False,
            "truth_boundary": "Private development trace for error analysis; raw model text is not accepted content or effect evidence.",
        }
        trace["content_sha256"] = hashlib.sha256(
            _canonical(trace).encode("utf-8")
        ).hexdigest()
        trace_output.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_text(
            trace_output,
            json.dumps(trace, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        )

    for index, request in enumerate(plan["requests"], start=1):
        surface_id = request["surface_id"]
        prior_attempts = (
            prior_trace["attempts_by_surface"].get(surface_id, [])
            if prior_trace is not None
            else []
        )
        carried = None
        for prior in prior_attempts:
            if not _failures(
                str(prior.get("raw_output", "")), plan=plan, request=request
            ):
                carried = dict(prior)
                carried["source"] = "prior_raw_revalidated_against_current_plan"
                break
        if carried is not None:
            print(f"[{index}/13] {surface_id} carry revalidated raw attempt", flush=True)
            attempts_by_surface[surface_id] = [carried]
            carried_surface_count += 1
            checkpoint_trace()
            continue
        if prior_attempts:
            prior_raw = str(prior_attempts[-1].get("raw_output", ""))
            prior_failures = _failures(
                prior_raw, plan=plan, request=request
            )
            print(
                f"[{index}/13] {surface_id} resume targeted repair: {' | '.join(prior_failures)}",
                flush=True,
            )
            first = _generate(
                model,
                tokenizer,
                _repair_prompt(request["prompt"], prior_raw, prior_failures),
                seed=20261203 + resume_seed_offset + index,
            )
            first["source"] = "resume_targeted_repair"
            resumed_targeted_repair_count += 1
        else:
            print(f"[{index}/13] {surface_id} draft", flush=True)
            first = _generate(
                model, tokenizer, request["prompt"], seed=20260803 + index
            )
            first["source"] = "fresh_generation"
        attempts = [first]
        failures = _failures(
            first["raw_output"], plan=plan, request=request
        )
        if failures:
            print(f"[{index}/13] {surface_id} repair: {' | '.join(failures)}", flush=True)
            second = _generate(
                model,
                tokenizer,
                _repair_prompt(request["prompt"], first["raw_output"], failures),
                seed=20262203 + resume_seed_offset + index,
            )
            second["source"] = (
                "bounded_resume_repair_retry"
                if prior_attempts
                else "bounded_repair"
            )
            attempts.append(second)
        attempts_by_surface[surface_id] = attempts
        checkpoint_trace()
    receipt_attempts: dict[str, list[dict[str, Any]]] = {}
    requests = {row["surface_id"]: row for row in plan["requests"]}
    for surface_id, attempts in attempts_by_surface.items():
        quality_pass = next(
            (
                attempt
                for attempt in reversed(attempts)
                if not _failures(
                    str(attempt.get("raw_output", "")),
                    plan=plan,
                    request=requests[surface_id],
                )
            ),
            None,
        )
        base_pass = next(
            (
                attempt
                for attempt in reversed(attempts)
                if not _base_failures(
                    str(attempt.get("raw_output", "")),
                    plan=plan,
                    request=requests[surface_id],
                )
            ),
            None,
        )
        receipt_attempts[surface_id] = [quality_pass or base_pass or attempts[-1]]
    receipt = compile_platform_native_receipt(
        plan=plan,
        model={
            "provider": "mlx_local",
            "device_family": "Apple Metal",
            "model_id": MODEL_ID,
            "model_revision": revision,
            "model_manifest_sha256": manifest_sha256,
            "model_load_count": 1,
            "model_load_seconds": round(model_load_seconds, 6),
            "network_download_performed": False,
            "cloud_api_calls": 0,
        },
        attempts_by_surface=receipt_attempts,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(
        args.output,
        json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
    )
    trace = json.loads(trace_output.read_text(encoding="utf-8"))
    trace_quality_audit = compile_platform_generation_trace_audit(
        plan=plan, trace=trace
    )
    trace_quality_audit_output = args.output.with_name(
        args.output.stem + ".trace-quality-audit.json"
    )
    atomic_write_text(
        trace_quality_audit_output,
        json.dumps(trace_quality_audit, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
    )
    if receipt["accepted_surface_count"] != 13:
        print(
            json.dumps(
                {
                    "output": str(args.output),
                    "status": receipt["status"],
                    "accepted_surface_count": receipt["accepted_surface_count"],
                    "content_sha256": receipt["content_sha256"],
                    "private_trace_output": str(trace_output),
                    "trace_quality_audit_output": str(trace_quality_audit_output),
                    "pre_human_quality_pass_count": trace_quality_audit[
                        "pre_human_quality_pass_count"
                    ],
                    "quality_audit_compiled": False,
                    "human_craft_review_completed_count": 0,
                    "production_effect_observed": False,
                },
                ensure_ascii=False,
                sort_keys=True,
            )
        )
        return 2
    quality_audit = compile_platform_generation_quality_audit(
        plan=plan, receipt=receipt
    )
    quality_audit_output = args.quality_audit_output or args.output.with_name(
        args.output.stem + ".quality-audit.json"
    )
    atomic_write_text(
        quality_audit_output,
        json.dumps(quality_audit, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
    )
    print(
        json.dumps(
            {
                "output": str(args.output),
                "status": receipt["status"],
                "accepted_surface_count": receipt["accepted_surface_count"],
                "content_sha256": receipt["content_sha256"],
                "private_trace_output": str(trace_output),
                "quality_audit_output": str(quality_audit_output),
                "pre_human_quality_pass_count": quality_audit[
                    "pre_human_quality_pass_count"
                ],
                "human_craft_review_completed_count": 0,
                "production_effect_observed": False,
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0 if (
        receipt["accepted_surface_count"] == 13
        and quality_audit["pre_human_quality_pass_count"] == 13
    ) else 2


if __name__ == "__main__":
    raise SystemExit(main())
