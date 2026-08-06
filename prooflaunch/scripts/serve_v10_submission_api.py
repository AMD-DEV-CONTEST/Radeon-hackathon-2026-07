#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import secrets
from pathlib import Path

from prooflaunch_remix.gtm_blind_review_service import BlindReviewService
from prooflaunch_remix.gtm_portfolio_blind_review_service import (
    PortfolioBlindReviewService,
)
from prooflaunch_remix.gtm_judge_calibration import JudgeCalibrationService
from prooflaunch_remix.campaign_pack_blind_review import (
    CampaignPackBlindReviewService,
)
from prooflaunch_remix.v10_submission_production_api import make_production_server
from prooflaunch_remix.v10_submission_runtime import AgencyRunWorker, ProductionAgencyService
from prooflaunch_remix.v10_submission_store import SubmissionStore


ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--state-root", default=str(ROOT / ".prooflaunch-runtime"))
    parser.add_argument("--approver-identity", default="local-human-operator")
    parser.add_argument("--approval-token", default=None)
    parser.add_argument("--tenant-id", default="org-local")
    parser.add_argument("--tenant-token", default=None)
    parser.add_argument("--memory-capsule-secret", default=None)
    parser.add_argument(
        "--enable-local-evaluation-session",
        action="store_true",
        help="Expose the ephemeral tenant session to this loopback UI only; disabled by default.",
    )
    parser.add_argument(
        "--blind-review-root",
        default=str(
            ROOT
            / "artifacts/aug3-gtm-employee-mission-v14/local-text-challenger"
        ),
    )
    parser.add_argument(
        "--reviewer-token-file",
        default=str(ROOT / ".prooflaunch-secrets/blind-review-invitations.json"),
    )
    parser.add_argument(
        "--portfolio-blind-review-root",
        default=str(
            ROOT
            / "artifacts/local-gtm-creative-benchmark-v11/portfolio-blind-review-v2"
        ),
    )
    parser.add_argument(
        "--judge-calibration-root",
        default=str(ROOT / ".prooflaunch-runtime/judge-calibration"),
    )
    parser.add_argument(
        "--campaign-pack-blind-review-root",
        default=str(ROOT / "artifacts/campaign-pack-visual-blind-review-v1"),
    )
    args = parser.parse_args()
    approval_token = (
        args.approval_token
        or os.environ.get("PROOFLAUNCH_APPROVAL_TOKEN")
        or secrets.token_urlsafe(32)
    )
    tenant_tokens_payload = os.environ.get("PROOFLAUNCH_TENANT_TOKENS_JSON")
    generated_tenant_token = False
    if tenant_tokens_payload is not None:
        try:
            tenant_tokens_raw = json.loads(tenant_tokens_payload)
        except json.JSONDecodeError as error:
            raise SystemExit(
                "PROOFLAUNCH_TENANT_TOKENS_JSON must be valid JSON"
            ) from error
        if not isinstance(tenant_tokens_raw, dict):
            raise SystemExit(
                "PROOFLAUNCH_TENANT_TOKENS_JSON must map tenant IDs to bearer tokens"
            )
        tenant_tokens = {
            str(tenant_id): str(token)
            for tenant_id, token in tenant_tokens_raw.items()
        }
    else:
        tenant_token = (
            args.tenant_token
            or os.environ.get("PROOFLAUNCH_TENANT_TOKEN")
            or secrets.token_urlsafe(32)
        )
        generated_tenant_token = (
            args.tenant_token is None
            and "PROOFLAUNCH_TENANT_TOKEN" not in os.environ
        )
        tenant_tokens = {args.tenant_id: tenant_token}
    configured_capsule_secret = (
        args.memory_capsule_secret
        or os.environ.get("PROOFLAUNCH_MEMORY_CAPSULE_SECRET")
    )
    memory_capsule_secret = (
        configured_capsule_secret.encode("utf-8")
        if configured_capsule_secret is not None
        else secrets.token_bytes(32)
    )
    if len(memory_capsule_secret) < 32:
        raise SystemExit("memory capsule secret must contain at least 32 UTF-8 bytes")
    store = SubmissionStore(Path(args.state_root).expanduser().resolve())
    worker = AgencyRunWorker(store)
    service = ProductionAgencyService(store, worker=worker)
    blind_review_root = Path(args.blind_review_root).expanduser().resolve()
    reviewer_token_file = Path(args.reviewer_token_file).expanduser().resolve()
    reviewer_token_payload = os.environ.get("PROOFLAUNCH_REVIEWER_TOKENS_JSON")
    if reviewer_token_payload is None and reviewer_token_file.is_file():
        if reviewer_token_file.is_symlink() or reviewer_token_file.stat().st_mode & 0o077:
            raise SystemExit(
                "reviewer token file must be a real file readable only by its owner (mode 0600)"
            )
        reviewer_token_payload = reviewer_token_file.read_text(encoding="utf-8")
    if reviewer_token_payload is None:
        reviewer_token_payload = "{}"
    try:
        reviewer_tokens_raw = json.loads(reviewer_token_payload)
    except json.JSONDecodeError as error:
        raise SystemExit("PROOFLAUNCH_REVIEWER_TOKENS_JSON must be valid JSON") from error
    if not isinstance(reviewer_tokens_raw, dict):
        raise SystemExit("PROOFLAUNCH_REVIEWER_TOKENS_JSON must be a JSON object")
    try:
        reviewer_tokens = {
            int(slot): str(token) for slot, token in reviewer_tokens_raw.items()
        }
    except (TypeError, ValueError) as error:
        raise SystemExit("reviewer invitation slots must be integers 1 through 5") from error
    blind_review_service = (
        BlindReviewService(
            blind_review_root,
            reviewer_tokens=reviewer_tokens,
            execution_bindings_path=ROOT / "config/comfyui_execution_bindings_v1.json",
            gpu_handoff_path=ROOT / "artifacts/comfyui-gpu-handoff-20260801/handoff.json",
            multimodal_compilation_path=(
                ROOT
                / "artifacts/aug3-gtm-employee-mission-v14/multimodal-seed-compilation.json"
            ),
        )
        if blind_review_root.is_dir()
        else None
    )
    portfolio_blind_review_root = (
        Path(args.portfolio_blind_review_root).expanduser().resolve()
    )
    portfolio_blind_review_service = (
        PortfolioBlindReviewService(
            portfolio_blind_review_root,
            reviewer_tokens=reviewer_tokens,
        )
        if portfolio_blind_review_root.is_dir()
        else None
    )
    judge_calibration_root = Path(args.judge_calibration_root).expanduser().resolve()
    judge_calibration_service = (
        JudgeCalibrationService(
            judge_calibration_root,
            reviewer_tokens=reviewer_tokens,
        )
        if judge_calibration_root.is_dir()
        else None
    )
    campaign_pack_blind_review_root = (
        Path(args.campaign_pack_blind_review_root).expanduser().resolve()
    )
    campaign_pack_blind_review_service = (
        CampaignPackBlindReviewService(
            campaign_pack_blind_review_root,
            project_root=ROOT,
            reviewer_tokens=reviewer_tokens,
        )
        if campaign_pack_blind_review_root.is_dir()
        else None
    )
    server = make_production_server(
        args.host,
        args.port,
        service=service,
        web_root=ROOT / "web",
        approval_token=approval_token,
        approver_identity=args.approver_identity,
        tenant_tokens=tenant_tokens,
        memory_capsule_secret=memory_capsule_secret,
        blind_review_service=blind_review_service,
        portfolio_blind_review_service=portfolio_blind_review_service,
        judge_calibration_service=judge_calibration_service,
        campaign_pack_blind_review_service=campaign_pack_blind_review_service,
        local_evaluation_session=(
            (args.tenant_id, tenant_tokens[args.tenant_id])
            if args.enable_local_evaluation_session and args.tenant_id in tenant_tokens
            else None
        ),
    )
    worker.start()
    print(f"ProofLaunch production Agent API: http://{args.host}:{server.server_port}")
    print(f"State root: {store.root}")
    if not args.approval_token and "PROOFLAUNCH_APPROVAL_TOKEN" not in os.environ:
        print(f"One-session approval token: {approval_token}")
    else:
        print("Approval token: configured externally (not echoed)")
    if generated_tenant_token:
        print(
            "One-session tenant bearer token for "
            f"{args.tenant_id}: {tenant_tokens[args.tenant_id]}"
        )
    else:
        print(
            "Tenant bearer tokens: configured externally for "
            f"{len(tenant_tokens)} tenant(s) (not echoed)"
        )
    print(
        "Local browser evaluation session: "
        + ("enabled on loopback" if args.enable_local_evaluation_session else "disabled")
    )
    print(
        "Portable memory signing: "
        + (
            "configured externally (not echoed)"
            if configured_capsule_secret is not None
            else "ephemeral for this server session; configure PROOFLAUNCH_MEMORY_CAPSULE_SECRET for cross-device use"
        )
    )
    if blind_review_service is None:
        print("Blind review service: unavailable (bundle root not found)")
    else:
        print(
            "Blind review service: ready; reviewer invitations configured for "
            f"{blind_review_service.status()['configured_reviewer_slot_count']}/5 slots"
        )
    if portfolio_blind_review_service is None:
        print("Portfolio blind review service: unavailable (bundle root not found)")
    else:
        portfolio_status = portfolio_blind_review_service.status()
        print(
            "Portfolio blind review service: ready; "
            f"{portfolio_status['submitted_review_count']}/"
            f"{portfolio_status['expected_review_count']} reviews submitted"
        )
    if judge_calibration_service is None:
        print("Judge calibration service: unavailable (real calibration bundle root not found)")
    else:
        calibration_status = judge_calibration_service.status()
        print(
            "Judge calibration service: ready; "
            f"{calibration_status['submitted_review_count']}/"
            f"{calibration_status['expected_review_count']} labels submitted; "
            f"judge_calibrated={str(calibration_status['judge_calibrated']).lower()}"
        )
    if campaign_pack_blind_review_service is None:
        print(
            "Campaign-pack blind review service: unavailable "
            "(identity-hidden visual review bundle root not found)"
        )
    else:
        campaign_status = campaign_pack_blind_review_service.status()
        print(
            "Campaign-pack blind review service: ready; "
            f"{campaign_status['submitted_review_count']}/"
            f"{campaign_status['expected_review_count']} reviews submitted; "
            "automatic publish/switch disabled"
        )
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        worker.stop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
