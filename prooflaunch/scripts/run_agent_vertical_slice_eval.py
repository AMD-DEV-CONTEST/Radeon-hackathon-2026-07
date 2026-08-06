from __future__ import annotations

import argparse
import hashlib
import json
import zipfile
from collections import Counter
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw

from prooflaunch_remix.audience_pulse import LexicalAudiencePulse
from prooflaunch_remix.contracts import (
    AuditFinding,
    CampaignRequest,
    ReleaseApproval,
    ReleaseApprovalKind,
    ReleaseDecision,
    Severity,
    Stage,
)
from prooflaunch_remix.ledger import EvidenceLedger, canonical_json
from prooflaunch_remix.runtime import build_supervisor
from prooflaunch_remix.workflow import Supervisor, WorkflowBlocked


SCHEMA = "ProofLaunchAgentVerticalSliceEvalV1"
FIXED_APPROVAL_TIME = "2026-08-01T12:00:00+00:00"
SINGLETON_SUCCESS_EVENTS = (
    "run_started",
    "claims_extracted",
    "briefs_planned",
    "assets_created",
    "release_awaiting_approval",
    "release_approved",
    "campaign_delivered",
)
CANVAS_OVERRIDES = {
    "TikTok": (360, 640),
    "Instagram Reels": (360, 640),
    "YouTube Shorts": (360, 640),
    "Instagram": (360, 450),
    "LinkedIn": (420, 420),
    "X": (480, 270),
}
PREDECLARED_BAR = {
    "case_count": 10,
    "prepare_success_rate": 1.0,
    "release_success_rate": 1.0,
    "unapproved_export_attempts": 10,
    "unapproved_export_rejection_rate": 1.0,
    "unapproved_bundle_count": 0,
    "duplicate_successful_step_count": 0,
    "cases_over_two_repairs": 0,
    "failure_probe_pass_rate": 1.0,
    "all_ledgers_verified": True,
    "all_manifest_file_hashes_verified": True,
}


@dataclass(frozen=True)
class EvalCase:
    case_id: str
    product_name: str
    specification_text: str
    market: str
    platform: str
    goal: str
    target_emotion: str
    unsafe_first_pass: bool = False


CASES = (
    EvalCase(
        "case-01",
        "Aster Arc",
        "Battery life lasts up to 18 hours under the documented test.",
        "Japan",
        "TikTok",
        "launch",
        "joy",
        True,
    ),
    EvalCase(
        "case-02",
        "Nori Lamp",
        "The lamp uses 8 watts in standard brightness mode.",
        "United States",
        "Instagram",
        "consideration",
        "love",
    ),
    EvalCase(
        "case-03",
        "Kite",
        "Surface size is 120 by 60 centimeters.",
        "Germany",
        "LinkedIn",
        "product update",
        "surprise",
    ),
    EvalCase(
        "case-04",
        "Mora Lock",
        "The lock records the last 30 access events on the device.",
        "Canada",
        "YouTube Shorts",
        "education",
        "fear",
    ),
    EvalCase(
        "case-05",
        "Pico",
        "220 g.",
        "France",
        "X",
        "relaunch",
        "anger",
        True,
    ),
    EvalCase(
        "case-06",
        "Sol Cup",
        "The cup holds 350 milliliters when filled to the marked line.",
        "Brazil",
        "Instagram Reels",
        "awareness",
        "sadness",
    ),
    EvalCase(
        "case-07",
        "Vale",
        "Four USB-C ports are documented.",
        "United Kingdom",
        "LinkedIn",
        "launch",
        "joy",
    ),
    EvalCase(
        "case-08",
        "Echo Tag",
        "The tag enclosure is rated IP67 in the supplied specification.",
        "Singapore",
        "TikTok",
        "discovery",
        "surprise",
    ),
    EvalCase(
        "case-09",
        "Luma",
        "Three pressure presets are documented.",
        "Australia",
        "Instagram",
        "retention",
        "love",
        True,
    ),
    EvalCase(
        "case-10",
        "Rook Bell",
        "The bell reaches 85 decibels at the specified test distance.",
        "Mexico",
        "YouTube Shorts",
        "education",
        "fear",
    ),
)


RIGHTS_BASIS = {
    "status": "rights-clear synthetic fixture",
    "product_image": (
        "Programmatically drawn by this evaluation; no external image, logo, "
        "person, or protected product design is used."
    ),
    "copy": "Synthetic specification authored only for mechanical testing.",
    "third_party_content": False,
}


def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _bundle_exists(root: Path) -> bool:
    return any(
        (root / name).is_file()
        for name in ("campaign-pack.json", "campaign-pack.zip")
    )


def _read_ledger(path: Path) -> list[dict[str, Any]]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _duplicate_success_count(events: list[dict[str, Any]]) -> int:
    counts = Counter(str(event.get("kind", "")) for event in events)
    return sum(max(0, counts[kind] - 1) for kind in SINGLETON_SUCCESS_EVENTS)


def _make_product(path: Path, index: int) -> None:
    """Create an evaluation-owned synthetic RGBA product fixture."""

    palette = (
        (30, 92, 178, 255),
        (132, 64, 170, 255),
        (14, 132, 105, 255),
        (194, 92, 36, 255),
        (38, 125, 150, 255),
    )
    accent = palette[index % len(palette)]
    image = Image.new("RGBA", (120, 160), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle(
        (10, 6, 110, 154),
        radius=20,
        fill=(244, 247, 252, 255),
        outline=(155, 170, 195, 255),
        width=3,
    )
    draw.rounded_rectangle((28, 30, 92, 104), radius=10, fill=accent)
    draw.ellipse((44, 116, 76, 148), fill=(244, 178, 58, 255))
    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path, format="PNG", optimize=False)


def _request(case: EvalCase, product_path: Path) -> CampaignRequest:
    return CampaignRequest(
        product_name=case.product_name,
        product_image=str(product_path),
        specification_text=case.specification_text,
        market=case.market,
        platform=case.platform,
        goal=case.goal,
        target_emotion=case.target_emotion,
    )


def _supervisor(*, seed: int, unsafe_first_pass: bool = False) -> Supervisor:
    return build_supervisor(
        audience=LexicalAudiencePulse(),
        seed=seed,
        canvas_overrides=CANVAS_OVERRIDES,
        unsafe_first_pass=unsafe_first_pass,
    )


def _approval(
    state: Any,
    *,
    decision: ReleaseDecision = ReleaseDecision.APPROVE,
    suffix: str,
) -> ReleaseApproval:
    return ReleaseApproval.create(
        run_id=state.run_id,
        preview_digest=state.prepared_preview_digest or "",
        decision=decision,
        approver=f"agent-vertical-eval-fixture-{suffix}",
        reason=(
            "Explicit content-bound fixture decision for deterministic mechanical "
            "evaluation only; this is not a production human authorization."
        ),
        kind=ReleaseApprovalKind.FIXTURE,
        issued_at=FIXED_APPROVAL_TIME,
    )


def _verify_pack(state: Any, root: Path) -> dict[str, Any]:
    manifest_path = root / "campaign-pack.json"
    archive_path = root / "campaign-pack.zip"
    if not manifest_path.is_file() or not archive_path.is_file():
        return {
            "verified": False,
            "manifest_sha256": None,
            "archive_sha256": None,
            "release_files": [],
            "reason": "campaign pack is incomplete",
        }

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    expected: dict[tuple[str, str], dict[str, Any]] = {
        (str(item["asset_id"]), str(item["role"])): item
        for item in manifest.get("files", [])
    }
    live_hashes: dict[tuple[str, str], str] = {}
    for asset in state.assets:
        for role, raw_path in state.release_file_paths(asset):
            path = Path(raw_path)
            if path.is_file():
                live_hashes[(asset.id, role)] = _sha256_file(path)

    live_verified = bool(expected) and set(expected) == set(live_hashes)
    if live_verified:
        live_verified = all(
            live_hashes[key] == str(item.get("sha256", ""))
            for key, item in expected.items()
        )

    archive_verified = False
    try:
        with zipfile.ZipFile(archive_path) as archive:
            archived_manifest = json.loads(
                archive.read("campaign-pack.json").decode("utf-8")
            )
            archive_verified = archived_manifest == manifest
            for item in expected.values():
                payload = archive.read(str(item["archive_name"]))
                archive_verified = archive_verified and (
                    _sha256_bytes(payload) == str(item["sha256"])
                )
    except (KeyError, OSError, UnicodeError, zipfile.BadZipFile, json.JSONDecodeError):
        archive_verified = False

    release_files = [
        {
            "asset_id": asset_id,
            "role": role,
            "sha256": live_hashes.get((asset_id, role)),
        }
        for asset_id, role in sorted(expected)
    ]
    return {
        "verified": live_verified and archive_verified,
        "manifest_sha256": _sha256_file(manifest_path),
        "archive_sha256": _sha256_file(archive_path),
        "release_files": release_files,
        "reason": None if live_verified and archive_verified else "hash mismatch",
    }


def _run_happy_case(root: Path, case: EvalCase, index: int) -> dict[str, Any]:
    case_root = root / "cases" / case.case_id
    case_root.mkdir(parents=True, exist_ok=False)
    product_path = case_root / "synthetic-product.png"
    _make_product(product_path, index)
    supervisor = _supervisor(
        seed=202680 + index,
        unsafe_first_pass=case.unsafe_first_pass,
    )
    prepared = supervisor.prepare(
        _request(case, product_path),
        str(case_root),
        run_id=f"vertical-{case.case_id}",
    )
    prepare_ok = prepared.stage is Stage.AWAITING_RELEASE

    unapproved_export_rejected = False
    unapproved_error = None
    if prepare_ok:
        try:
            supervisor.adapters.exporter.export(prepared)
        except RuntimeError as exc:
            unapproved_export_rejected = True
            unapproved_error = str(exc)
    bundle_before_approval = _bundle_exists(case_root)

    fixture_approval = None
    final = prepared
    release_error = None
    if prepare_ok:
        fixture_approval = _approval(prepared, suffix=case.case_id)
        try:
            final = supervisor.release(case_root, fixture_approval)
        except Exception as exc:  # The aggregate must record a failed case.
            release_error = f"{type(exc).__name__}: {exc}"

    ledger_path = case_root / "evidence-ledger.jsonl"
    ledger_verified = EvidenceLedger.verify(ledger_path)
    events = _read_ledger(ledger_path) if ledger_verified else []
    duplicate_successes = _duplicate_success_count(events)
    pack_trace = _verify_pack(final, case_root)
    release_ok = (
        final.stage is Stage.DELIVER
        and fixture_approval is not None
        and fixture_approval.kind is ReleaseApprovalKind.FIXTURE
        and bool(final.exports)
        and all(Path(path).is_file() for path in final.exports)
        and pack_trace["verified"]
    )
    return {
        "case_id": case.case_id,
        "market": case.market,
        "platform": case.platform,
        "target_emotion": case.target_emotion,
        "goal": case.goal,
        "rights_basis": dict(RIGHTS_BASIS),
        "prepare_stage": prepared.stage.value,
        "prepare_success": prepare_ok,
        "release_stage": final.stage.value,
        "release_success": release_ok,
        "repair_count": final.repair_count,
        "repair_bound_satisfied": final.repair_count <= 2,
        "fixture_approval": (
            fixture_approval.serializable() if fixture_approval is not None else None
        ),
        "unapproved_export_rejected": unapproved_export_rejected,
        "unapproved_export_error": unapproved_error,
        "bundle_before_approval": bundle_before_approval,
        "release_error": release_error,
        "blocked_reason": final.blocked_reason,
        "duplicate_successful_step_count": duplicate_successes,
        "hash_trace": {
            "ledger_verified": ledger_verified,
            "ledger_sha256": _sha256_file(ledger_path) if ledger_path.is_file() else None,
            **pack_trace,
        },
    }


def _prepare_probe(
    probes_root: Path,
    name: str,
    *,
    unsafe_first_pass: bool = False,
) -> tuple[Path, Supervisor, Any]:
    probe_root = probes_root / name
    probe_root.mkdir(parents=True, exist_ok=False)
    product_path = probe_root / "synthetic-product.png"
    _make_product(product_path, 30 + len(name))
    case = replace(CASES[0], case_id=f"probe-{name}", unsafe_first_pass=unsafe_first_pass)
    supervisor = _supervisor(seed=303000 + len(name), unsafe_first_pass=unsafe_first_pass)
    prepared = supervisor.prepare(
        _request(case, product_path),
        str(probe_root),
        run_id=f"vertical-probe-{name}",
    )
    return probe_root, supervisor, prepared


def _probe_state_tamper(probes_root: Path) -> dict[str, Any]:
    root, supervisor, prepared = _prepare_probe(probes_root, "state-tamper")
    approval = _approval(prepared, suffix="state-tamper")
    state_path = root / "campaign-state.json"
    payload = json.loads(state_path.read_text(encoding="utf-8"))
    payload["claims"][0]["text"] = "Injected unsupported replacement claim."
    state_path.write_text(json.dumps(payload), encoding="utf-8")
    blocked = False
    error = None
    try:
        supervisor.release(root, approval)
    except WorkflowBlocked as exc:
        blocked = True
        error = str(exc)
    passed = blocked and not _bundle_exists(root)
    return {
        "probe": "state_tamper",
        "passed": passed,
        "blocked": blocked,
        "bundle_created": _bundle_exists(root),
        "error": error,
        "ledger_verified": EvidenceLedger.verify(root / "evidence-ledger.jsonl"),
    }


def _probe_asset_tamper(probes_root: Path) -> dict[str, Any]:
    root, supervisor, prepared = _prepare_probe(probes_root, "asset-tamper")
    approval = _approval(prepared, suffix="asset-tamper")
    Path(prepared.assets[0].path).write_bytes(b"tampered-after-audit")
    blocked = False
    error = None
    try:
        supervisor.release(root, approval)
    except WorkflowBlocked as exc:
        blocked = True
        error = str(exc)
    passed = blocked and not _bundle_exists(root)
    return {
        "probe": "asset_tamper",
        "passed": passed,
        "blocked": blocked,
        "bundle_created": _bundle_exists(root),
        "error": error,
        "ledger_verified": EvidenceLedger.verify(root / "evidence-ledger.jsonl"),
    }


def _probe_rejection(probes_root: Path) -> dict[str, Any]:
    root, supervisor, prepared = _prepare_probe(probes_root, "rejection")
    approval = _approval(
        prepared,
        decision=ReleaseDecision.REJECT,
        suffix="rejection",
    )
    state = supervisor.release(root, approval)
    passed = (
        state.stage is Stage.BLOCKED
        and not state.exports
        and not _bundle_exists(root)
        and approval.kind is ReleaseApprovalKind.FIXTURE
    )
    return {
        "probe": "explicit_rejection",
        "passed": passed,
        "final_stage": state.stage.value,
        "bundle_created": _bundle_exists(root),
        "approval_kind": approval.kind.value,
        "blocked_reason": state.blocked_reason,
        "ledger_verified": EvidenceLedger.verify(root / "evidence-ledger.jsonl"),
    }


def _probe_crash_retry(probes_root: Path) -> dict[str, Any]:
    class InterruptingExporter:
        def export(self, state: Any) -> list[str]:
            del state
            raise KeyboardInterrupt("injected crash after approval checkpoint")

    root, healthy, prepared = _prepare_probe(probes_root, "crash-retry")
    # Re-run the probe with a Supervisor that shares the real adapters except for
    # the single injected crash point. The original build_supervisor is retained
    # for recovery.
    interrupted = Supervisor(replace(healthy.adapters, exporter=InterruptingExporter()))
    approval = _approval(prepared, suffix="crash-retry")
    crash_observed = False
    try:
        interrupted.release(root, approval)
    except KeyboardInterrupt:
        crash_observed = True
    bundle_after_crash = _bundle_exists(root)
    recovered = healthy.release(root, approval)
    ledger_path = root / "evidence-ledger.jsonl"
    events = _read_ledger(ledger_path)
    duplicate_successes = _duplicate_success_count(events)
    approval_events = [
        event for event in events if event.get("kind") == "release_approved"
    ]
    delivered_events = [
        event for event in events if event.get("kind") == "campaign_delivered"
    ]
    pack_trace = _verify_pack(recovered, root)
    passed = (
        crash_observed
        and not bundle_after_crash
        and recovered.stage is Stage.DELIVER
        and recovered.release_approval == approval
        and len(approval_events) == 1
        and len(delivered_events) == 1
        and duplicate_successes == 0
        and EvidenceLedger.verify(ledger_path)
        and pack_trace["verified"]
    )
    return {
        "probe": "same_approval_crash_retry",
        "passed": passed,
        "crash_observed": crash_observed,
        "bundle_after_crash": bundle_after_crash,
        "final_stage": recovered.stage.value,
        "same_approval_id": (
            recovered.release_approval is not None
            and recovered.release_approval.approval_id == approval.approval_id
        ),
        "release_approved_event_count": len(approval_events),
        "campaign_delivered_event_count": len(delivered_events),
        "duplicate_successful_step_count": duplicate_successes,
        "ledger_verified": EvidenceLedger.verify(ledger_path),
        "pack_hashes_verified": pack_trace["verified"],
    }


def _probe_two_repair_bound(probes_root: Path) -> dict[str, Any]:
    class AlwaysBlockingAuditor:
        def audit(self, state: Any) -> list[AuditFinding]:
            return [
                AuditFinding(
                    id="AUD-INJECTED-PERSISTENT",
                    category="injected_persistent_gate",
                    severity=Severity.CRITICAL,
                    message="Injected persistent release blocker.",
                    asset_id=state.assets[0].id,
                    repair_action="apply_accessible_type_layout",
                )
            ]

    probe_root = probes_root / "two-repair-bound"
    probe_root.mkdir(parents=True, exist_ok=False)
    product_path = probe_root / "synthetic-product.png"
    _make_product(product_path, 88)
    case = replace(CASES[0], case_id="probe-two-repair-bound")
    base = _supervisor(seed=404002)
    supervisor = Supervisor(replace(base.adapters, auditor=AlwaysBlockingAuditor()))
    state = supervisor.prepare(
        _request(case, product_path),
        str(probe_root),
        run_id="vertical-probe-two-repair-bound",
    )
    passed = (
        state.stage is Stage.BLOCKED
        and state.repair_count == 2
        and state.max_repairs == 2
        and not _bundle_exists(probe_root)
        and "after 2 repair rounds" in (state.blocked_reason or "")
    )
    return {
        "probe": "maximum_two_repairs",
        "passed": passed,
        "final_stage": state.stage.value,
        "repair_count": state.repair_count,
        "max_repairs": state.max_repairs,
        "bundle_created": _bundle_exists(probe_root),
        "blocked_reason": state.blocked_reason,
        "ledger_verified": EvidenceLedger.verify(
            probe_root / "evidence-ledger.jsonl"
        ),
    }


def _aggregate_hash_root(case_results: list[dict[str, Any]]) -> str:
    normalized = []
    for result in case_results:
        release_files = result["hash_trace"].get("release_files", [])
        normalized.append(
            {
                "case_id": result["case_id"],
                "release_files": sorted(
                    release_files,
                    key=lambda item: (item["asset_id"], item["role"]),
                ),
            }
        )
    return _sha256_bytes(canonical_json(normalized).encode("utf-8"))


def run_evaluation(output_dir: str | Path) -> dict[str, Any]:
    root = Path(output_dir)
    if root.exists() and any(root.iterdir()):
        raise FileExistsError(f"evaluation output must be empty: {root}")
    root.mkdir(parents=True, exist_ok=True)

    case_results = [
        _run_happy_case(root, case, index)
        for index, case in enumerate(CASES, start=1)
    ]
    unapproved_export_attempts = sum(
        item["prepare_success"] for item in case_results
    )
    unapproved_export_rejections = sum(
        item["unapproved_export_rejected"] for item in case_results
    )
    unapproved_bundle_count = sum(
        item["bundle_before_approval"] for item in case_results
    )
    happy_ledgers_verified = all(
        item["hash_trace"]["ledger_verified"] for item in case_results
    )
    probes_root = root / "failure-probes"
    probes_root.mkdir(parents=True, exist_ok=False)
    failure_probes = [
        {
            "probe": "unapproved_export",
            "passed": (
                unapproved_export_attempts == len(CASES)
                and unapproved_export_rejections == len(CASES)
                and unapproved_bundle_count == 0
            ),
            "attempts": unapproved_export_attempts,
            "rejections": unapproved_export_rejections,
            "bundle_created_count": unapproved_bundle_count,
            "ledger_verified": happy_ledgers_verified,
        },
        _probe_state_tamper(probes_root),
        _probe_asset_tamper(probes_root),
        _probe_rejection(probes_root),
        _probe_crash_retry(probes_root),
        _probe_two_repair_bound(probes_root),
    ]

    case_count = len(case_results)
    prepare_successes = sum(item["prepare_success"] for item in case_results)
    release_successes = sum(item["release_success"] for item in case_results)
    duplicate_successful_step_count = sum(
        item["duplicate_successful_step_count"] for item in case_results
    ) + sum(
        int(item.get("duplicate_successful_step_count", 0))
        for item in failure_probes
    )
    cases_over_two_repairs = sum(
        item["repair_count"] > 2 for item in case_results
    )
    ledger_verified = happy_ledgers_verified and all(
        item["ledger_verified"] for item in failure_probes
    )
    manifest_hashes_verified = all(
        item["hash_trace"]["verified"] for item in case_results
    )
    failure_probe_passes = sum(item["passed"] for item in failure_probes)

    metrics = {
        "prepare_success_rate": prepare_successes / case_count,
        "release_success_rate": release_successes / case_count,
        "unapproved_export_attempts": unapproved_export_attempts,
        "unapproved_export_rejection_rate": (
            unapproved_export_rejections / unapproved_export_attempts
            if unapproved_export_attempts
            else 0.0
        ),
        "unapproved_bundle_count": unapproved_bundle_count,
        "duplicate_successful_step_count": duplicate_successful_step_count,
        "max_happy_path_repair_count": max(
            item["repair_count"] for item in case_results
        ),
        "cases_over_two_repairs": cases_over_two_repairs,
        "failure_probe_pass_rate": failure_probe_passes / len(failure_probes),
        "all_ledgers_verified": ledger_verified,
        "all_manifest_file_hashes_verified": manifest_hashes_verified,
    }
    gates = {
        "case_count": case_count == PREDECLARED_BAR["case_count"],
        "prepare_success_rate": (
            metrics["prepare_success_rate"]
            >= PREDECLARED_BAR["prepare_success_rate"]
        ),
        "release_success_rate": (
            metrics["release_success_rate"]
            >= PREDECLARED_BAR["release_success_rate"]
        ),
        "unapproved_export_attempts": (
            metrics["unapproved_export_attempts"]
            == PREDECLARED_BAR["unapproved_export_attempts"]
        ),
        "unapproved_export_rejection_rate": (
            metrics["unapproved_export_rejection_rate"]
            >= PREDECLARED_BAR["unapproved_export_rejection_rate"]
        ),
        "unapproved_bundle_count": (
            metrics["unapproved_bundle_count"]
            == PREDECLARED_BAR["unapproved_bundle_count"]
        ),
        "duplicate_successful_step_count": (
            metrics["duplicate_successful_step_count"]
            == PREDECLARED_BAR["duplicate_successful_step_count"]
        ),
        "cases_over_two_repairs": (
            metrics["cases_over_two_repairs"]
            == PREDECLARED_BAR["cases_over_two_repairs"]
        ),
        "failure_probe_pass_rate": (
            metrics["failure_probe_pass_rate"]
            >= PREDECLARED_BAR["failure_probe_pass_rate"]
        ),
        "all_ledgers_verified": (
            metrics["all_ledgers_verified"]
            is PREDECLARED_BAR["all_ledgers_verified"]
        ),
        "all_manifest_file_hashes_verified": (
            metrics["all_manifest_file_hashes_verified"]
            is PREDECLARED_BAR["all_manifest_file_hashes_verified"]
        ),
    }
    result = {
        "schema": SCHEMA,
        "evaluation_kind": "offline deterministic mechanical agent evaluation",
        "decision_gated": "Day-3 vertical-slice production rehearsal readiness",
        "predeclared_bar": dict(PREDECLARED_BAR),
        "case_count": case_count,
        "coverage": {
            "markets": sorted({case.market for case in CASES}),
            "platforms": sorted({case.platform for case in CASES}),
            "target_emotions": sorted({case.target_emotion for case in CASES}),
            "rights_basis": dict(RIGHTS_BASIS),
        },
        "metrics": metrics,
        "gates": gates,
        "passed": all(gates.values()),
        "cases": case_results,
        "failure_injections": failure_probes,
        "hash_trace": {
            "algorithm": "sha256",
            "root": _aggregate_hash_root(case_results),
            "all_ledgers_verified": ledger_verified,
            "all_manifest_file_hashes_verified": manifest_hashes_verified,
            "scope": (
                "Root binds case IDs to released creative/product-layer/background "
                "file hashes; per-case records also retain ledger, manifest, and ZIP hashes."
            ),
        },
        "limitations": [
            "All inputs are synthetic rights-clear fixtures; no live customer data or production traffic was evaluated.",
            "Every approval is explicitly kind=fixture and is not a human production authorization.",
            "The lexical audience pulse and procedural compositor are deterministic fallbacks, not a real trained audience model.",
            "This evaluation does not claim 4A creative quality, campaign lift, persuasion, or human preference.",
            "This evaluation does not prove AMD Radeon execution, model fine-tuning, or multimodal model quality.",
            "Small canvases reduce CI cost; typography and hash bytes can vary if the host font stack changes.",
        ],
    }
    result_path = root / "agent-vertical-slice-eval.json"
    temporary_result_path = result_path.with_name(f".{result_path.name}.tmp")
    temporary_result_path.write_text(
        json.dumps(result, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    temporary_result_path.replace(result_path)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run the deterministic ProofLaunch Agent vertical-slice eval."
    )
    parser.add_argument(
        "--output",
        default="evidence/local/agent-vertical-slice-eval",
        help="Empty output directory for cases, probes, and aggregate JSON.",
    )
    args = parser.parse_args()
    result = run_evaluation(args.output)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    raise SystemExit(0 if result["passed"] else 1)


if __name__ == "__main__":
    main()
