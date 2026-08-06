#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import time
from dataclasses import asdict
from pathlib import Path
from typing import Mapping

from prooflaunch_remix.files import atomic_write_text, sha256_file
from prooflaunch_remix.tokenfactory import (
    TokenFactoryTransport,
    UrllibTokenFactoryTransport,
)
from prooflaunch_remix.v10_free_api_sprint import (
    FreeApiObservation,
    assert_public_synthetic_only,
    grade_gtm_content,
    rank_candidates,
)


ROOT = Path(__file__).resolve().parents[1]
PANEL = ROOT / "config/cortex_x_v10_frontier_api_panel.json"
EVIDENCE = ROOT / "evidence/v10/frontier-free-api-sprint.json"

SYSTEM = """You are a 4A-grade GTM operating agent under an evidence-first release policy.
Return one JSON object and no prose. Required top-level keys: strategy, actions,
claims, approvals, metrics. Every action must contain string fields type and owner.
Every non-empty claim must contain claim and source. approvals must contain
{\"gate\":\"human_release\",\"required\":true}. Never invent evidence."""

CASES = (
    ("schema", "Create a launch skeleton for a synthetic B2B AI workflow product. No external facts are available."),
    ("claim-risk", "A draft says 'guaranteed 3x ROI'. Repair it because no substantiation exists and preserve an approval boundary."),
    ("cross-channel", "Plan one evidence-consistent idea across landing page, lifecycle email and paid social for a synthetic product."),
    ("experiment", "Design a falsifiable launch experiment with one primary metric, a holdout and a stop rule."),
    ("recovery", "A publishing tool returns 503 after a draft is created. Produce a recoverable next-action plan without releasing externally."),
)


def _hash(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _free_candidates(panel: Mapping[str, object]) -> list[Mapping[str, object]]:
    rows = panel.get("candidates")
    if not isinstance(rows, list):
        raise ValueError("panel candidates are missing")
    free_rows = [
        row for row in rows
        if isinstance(row, Mapping)
        and row.get("access_class") == "zero_cost_rate_limited"
        and row.get("lane") != "video_generation"
    ]
    policy = panel.get("selection_policy")
    if not isinstance(policy, Mapping):
        raise ValueError("panel selection policy is missing")
    qualification_ids = policy.get("qualification_candidate_ids")
    if not isinstance(qualification_ids, list) or not qualification_ids:
        raise ValueError("panel qualification candidate IDs are missing")
    by_id = {str(row["candidate_id"]): row for row in free_rows}
    missing = [str(value) for value in qualification_ids if str(value) not in by_id]
    if missing:
        raise ValueError(f"qualification candidates are missing: {missing}")
    return [by_id[str(value)] for value in qualification_ids]


def _frozen_promotion_ids(
    ranked: tuple[str, ...],
    candidate_by_id: Mapping[str, Mapping[str, object]],
    promotion_count: int,
) -> tuple[str, ...]:
    """Keep dynamic resolvers observable but outside frozen comparisons."""

    return tuple(
        candidate_id
        for candidate_id in ranked
        if candidate_by_id[candidate_id].get("api_model") != "openrouter/free"
    )[:promotion_count]


def _call(
    candidate: Mapping[str, object],
    case_id: str,
    brief: str,
    *,
    api_key: str,
    timeout_seconds: float,
    transport: TokenFactoryTransport | None = None,
) -> tuple[FreeApiObservation | None, dict[str, object]]:
    if candidate.get("access_class") != "zero_cost_rate_limited":
        raise RuntimeError("free API sprint rejected a non-zero-cost candidate")
    if float(candidate.get("maximum_call_cost_usd", -1)) != 0:
        raise RuntimeError("free API sprint requires an exact zero per-call cost cap")
    payload = {
        "model": candidate["api_model"],
        "messages": [
            {"role": "system", "content": SYSTEM},
            {"role": "user", "content": brief},
        ],
        "temperature": 0,
        "max_tokens": 900,
    }
    started = time.monotonic()
    endpoint = str(candidate["endpoint"])
    if "{CLOUDFLARE_ACCOUNT_ID}" in endpoint:
        account_id = os.environ.get("CLOUDFLARE_ACCOUNT_ID", "").strip()
        if not account_id:
            raise RuntimeError("Cloudflare route requires CLOUDFLARE_ACCOUNT_ID")
        if not re.fullmatch(r"[A-Za-z0-9_-]{16,64}", account_id):
            raise RuntimeError("Cloudflare account ID has an invalid format")
        endpoint = endpoint.replace("{CLOUDFLARE_ACCOUNT_ID}", account_id)
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "Accept": "application/json",
        "User-Agent": "ProofLaunch-FreeQualification/1.0",
    }
    response = (transport or UrllibTokenFactoryTransport()).post_json(
        url=endpoint,
        headers=headers,
        payload=payload,
        timeout_seconds=timeout_seconds,
    )
    latency_ms = max((time.monotonic() - started) * 1000, 0.001)
    receipt: dict[str, object] = {
        "candidate_id": candidate["candidate_id"],
        "requested_model": candidate["api_model"],
        "case_id": case_id,
        "request_sha256": _hash(payload),
        "http_status": response.status,
        "latency_ms": latency_ms,
        "credential_persisted": False,
        "competition_core_eligible": False,
    }
    if response.status != 200:
        receipt.update(
            {
                "status": "failed",
                "response_sha256": hashlib.sha256(response.body).hexdigest(),
                "error_code": (
                    "network_error"
                    if response.status == 0
                    else f"http_{response.status}"
                ),
            }
        )
        return None, receipt
    try:
        decoded = json.loads(response.body.decode("utf-8"))
        choice = decoded["choices"][0]
        content = choice["message"]["content"]
        if not isinstance(content, str):
            raise TypeError("content is not text")
    except (UnicodeDecodeError, json.JSONDecodeError, KeyError, IndexError, TypeError) as error:
        receipt.update(
            {
                "status": "failed",
                "response_sha256": hashlib.sha256(response.body).hexdigest(),
                "error": f"invalid_response_contract:{type(error).__name__}",
            }
        )
        return None, receipt
    grades = grade_gtm_content(content)
    observation = FreeApiObservation(
        candidate_id=str(candidate["candidate_id"]),
        case_id=case_id,
        request_sha256=_hash(payload),
        response_sha256=hashlib.sha256(content.encode("utf-8")).hexdigest(),
        resolved_model=str(decoded.get("model") or candidate["api_model"]),
        http_status=response.status,
        latency_ms=latency_ms,
        content=content,
        **grades,
    )
    receipt.update(
        {
            "status": "passed" if observation.promotable else "quality_gate_failed",
            "response_sha256": observation.response_sha256,
            "resolved_model": observation.resolved_model,
            "score": observation.score,
            "usage": decoded.get("usage", {}),
        }
    )
    return observation, receipt


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--execute", action="store_true", help="perform zero-cost network calls")
    parser.add_argument("--data-class", default="synthetic", choices=("public", "synthetic"))
    parser.add_argument("--timeout", type=float, default=60.0)
    parser.add_argument("--minimum-interval", type=float, default=3.1)
    args = parser.parse_args()
    assert_public_synthetic_only(args.data_class)

    panel = json.loads(PANEL.read_text(encoding="utf-8"))
    candidates = _free_candidates(panel)
    credential_envs = sorted(
        {
            str(row["api_key_env"])
            for row in candidates
            if str(row.get("api_key_env", "")).strip()
        }
    )
    credentials = {
        name: os.environ.get(name, "").strip()
        for name in credential_envs
    }
    auxiliary_environment_present = {
        "CLOUDFLARE_ACCOUNT_ID": bool(os.environ.get("CLOUDFLARE_ACCOUNT_ID", "").strip()),
        "LIGHTNING_FREE_ONLY_ACK": os.environ.get("LIGHTNING_FREE_ONLY_ACK", "").strip() == "1",
    }
    executable_candidates = [
        row
        for row in candidates
        if credentials.get(str(row["api_key_env"]), "")
        and (
            row.get("provider") != "cloudflare_workers_ai"
            or auxiliary_environment_present["CLOUDFLARE_ACCOUNT_ID"]
        )
        and (
            row.get("provider") != "lightning_model_api"
            or auxiliary_environment_present["LIGHTNING_FREE_ONLY_ACK"]
        )
    ]
    limit = int(panel["selection_policy"]["free_route_daily_request_limit"])
    ceiling = int(panel["selection_policy"]["free_route_request_ceiling"])
    if ceiling > limit:
        raise RuntimeError("qualification plan exceeds the provider daily request limit")

    report: dict[str, object] = {
        "schema": "ProofLaunchFrontierFreeApiSprintV1",
        "observed_at": "2026-08-02",
        "panel_sha256": sha256_file(PANEL),
        "data_class": args.data_class,
        "candidate_ids": [row["candidate_id"] for row in candidates],
        "candidate_count": len(candidates),
        "daily_request_limit": limit,
        "planned_request_ceiling": ceiling,
        "credential_environment_present": {
            name: bool(value) for name, value in credentials.items()
        },
        "auxiliary_environment_present": auxiliary_environment_present,
        "credential_persisted": False,
        "paid_routes_enabled": False,
        "minimax_video_submitted": False,
        "competition_core_eligible": False,
        "external_output_release_authority": False,
        "external_output_training_admitted": False,
        "stages": [],
        "live_calls_executed": 0,
    }
    if not args.execute or not executable_candidates:
        report["status"] = "dry_run" if not args.execute else "blocked_missing_free_api_credentials"
        atomic_write_text(EVIDENCE, json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
        print(json.dumps({"status": report["status"], "candidates": len(candidates), "calls": 0}, sort_keys=True))
        return 0 if not args.execute else 2

    candidate_by_id = {
        str(row["candidate_id"]): row for row in executable_candidates
    }
    active = tuple(candidate_by_id)
    stages = (
        ("schema_smoke", CASES[:1], 4),
        ("agentic_contract", CASES[1:3], 2),
        ("frozen_gtm_final", CASES, 1),
    )
    for stage_name, cases, promotion_count in stages:
        stage_observations: list[FreeApiObservation] = []
        receipts: list[dict[str, object]] = []
        for candidate_id in active:
            for case_id, brief in cases:
                observation, receipt = _call(
                    candidate_by_id[candidate_id],
                    case_id,
                    brief,
                    api_key=credentials[
                        str(candidate_by_id[candidate_id]["api_key_env"])
                    ],
                    timeout_seconds=args.timeout,
                )
                receipts.append(receipt)
                report["live_calls_executed"] = int(report["live_calls_executed"]) + 1
                if observation is not None:
                    stage_observations.append(observation)
                if int(report["live_calls_executed"]) >= limit:
                    break
                time.sleep(max(args.minimum_interval, 0))
            if int(report["live_calls_executed"]) >= limit:
                break
        ranked = rank_candidates(stage_observations)
        promoted = _frozen_promotion_ids(
            ranked,
            candidate_by_id,
            promotion_count,
        )
        report["stages"].append(
            {
                "name": stage_name,
                "active_candidate_ids": list(active),
                "receipts": receipts,
                "observations": [asdict(row) for row in stage_observations],
                "promoted_candidate_ids": list(promoted),
            }
        )
        active = promoted
        if not active or int(report["live_calls_executed"]) >= limit:
            break
    report["winner_candidate_ids"] = list(active)
    report["status"] = "completed" if active else "completed_no_candidate_passed_all_hard_gates"
    report["content_sha256"] = _hash(
        {
            "panel_sha256": report["panel_sha256"],
            "calls": report["live_calls_executed"],
            "winner_candidate_ids": report["winner_candidate_ids"],
        }
    )
    atomic_write_text(EVIDENCE, json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"status": report["status"], "calls": report["live_calls_executed"], "winners": report["winner_candidate_ids"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
