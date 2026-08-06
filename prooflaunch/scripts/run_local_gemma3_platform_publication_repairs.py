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
from prooflaunch_remix.gtm_platform_native_challenger import (  # noqa: E402
    CREATIVE_FIELDS,
    adapt_platform_native_candidate,
    candidate_failures,
    compile_platform_native_receipt,
    extract_first_json_object,
    verify_platform_native_challenger_plan,
    verify_platform_native_receipt,
)
from prooflaunch_remix.gtm_platform_native_publication_audit import (  # noqa: E402
    compile_platform_native_publication_audit,
    publication_failures,
)


RUNNER_PATH = ROOT / "scripts/run_local_gemma3_platform_native_challenger.py"
SPEC = importlib.util.spec_from_file_location("prooflaunch_platform_runner", RUNNER_PATH)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError("failed to load the platform-native local runner")
RUNNER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(RUNNER)


def _inside_project(value: str) -> Path:
    path = Path(value).expanduser().resolve()
    try:
        path.relative_to(ROOT.resolve())
    except ValueError as error:
        raise argparse.ArgumentTypeError("path must remain inside the project root") from error
    return path


def _creative_only(candidate: dict[str, Any]) -> dict[str, Any]:
    return {field: candidate[field] for field in CREATIVE_FIELDS}


def _failures(
    raw: str,
    *,
    plan: dict[str, Any],
    request: dict[str, Any],
) -> tuple[str, ...]:
    try:
        candidate = adapt_platform_native_candidate(
            extract_first_json_object(raw), plan=plan, request=request
        )
        base = candidate_failures(candidate, plan=plan, request=request)
        if base:
            return base
        return publication_failures(candidate, plan=plan, request=request)
    except Exception as error:
        return (str(error),)


def _repair_prompt(
    *,
    plan: dict[str, Any],
    request: dict[str, Any],
    candidate: dict[str, Any],
    failures: tuple[str, ...],
) -> str:
    return (
        request["prompt"]
        + "\n\nDIRECT-PUBLICATION REPAIR. Rewrite the complete JSON from scratch and fix exactly these blocking defects:\n- "
        + "\n- ".join(failures)
        + "\nHard repair rules: reference no placeholder, hypothetical URL, bracketed link or asset that is not supplied; "
        "do not ask the reader to download, request access or tap an unavailable destination; use the frozen offer as the CTA; "
        "include the exact approved claim once in proof_integration and do not repeat or paraphrase it as a second proof; "
        "never use these outcome verbs anywhere outside the exact approved claim: eliminate, eliminates, ensure, ensures, "
        "increase, increases, improve, improves, reduce, reduces, accelerate, accelerates, boost, boosts, solve, solves, "
        "prevent, prevents, guarantee, guarantees; do not put them in questions, hypotheses, body, progression, CTA, "
        "participation or falsifier; set proof_integration to the exact approved claim and nothing else; "
        "the complete approved-claim sentence may appear only in proof_integration: never copy or paraphrase that sentence "
        "in campaign_platform, hook, progression, body, CTA or participation_mechanism; "
        "progression must be a JSON array of exactly four plain strings, never objects; body must be a JSON array of three "
        "to seven plain strings, never one string; no progression item may repeat proof_integration; "
        "make the post complete in itself without a link, image, diagram, worksheet, diagnostic, assessment, case study, "
        "sample brief, live brief, screen recording, demo, diagnostic, submit-a-brief flow, promised response, company metric, "
        "claimed user result, file or destination; use only the frozen problem, "
        "product truth, approved claim and offer as factual product content; invent no customer, company, asset or result; "
        "for Reddit, disclose affiliation plainly with 'We built ProofLaunch Cortex-X' before product relevance. "
        "The prior candidate is intentionally omitted so its defects cannot be copied. Return only the complete repaired JSON."
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Repair only direct-publication blockers in the thirteen-surface B2B challenger."
    )
    parser.add_argument("--model-path", required=True)
    parser.add_argument("--plan", required=True, type=_inside_project)
    parser.add_argument("--source-receipt", required=True, type=_inside_project)
    parser.add_argument("--b2c-plan", required=True, type=_inside_project)
    parser.add_argument("--b2c-receipt", required=True, type=_inside_project)
    parser.add_argument("--output", required=True, type=_inside_project)
    parser.add_argument("--audit-output", required=True, type=_inside_project)
    parser.add_argument(
        "--resume-trace",
        type=_inside_project,
        help="Resume from a private trace and call the model only for surfaces that still fail.",
    )
    args = parser.parse_args()
    plan = json.loads(args.plan.read_text(encoding="utf-8"))
    source_receipt = json.loads(args.source_receipt.read_text(encoding="utf-8"))
    b2c_plan = json.loads(args.b2c_plan.read_text(encoding="utf-8"))
    b2c_receipt = json.loads(args.b2c_receipt.read_text(encoding="utf-8"))
    verify_platform_native_challenger_plan(plan)
    verify_platform_native_receipt(source_receipt, plan=plan)
    verify_platform_native_challenger_plan(b2c_plan)
    verify_platform_native_receipt(b2c_receipt, plan=b2c_plan)
    if plan.get("business_model") != "b2b":
        raise SystemExit("publication repair currently admits only the real B2B product brief")
    requests = {row["surface_id"]: row for row in plan["requests"]}
    candidates = {row["surface_id"]: row for row in source_receipt["accepted_candidates"]}
    revision, manifest_sha256 = RUNNER._model_manifest(
        Path(args.model_path).expanduser().resolve(strict=True)
    )
    attempts: dict[str, list[dict[str, Any]]] = {}
    if args.resume_trace:
        trace = json.loads(args.resume_trace.read_text(encoding="utf-8"))
        unsigned_trace = dict(trace)
        supplied_trace_sha256 = unsigned_trace.pop("content_sha256", None)
        expected_trace_sha256 = hashlib.sha256(
            RUNNER._canonical(unsigned_trace).encode("utf-8")
        ).hexdigest()
        if supplied_trace_sha256 != expected_trace_sha256:
            raise SystemExit("resume trace digest is invalid")
        expected_bindings = {
            "schema": "ProofLaunchPlatformPublicationRepairPrivateTraceV1",
            "plan_sha256": plan["content_sha256"],
            "source_receipt_sha256": source_receipt["content_sha256"],
            "model_revision": revision,
            "model_manifest_sha256": manifest_sha256,
        }
        for field, expected in expected_bindings.items():
            if trace.get(field) != expected:
                raise SystemExit(f"resume trace {field} binding is invalid")
        raw_attempts = trace.get("attempts_by_surface")
        if not isinstance(raw_attempts, dict) or not set(raw_attempts).issubset(requests):
            raise SystemExit("resume trace surface coverage is invalid")
        attempts = {
            str(surface_id): list(surface_attempts)
            for surface_id, surface_attempts in raw_attempts.items()
        }
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
    model, tokenizer = load(str(Path(args.model_path).expanduser().resolve()), lazy=False)
    model_load_seconds = time.monotonic() - load_started
    repaired_surface_count = 0
    trace_path = args.output.with_name(args.output.stem + ".private-trace.json")

    def checkpoint_trace() -> None:
        trace = {
            "schema": "ProofLaunchPlatformPublicationRepairPrivateTraceV1",
            "plan_sha256": plan["content_sha256"],
            "source_receipt_sha256": source_receipt["content_sha256"],
            "model_revision": revision,
            "model_manifest_sha256": manifest_sha256,
            "attempts_by_surface": attempts,
            "completed_surface_count": len(attempts),
            "contains_secrets": False,
            "external_publish_executed": False,
        }
        trace["content_sha256"] = hashlib.sha256(
            RUNNER._canonical(trace).encode("utf-8")
        ).hexdigest()
        trace_path.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_text(
            trace_path,
            json.dumps(trace, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        )

    for index, request in enumerate(plan["requests"], start=1):
        surface_id = request["surface_id"]
        candidate = candidates[surface_id]
        prior_attempts = list(attempts.get(surface_id, ()))
        if prior_attempts:
            prior_raw = str(prior_attempts[-1].get("raw_output", ""))
            failures = _failures(prior_raw, plan=plan, request=request)
            try:
                candidate = adapt_platform_native_candidate(
                    extract_first_json_object(prior_raw), plan=plan, request=request
                )
            except Exception:
                candidate = candidates[surface_id]
        else:
            failures = publication_failures(candidate, plan=plan, request=request)
        if not failures:
            print(f"[{index}/13] {surface_id} carry publication-ready candidate", flush=True)
            if not prior_attempts:
                attempts[surface_id] = [
                    {
                        "raw_output": json.dumps(_creative_only(candidate), ensure_ascii=False),
                        "source": "prior_candidate_revalidated_publication_ready",
                        "elapsed_seconds": 0.0,
                        "generated_token_count": 0,
                    }
                ]
            checkpoint_trace()
            continue
        repaired_surface_count += 1
        print(f"[{index}/13] {surface_id} repair: {' | '.join(failures)}", flush=True)
        prompt = _repair_prompt(
            plan=plan,
            request=request,
            candidate=candidate,
            failures=failures,
        )
        first = RUNNER._generate(
            model, tokenizer, prompt, seed=20261003 + index
        )
        first["source"] = "publication_repair"
        surface_attempts = prior_attempts + [first]
        remaining = _failures(first["raw_output"], plan=plan, request=request)
        if remaining:
            second_prompt = (
                prompt
                + "\n\nThe repaired draft still failed for exactly these reasons:\n- "
                + "\n- ".join(remaining)
                + "\nRewrite the complete JSON again. Do not explain. FAILED_REPAIR="
                + first["raw_output"][:8_000]
            )
            second = RUNNER._generate(
                model, tokenizer, second_prompt, seed=20261103 + index
            )
            second["source"] = "bounded_publication_repair_retry"
            surface_attempts.append(second)
        attempts[surface_id] = surface_attempts
        checkpoint_trace()
    receipt_attempts = {
        surface_id: surface_attempts[-1:]
        for surface_id, surface_attempts in attempts.items()
    }
    receipt = compile_platform_native_receipt(
        plan=plan,
        model={
            "provider": "mlx_local_publication_repair",
            "device_family": "Apple Metal",
            "model_id": RUNNER.MODEL_ID,
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
    if receipt["accepted_surface_count"] != 13:
        print(
            json.dumps(
                {
                    "output": str(args.output),
                    "private_trace_output": str(trace_path),
                    "repaired_surface_count": repaired_surface_count,
                    "accepted_surface_count": receipt["accepted_surface_count"],
                    "strict_audit_compiled": False,
                    "human_review_completed": False,
                },
                ensure_ascii=False,
                sort_keys=True,
            )
        )
        return 2
    strict_audit = compile_platform_native_publication_audit(
        ((plan, receipt), (b2c_plan, b2c_receipt))
    )
    args.audit_output.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(
        args.audit_output,
        json.dumps(strict_audit, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
    )
    b2b_ready = sum(
        row["mechanical_publication_ready"]
        for row in strict_audit["rows"]
        if row["business_model"] == "b2b"
    )
    print(
        json.dumps(
            {
                "output": str(args.output),
                "audit_output": str(args.audit_output),
                "repaired_surface_count": repaired_surface_count,
                "accepted_surface_count": receipt["accepted_surface_count"],
                "b2b_mechanically_publication_ready_count": b2b_ready,
                "human_review_completed": False,
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0 if b2b_ready == 13 else 2


if __name__ == "__main__":
    raise SystemExit(main())
