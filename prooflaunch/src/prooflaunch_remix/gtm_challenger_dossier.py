from __future__ import annotations

import base64
import html
import json
import mimetypes
import re
import wave
from pathlib import Path
from typing import Any, Mapping

from PIL import Image

from .files import atomic_write_text, sha256_file
from .gtm_unified_offline_review import seal, sha256_json


DOSSIER_REPORT_SCHEMA = "ProofLaunchNamedProductChallengerAdmissionV1"
DOSSIER_SCHEMA = "ProofLaunchNamedProductChallengerDossierV1"
LEDGER_SCHEMA = "ProofLaunchConcreteProductEffectPKLedgerV1"
SUPPORTED = {
    ".json", ".md", ".txt", ".vtt", ".js", ".mjs", ".html", ".pdf",
    ".png", ".jpg", ".jpeg", ".webp",
    ".mp4", ".mov", ".webm",
    ".wav", ".mp3", ".flac", ".m4a",
}
DOSSIER_ROOT_FRAGMENT = "named-product-challenger-dossiers-v1"
_DIGEST = re.compile(r"^[0-9a-f]{64}$")


class ChallengerDossierError(ValueError):
    pass


def _load_json(path: Path) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file():
        raise ChallengerDossierError(f"unsafe or missing JSON: {path}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ChallengerDossierError(f"invalid JSON: {path}") from error
    if not isinstance(value, dict):
        raise ChallengerDossierError(f"JSON must be an object: {path}")
    return value


def _verify_ledger(value: object) -> dict[str, Any]:
    if not isinstance(value, dict) or value.get("schema") != LEDGER_SCHEMA:
        raise ChallengerDossierError("challenger ledger schema is invalid")
    supplied = value.get("content_sha256")
    unsigned = dict(value)
    unsigned.pop("content_sha256", None)
    if not isinstance(supplied, str) or not _DIGEST.fullmatch(supplied) or supplied != sha256_json(unsigned):
        raise ChallengerDossierError("challenger ledger digest is invalid")
    if value.get("category_count") != 13 or value.get("reference_product_row_count") != 130:
        raise ChallengerDossierError("challenger ledger coverage drifted")
    return value


def _inside(path: Path, root: Path) -> Path:
    resolved = path.resolve(strict=True)
    try:
        resolved.relative_to(root.resolve(strict=True))
    except ValueError as error:
        raise ChallengerDossierError("challenger artifact escaped the project root") from error
    if path.is_symlink() or resolved.is_symlink() or not resolved.is_file():
        raise ChallengerDossierError("challenger artifact is missing or unsafe")
    return resolved


def _artifact(path: Path, *, relative: str, declared: Mapping[str, Any]) -> dict[str, Any]:
    suffix = path.suffix.casefold()
    if suffix not in SUPPORTED:
        raise ChallengerDossierError(f"challenger artifact is not directly reviewable: {relative}")
    observed = {
        "path": relative,
        "bytes": path.stat().st_size,
        "sha256": sha256_file(path),
        "extension": suffix,
        "media_type": mimetypes.guess_type(path.name)[0] or "application/octet-stream",
    }
    if declared.get("exists") is not True or declared.get("bytes") != observed["bytes"] or declared.get("sha256") != observed["sha256"]:
        raise ChallengerDossierError(f"challenger artifact binding drifted: {relative}")
    if suffix == ".json":
        _load_json(path)
    return observed


def _json_text(path: Path) -> str:
    return json.dumps(_load_json(path), ensure_ascii=False, indent=2, sort_keys=True)


def _render(path: Path, item: Mapping[str, Any], index: int) -> str:
    suffix = path.suffix.casefold()
    title = f"Deliverable {index:02d} · {html.escape(str(item['media_type']))} · {item['bytes']:,} bytes"
    if suffix == ".json":
        body = f"<pre>{html.escape(_json_text(path))}</pre>"
    elif suffix in {".md", ".txt", ".vtt", ".js", ".mjs"}:
        body = f"<pre>{html.escape(path.read_text(encoding='utf-8'))}</pre>"
    else:
        encoded = base64.b64encode(path.read_bytes()).decode("ascii")
        uri = f"data:{item['media_type']};base64,{encoded}"
        if suffix in {".png", ".jpg", ".jpeg", ".webp"}:
            body = f'<img src="{uri}" alt="source-hidden candidate deliverable {index}">'
        elif suffix in {".mp4", ".mov", ".webm"}:
            body = f'<video controls preload="metadata" src="{uri}"></video>'
        elif suffix in {".wav", ".mp3", ".flac", ".m4a"}:
            body = f'<audio controls preload="metadata" src="{uri}"></audio>'
        else:
            body = f'<iframe sandbox title="source-hidden candidate deliverable {index}" src="{uri}"></iframe>'
    return f"<section><h2>{title}</h2><p><code>sha256:{item['sha256']}</code></p>{body}</section>"


def _strings(value: object) -> str:
    if isinstance(value, str):
        return value.casefold()
    if isinstance(value, Mapping):
        return " ".join(f"{str(key).replace('_', ' ').casefold()} {_strings(item)}" for key, item in value.items())
    if isinstance(value, list):
        return " ".join(_strings(item) for item in value)
    return ""


def _json_by_name(paths: list[Path], name: str) -> dict[str, Any] | None:
    for path in paths:
        if path.name == name:
            return _load_json(path)
    return None


def _require_terms(text: str, terms: list[str], gaps: list[str], prefix: str) -> None:
    missing = [term for term in terms if term.casefold() not in text]
    if missing:
        gaps.append(f"{prefix}: missing explicit evidence for {', '.join(missing)}")


def _category_gaps(category_id: str, paths: list[Path]) -> list[str]:
    gaps: list[str] = []
    json_values = [_load_json(path) for path in paths if path.suffix.casefold() == ".json"]
    text = " ".join(_strings(value) for value in json_values)
    if category_id == "cross_device_memory":
        execution = _json_by_name(paths, "cross-device-memory-execution.json") or {}
        event_names = [item.get("event") for item in execution.get("events", [])]
        if not isinstance(execution.get("memory_count"), int) or execution.get("memory_count", 0) < 2:
            gaps.append("no approved memory is present for retrieval")
        if not execution.get("latest_source_observation_id"):
            gaps.append("no source-bound observation is present")
        for event in ("conflict_resolved", "cross_tenant_retrieval_denied", "cross_device_retrieval_succeeded", "deletion_tombstone_appended", "post_deletion_retrieval"):
            if event not in event_names:
                gaps.append(f"memory lifecycle event is missing: {event}")
        if execution.get("hash_chain_valid") is not True:
            gaps.append("memory lifecycle event chain is not valid")
    elif category_id == "data_strategy_intelligence":
        memo = _json_by_name(paths, "data-strategy-decision-memo.json") or {}
        for field in ("lineage", "forecast_uncertainty", "scenarios", "reversible_recommendation"):
            if not memo.get(field):
                gaps.append(f"decision memo field is missing: {field}")
        if memo.get("causal_claim_allowed") is not False:
            gaps.append("decision memo causal boundary is not fail-closed")
    elif category_id == "content_scheduling_operations":
        calendar = _json_by_name(paths, "content-calendar.json") or {}
        if len(calendar.get("slots", [])) != 7:
            gaps.append("seven executable calendar slots are not present")
        for field in ("timezone", "approval_queue", "frequency_cap"):
            if not calendar.get(field):
                gaps.append(f"calendar field is missing: {field}")
        if calendar.get("automatic_publish_enabled") is not False or calendar.get("automatic_rescheduling_enabled") is not False:
            gaps.append("calendar authority boundary is not fail-closed")
    elif category_id == "image_generation_editing":
        observed = []
        for path in paths:
            if path.suffix.casefold() in {".png", ".jpg", ".jpeg", ".webp"}:
                with Image.open(path) as image:
                    image.verify()
                with Image.open(path) as image:
                    observed.append(tuple(image.size))
        for required in ((3840, 2160), (1080, 1350), (1920, 1080)):
            if required not in observed:
                gaps.append(f"required rendered format is missing: {required[0]}x{required[1]}")
    elif category_id == "video_generation_production":
        receipt = _json_by_name(paths, "video-challenger-receipt.json") or {}
        variants = receipt.get("variants")
        if isinstance(variants, list):
            mp4_by_sha = {
                sha256_file(path): path
                for path in paths
                if path.suffix.casefold() == ".mp4"
            }
            observed_sizes: set[tuple[int, int]] = set()
            if len(variants) < 2:
                gaps.append("dual-aspect 4K variants are missing")
            for variant in variants:
                if not isinstance(variant, Mapping):
                    gaps.append("video variant receipt is invalid")
                    continue
                video = variant.get("video") if isinstance(variant.get("video"), Mapping) else {}
                if video.get("sha256") not in mp4_by_sha:
                    gaps.append("4K variant is not bound to its production receipt")
                width = int(variant.get("width", 0))
                height = int(variant.get("height", 0))
                observed_sizes.add((width, height))
                if max(width, height) < 3840 or min(width, height) < 2160:
                    gaps.append("video variant is below 4K")
                if not 14.0 <= float(variant.get("duration_seconds", 0)) <= 16.0:
                    gaps.append("video variant duration is outside the frozen 15-second window")
                if len(variant.get("audit_frames", [])) < 3:
                    gaps.append("video variant three-beat audit frames are missing")
            if not {(3840, 2160), (2160, 3840)}.issubset(observed_sizes):
                gaps.append("landscape and vertical 4K masters are not both present")
        else:
            video = receipt.get("video") if isinstance(receipt.get("video"), Mapping) else {}
            mp4 = next((path for path in paths if path.suffix.casefold() == ".mp4"), None)
            if mp4 is None or video.get("sha256") != (sha256_file(mp4) if mp4 else None):
                gaps.append("4K master is not bound to its production receipt")
            if video.get("width", 0) < 3840 or video.get("height", 0) < 2160:
                gaps.append("video master is below 4K")
            if not 14.0 <= float(video.get("duration_seconds", 0)) <= 16.0:
                gaps.append("video duration is outside the frozen 15-second window")
            if len(receipt.get("audit_frames", [])) < 3:
                gaps.append("three-beat audit frames are missing")
    elif category_id == "audio_voice_music":
        wavs = [path for path in paths if path.suffix.casefold() == ".wav"]
        if len(wavs) != 3:
            gaps.append("three voice-direction masters are not present")
        for path in wavs:
            with wave.open(str(path), "rb") as handle:
                if (handle.getframerate(), handle.getnchannels(), handle.getsampwidth()) != (48000, 2, 3):
                    gaps.append(f"audio mastering contract failed for {path.name}")
        receipt = _json_by_name(paths, "audio-candidate-receipt.json") or {}
        if not receipt.get("frozen_script") or receipt.get("candidate_count") != 3:
            gaps.append("same-script candidate receipt is incomplete")
        if any(item.get("identifiable_person_imitation_requested") is not False for item in receipt.get("candidates", [])):
            gaps.append("voice consent/imitation boundary failed")
    elif category_id == "text_content_generation":
        channel = _json_by_name(paths, "channel-copy.json") or {}
        landing = _json_by_name(paths, "landing-page-draft.json") or {}
        email = _json_by_name(paths, "lifecycle-email-draft.json") or {}
        if not channel.get("primary") or not channel.get("secondary"):
            gaps.append("two channel-native social/community executions are not present")
        if not landing.get("hero") or not landing.get("citation"):
            gaps.append("landing hero or evidence citation is missing")
        if not email.get("subject") or not email.get("body_blocks") or not email.get("citation"):
            gaps.append("lifecycle email or evidence citation is missing")
    elif category_id == "product_marketing_analytics":
        system = _json_by_name(paths, "product-analytics-measurement-system.json") or {}
        for field in ("identity_model", "event_contract", "funnel", "cohort", "randomized_holdout", "revenue_reconciliation", "incrementality"):
            if not system.get(field):
                gaps.append(f"measurement system field is missing: {field}")
        if system.get("incrementality", {}).get("causal_claim_allowed") is not False:
            gaps.append("measurement causal boundary is not fail-closed")
    elif category_id == "geo_ai_visibility":
        faq = _json_by_name(paths, "seo-geo-faq-drafts.json") or {}
        rows = faq.get("faqs", [])
        if len(rows) < 4:
            gaps.append("fewer than four answer-engine questions are present")
        if any(not row.get("question") or not row.get("answer_draft") or not row.get("citation", {}).get("evidence_sha256") for row in rows):
            gaps.append("a GEO answer lacks a direct answer or evidence citation")
    elif category_id == "seo_operations":
        execution = _json_by_name(paths, "seo-technical-execution.json") or {}
        for field in ("owned_page", "structured_data", "internal_link_graph", "performance_audit", "crawl_audit", "content_brief"):
            if not execution.get(field):
                gaps.append(f"technical SEO execution field is missing: {field}")
        if execution.get("measured_organic_delta", "missing") is not None:
            gaps.append("unobserved organic delta was not preserved as null")
    elif category_id == "employee_agent_platforms":
        trace = _json_by_name(paths, "employee-agent-execution-trace.json") or {}
        for field in ("forced_tool_failure_observed", "approval_denial_observed", "recovery_trace_observed", "hash_chain_valid"):
            if trace.get(field) is not True:
                gaps.append(f"executed Agent trace gate failed: {field}")
        if trace.get("external_action_executed") is not False:
            gaps.append("Agent recovery trace escaped its authority boundary")
    elif category_id == "advertising_activation":
        advertising = _json_by_name(paths, "advertising-creative-system.json") or {}
        routes = advertising.get("creative_routes")
        if not isinstance(routes, list) or len(routes) < 3:
            gaps.append("three distinct advertising creative routes are not present")
        if not advertising.get("audience", {}).get("audience_exclusions"):
            gaps.append("audience exclusions are not present")
        if not advertising.get("incrementality_design") or not advertising.get("brand_safety"):
            gaps.append("incrementality or brand-safety design is missing")
        if advertising.get("budget", {}).get("activation_authorized") is not False:
            gaps.append("advertising activation authority is not fail-closed")
    elif category_id == "gtm_lifecycle_orchestration":
        lifecycle = _json_by_name(paths, "gtm-lifecycle-execution-dossier.json") or {}
        for field in ("diagnosis", "strategy_binding", "asset_bindings", "approval_receipt", "experiment_observation", "next_cycle_recommendation", "cross_device_memory"):
            if not lifecycle.get(field):
                gaps.append(f"executed lifecycle dossier field is missing: {field}")
        if lifecycle.get("experiment_observation", {}).get("production_outcome") is not False:
            gaps.append("synthetic lifecycle observation overclaimed production effect")
    else:
        gaps.append("category admission policy is missing")
    return gaps


def _dossier_html(category: Mapping[str, Any], rendered: list[str], manifest_core: Mapping[str, Any]) -> str:
    embedded = html.escape(json.dumps(manifest_core, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
    return f'''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Source-hidden challenger dossier</title><style>:root{{--ink:#f5f7ff;--muted:#aeb7d4;--panel:#11162a;--line:#384163;--accent:#8d6cff}}*{{box-sizing:border-box}}body{{margin:0;background:#080b16;color:var(--ink);font:15px/1.5 system-ui,sans-serif}}main{{max-width:1440px;margin:auto;padding:28px}}header,section{{background:var(--panel);border:1px solid var(--line);border-radius:16px;padding:20px;margin-bottom:18px}}h1,h2{{line-height:1.15}}.boundary{{border-left:4px solid var(--accent);padding-left:12px;color:var(--muted)}}img,video,audio,iframe{{display:block;width:100%}}iframe{{height:700px;background:#fff}}pre{{white-space:pre-wrap;overflow:auto;max-height:720px;background:#080b16;padding:16px;border-radius:10px}}code{{word-break:break-all;color:#cbbfff}}</style></head><body><main>
<header><p><strong>Source-hidden same-brief challenger</strong></p><h1>{html.escape(str(category['category_id']).replace('_', ' ').title())}</h1><p>{html.escape(str(category['same_brief_task']))}</p><p><strong>Decision question:</strong> {html.escape(str(category['effect_pk_question']))}</p><p><strong>Quality axes:</strong> {html.escape(' · '.join(category['quality_axes']))}</p><p class="boundary">This self-contained dossier preserves every sealed candidate deliverable needed for side-by-side human review. It contains no product/provider role mapping and cannot promote, publish, send, spend, or establish 4A effect.</p><details><summary>Machine-readable dossier binding</summary><pre>{embedded}</pre></details></header>
{''.join(rendered)}</main></body></html>'''


def compile_challenger_dossiers(*, project_root: Path, ledger_path: Path, output_root: Path) -> dict[str, Any]:
    root = project_root.resolve(strict=True)
    ledger = _verify_ledger(_load_json(ledger_path))
    output = output_root.resolve()
    expected_outputs = {
        f"{category['category_id']}.html" for category in ledger["categories"]
    } | {"manifest.json"}
    if output.exists():
        unexpected = {path.name for path in output.iterdir()} - expected_outputs
        if unexpected:
            raise ChallengerDossierError(
                "challenger dossier output contains unexpected files: "
                + ", ".join(sorted(unexpected))
            )
    output.mkdir(parents=True, mode=0o700, exist_ok=True)
    rows_by_category: dict[str, list[dict[str, Any]]] = {}
    for row in ledger["product_pk_rows"]:
        rows_by_category.setdefault(row["category_id"], []).append(row)
    categories: list[dict[str, Any]] = []
    for category in ledger["categories"]:
        category_id = category["category_id"]
        rows = rows_by_category.get(category_id, [])
        if len(rows) != 10:
            raise ChallengerDossierError(f"named-product row coverage drifted for {category_id}")
        source_artifacts = [
            item for item in rows[0]["candidate_artifacts"]
            if DOSSIER_ROOT_FRAGMENT not in str(item.get("path", ""))
        ]
        if not source_artifacts or any(row["candidate_artifacts"] != rows[0]["candidate_artifacts"] for row in rows):
            raise ChallengerDossierError(f"candidate artifact set drifted inside {category_id}")
        paths: list[Path] = []
        artifacts: list[dict[str, Any]] = []
        for declared in source_artifacts:
            relative = str(declared.get("path", ""))
            path = _inside(root / relative, root)
            paths.append(path)
            artifacts.append(_artifact(path, relative=relative, declared=declared))
        gaps = _category_gaps(category_id, paths)
        dossier_core = {
            "schema": DOSSIER_SCHEMA,
            "category_id": category_id,
            "same_brief_task": category["same_brief_task"],
            "effect_pk_question": category["effect_pk_question"],
            "quality_axes": category["quality_axes"],
            "source_artifacts": [
                {key: value for key, value in artifact.items() if key != "path"}
                for artifact in artifacts
            ],
            "source_artifact_count": len(artifacts),
            "provider_identity_exposed": False,
            "candidate_role_exposed": False,
            "self_contained": True,
            "automatic_action_authority": False,
        }
        dossier_name = f"{category_id}.html"
        dossier_path = output / dossier_name
        rendered = [_render(path, artifact, index) for index, (path, artifact) in enumerate(zip(paths, artifacts), 1)]
        atomic_write_text(dossier_path, _dossier_html(category, rendered, dossier_core))
        categories.append(
            {
                "category_id": category_id,
                "dossier": {
                    "project_relative_path": dossier_path.relative_to(root).as_posix(),
                    "bytes": dossier_path.stat().st_size,
                    "sha256": sha256_file(dossier_path),
                    "media_type": "text/html",
                },
                "source_artifact_count": len(artifacts),
                "source_artifacts": artifacts,
                "dossier_compiled": True,
                "same_brief_material_complete": not gaps,
                "named_product_pk_preparation_admitted": not gaps,
                "blocking_gap_count": len(gaps),
                "blocking_gaps": gaps,
                "repair_action": "admit_for_source_hidden_named_product_pairing" if not gaps else "repair_missing_same_brief_evidence_then_recompile",
            }
        )
    core = {
        "schema": DOSSIER_REPORT_SCHEMA,
        "source_ledger_sha256": ledger["content_sha256"],
        "category_count": 13,
        "reference_product_row_count": 130,
        "dossier_count": len(categories),
        "admitted_category_count": sum(item["named_product_pk_preparation_admitted"] for item in categories),
        "blocked_category_count": sum(not item["named_product_pk_preparation_admitted"] for item in categories),
        "categories": categories,
        "automatic_pairing_enabled": False,
        "automatic_product_execution_enabled": False,
        "automatic_pk_promotion_enabled": False,
        "four_a_quality_proven": False,
        "truth_boundary": (
            "A dossier makes the complete sealed challenger output directly inspectable. Admission means only that the predeclared same-brief material contract is present; it is not human preference, named-product victory, 4A quality, publication, causal lift or revenue evidence."
        ),
    }
    report = seal(core)
    atomic_write_text(output / "manifest.json", json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    return report


def validate_challenger_admission(payload: object, *, ledger: Mapping[str, Any], project_root: Path) -> dict[str, Any]:
    if not isinstance(payload, dict) or payload.get("schema") != DOSSIER_REPORT_SCHEMA:
        raise ChallengerDossierError("challenger admission schema is invalid")
    supplied = payload.get("content_sha256")
    unsigned = dict(payload)
    unsigned.pop("content_sha256", None)
    if not isinstance(supplied, str) or supplied != sha256_json(unsigned):
        raise ChallengerDossierError("challenger admission digest is invalid")
    if payload.get("source_ledger_sha256") != ledger.get("content_sha256"):
        raise ChallengerDossierError("challenger admission is bound to another ledger")
    if payload.get("category_count") != 13 or payload.get("reference_product_row_count") != 130:
        raise ChallengerDossierError("challenger admission coverage drifted")
    if payload.get("automatic_pairing_enabled") is not False or payload.get("four_a_quality_proven") is not False:
        raise ChallengerDossierError("challenger admission escaped its authority boundary")
    for category in payload.get("categories", []):
        dossier = category.get("dossier", {})
        path = _inside(project_root / str(dossier.get("project_relative_path", "")), project_root)
        if path.stat().st_size != dossier.get("bytes") or sha256_file(path) != dossier.get("sha256"):
            raise ChallengerDossierError("challenger dossier binding drifted")
    return payload


def admitted_dossier_for_category(
    payload: Mapping[str, Any], *, category_id: str, project_root: Path
) -> Path:
    category = next((item for item in payload.get("categories", []) if item.get("category_id") == category_id), None)
    if category is None:
        raise ChallengerDossierError("challenger category admission is missing")
    if category.get("named_product_pk_preparation_admitted") is not True or category.get("blocking_gap_count") != 0:
        raise ChallengerDossierError("challenger category has unresolved same-brief material gaps")
    return _inside(project_root / category["dossier"]["project_relative_path"], project_root)
