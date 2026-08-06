#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import sys
import time
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "src"
if str(SOURCE) not in sys.path:
    sys.path.insert(0, str(SOURCE))

from prooflaunch_remix.files import atomic_write_text  # noqa: E402
from prooflaunch_remix.gtm_platform_generation_quality import (  # noqa: E402
    compile_platform_generation_trace_audit,
)
from prooflaunch_remix.gtm_platform_native_challenger import (  # noqa: E402
    build_concept_anchored_draft_prompt,
    build_platform_native_concept_prompt,
    extract_platform_native_concept,
    platform_native_concept_failures,
    verify_platform_native_challenger_plan,
)


RUNNER_PATH = ROOT / "scripts/run_local_gemma3_platform_native_challenger.py"
SPEC = importlib.util.spec_from_file_location("prooflaunch_platform_runner", RUNNER_PATH)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError("failed to load platform-generation runner")
RUNNER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(RUNNER)


def _parse_concept(raw: str) -> dict[str, str]:
    return extract_platform_native_concept(raw)


def _concept_failures(
    raw: str, *, plan: dict[str, Any], request: dict[str, Any]
) -> tuple[str, ...]:
    try:
        return platform_native_concept_failures(
            _parse_concept(raw), plan=plan, request=request
        )
    except Exception as error:
        return (str(error),)


def _concept_repair_prompt(original: str, failures: tuple[str, ...]) -> str:
    return (
        original
        + "\n\nThe prior private concept failed for exactly these reasons:\n- "
        + "\n- ".join(failures)
        + "\nChoose a materially different concept and return the complete flat JSON only. "
        "Do not explain the repair and do not add keys."
    )


def _inside_project(value: str) -> Path:
    path = Path(value).expanduser().resolve()
    try:
        path.relative_to(ROOT.resolve())
    except ValueError as error:
        raise argparse.ArgumentTypeError("path must remain inside the project root") from error
    return path


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Probe selected platform contracts in one offline Gemma 3 MLX load."
    )
    parser.add_argument("--model-path", required=True)
    parser.add_argument("--plan", required=True, type=_inside_project)
    parser.add_argument("--surfaces", nargs="+", required=True)
    parser.add_argument("--trace-output", required=True, type=_inside_project)
    parser.add_argument("--audit-output", required=True, type=_inside_project)
    parser.add_argument(
        "--concept-first",
        action="store_true",
        help="Use a compact private concept call before the platform rendering call.",
    )
    parser.add_argument(
        "--resume-concept-trace",
        type=_inside_project,
        help="Digest-verify and reuse passing private concepts from an earlier bound trace.",
    )
    parser.add_argument(
        "--max-repair-rounds",
        type=int,
        default=2,
        choices=range(0, 4),
        help="Maximum targeted draft repairs after the initial render (default: 2).",
    )
    args = parser.parse_args()

    plan = json.loads(args.plan.read_text(encoding="utf-8"))
    verify_platform_native_challenger_plan(plan)
    prior_concept_trace = (
        json.loads(args.resume_concept_trace.read_text(encoding="utf-8"))
        if args.resume_concept_trace
        else None
    )
    if prior_concept_trace is not None:
        unsigned = dict(prior_concept_trace)
        supplied = unsigned.pop("content_sha256", None)
        expected = hashlib.sha256(
            RUNNER._canonical(unsigned).encode("utf-8")
        ).hexdigest()
        if supplied != expected:
            raise SystemExit("--resume-concept-trace digest is invalid")
        if (
            prior_concept_trace.get("plan_sha256") != plan.get("content_sha256")
            or not isinstance(prior_concept_trace.get("concepts_by_surface"), dict)
        ):
            raise SystemExit("--resume-concept-trace does not match the current plan")
    requests = {row["surface_id"]: row for row in plan["requests"]}
    selected = list(dict.fromkeys(args.surfaces))
    unknown = [surface for surface in selected if surface not in requests]
    if unknown:
        raise SystemExit(f"unknown platform surfaces: {unknown}")
    snapshot = Path(args.model_path).expanduser().resolve(strict=True)
    revision, manifest_sha256 = RUNNER._model_manifest(snapshot)
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
    concepts_by_surface: dict[str, list[dict[str, Any]]] = {}
    carried_concept_count = 0

    def checkpoint() -> dict[str, Any]:
        trace: dict[str, Any] = {
            "schema": "ProofLaunchPlatformNativePrivateTraceV1",
            "plan_sha256": plan["content_sha256"],
            "business_model": plan["business_model"],
            "model_id": RUNNER.MODEL_ID,
            "model_revision": revision,
            "model_manifest_sha256": manifest_sha256,
            "model_load_count": 1,
            "model_load_seconds": round(model_load_seconds, 6),
            "attempts_by_surface": attempts_by_surface,
            "concepts_by_surface": concepts_by_surface,
            "resume_from_concept_trace_sha256": (
                prior_concept_trace.get("content_sha256")
                if prior_concept_trace is not None
                else None
            ),
            "carried_concept_count": carried_concept_count,
            "generation_mode": (
                "concept_then_render_then_repair"
                if args.concept_first
                else "direct_render_then_repair"
            ),
            "resume_from_trace_sha256": None,
            "completed_surface_count": len(attempts_by_surface),
            "carried_surface_count": 0,
            "resumed_targeted_repair_count": 0,
            "selected_probe_surfaces": selected,
            "network_download_performed": False,
            "cloud_api_calls": 0,
            "contains_secrets": False,
            "external_publish_executed": False,
            "truth_boundary": "Selected-surface local development probe; raw model text is not accepted content or effect evidence.",
        }
        trace["content_sha256"] = hashlib.sha256(
            RUNNER._canonical(trace).encode("utf-8")
        ).hexdigest()
        args.trace_output.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_text(
            args.trace_output,
            json.dumps(trace, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        )
        return trace

    for index, surface_id in enumerate(selected, start=1):
        request = requests[surface_id]
        print(f"[{index}/{len(selected)}] {surface_id} probe", flush=True)
        draft_prompt = request["prompt"]
        if args.concept_first:
            concept_prompt = build_platform_native_concept_prompt(
                plan=plan, request=request
            )
            selected_concept: dict[str, str] | None = None
            concept_attempts: list[dict[str, Any]] = []
            prior_attempts = (
                prior_concept_trace["concepts_by_surface"].get(surface_id, [])
                if prior_concept_trace is not None
                else []
            )
            for prior in reversed(prior_attempts):
                prior_raw = str(prior.get("raw_output", ""))
                if not _concept_failures(
                    prior_raw, plan=plan, request=request
                ):
                    carried = dict(prior)
                    carried["source"] = "prior_private_concept_revalidated"
                    carried["concept_failures"] = []
                    concept_attempts = [carried]
                    selected_concept = _parse_concept(prior_raw)
                    carried_concept_count += 1
                    print(
                        f"[{index}/{len(selected)}] {surface_id} carry revalidated concept",
                        flush=True,
                    )
                    break
            if selected_concept is None:
                concept_first = RUNNER._generate(
                    model,
                    tokenizer,
                    concept_prompt,
                    seed=20265003 + index,
                )
                concept_first["source"] = "private_concept_probe"
                concept_attempts = [concept_first]
                concept_errors = _concept_failures(
                    concept_first["raw_output"], plan=plan, request=request
                )
                if not concept_errors:
                    selected_concept = _parse_concept(concept_first["raw_output"])
                else:
                    print(
                        f"[{index}/{len(selected)}] {surface_id} concept repair: {' | '.join(concept_errors)}",
                        flush=True,
                    )
                    concept_second = RUNNER._generate(
                        model,
                        tokenizer,
                        _concept_repair_prompt(concept_prompt, concept_errors),
                        seed=20266003 + index,
                    )
                    concept_second["source"] = "private_concept_probe_repair"
                    concept_attempts.append(concept_second)
                    second_errors = _concept_failures(
                        concept_second["raw_output"], plan=plan, request=request
                    )
                    if not second_errors:
                        selected_concept = _parse_concept(concept_second["raw_output"])
            for attempt in concept_attempts:
                attempt["concept_failures"] = list(
                    _concept_failures(
                        attempt["raw_output"], plan=plan, request=request
                    )
                )
            concepts_by_surface[surface_id] = concept_attempts
            if selected_concept is None:
                print(
                    f"[{index}/{len(selected)}] {surface_id} concept blocked before rendering",
                    flush=True,
                )
                attempts_by_surface[surface_id] = []
                checkpoint()
                continue
            draft_prompt = build_concept_anchored_draft_prompt(
                plan=plan,
                request=request,
                concept=selected_concept,
            )
        first = RUNNER._generate(
            model, tokenizer, draft_prompt, seed=20263003 + index
        )
        first["source"] = "selected_surface_probe"
        attempts = [first]
        current = first
        for repair_round in range(1, args.max_repair_rounds + 1):
            failures = RUNNER._failures(
                current["raw_output"], plan=plan, request=request
            )
            if not failures:
                break
            print(
                f"[{index}/{len(selected)}] {surface_id} repair {repair_round}: {' | '.join(failures)}",
                flush=True,
            )
            repaired = RUNNER._generate(
                model,
                tokenizer,
                RUNNER._repair_prompt(
                    draft_prompt, current["raw_output"], failures
                ),
                seed=20264003 + (repair_round - 1) * 1_000 + index,
            )
            repaired["source"] = f"selected_surface_probe_repair_{repair_round}"
            attempts.append(repaired)
            current = repaired
        attempts_by_surface[surface_id] = attempts
        checkpoint()
    trace = checkpoint()
    audit = compile_platform_generation_trace_audit(plan=plan, trace=trace)
    args.audit_output.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(
        args.audit_output,
        json.dumps(audit, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
    )
    selected_rows = [row for row in audit["rows"] if row["surface_id"] in selected]
    selected_pass_count = sum(row["pre_human_quality_pass"] for row in selected_rows)
    print(
        json.dumps(
            {
                "selected_surface_count": len(selected),
                "selected_pre_human_quality_pass_count": selected_pass_count,
                "concept_first": args.concept_first,
                "concept_pass_count": sum(
                    bool(attempts)
                    and not attempts[-1].get("concept_failures")
                    for attempts in concepts_by_surface.values()
                ),
                "carried_concept_count": carried_concept_count,
                "max_repair_rounds": args.max_repair_rounds,
                "trace_output": str(args.trace_output),
                "audit_output": str(args.audit_output),
                "network_download_performed": False,
                "cloud_api_calls": 0,
                "human_craft_review_completed_count": 0,
                "production_effect_observed": False,
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0 if selected_pass_count == len(selected) else 2


if __name__ == "__main__":
    raise SystemExit(main())
