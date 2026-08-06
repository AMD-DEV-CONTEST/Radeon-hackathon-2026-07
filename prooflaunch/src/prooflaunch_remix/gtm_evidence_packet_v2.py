from __future__ import annotations

import hashlib
import json
import re
from typing import Any, Mapping, Sequence


SCHEMA = "ProofLaunchGTMEvidencePacketLedgerV2"
SURFACES = (
    "engagement_thread",
    "edit_history",
    "cta",
    "landing_page",
    "follow_up_content",
)
STATUSES = {"observed", "not_publicly_available", "not_applicable"}
FORBIDDEN_PERSONAL_OR_RAW_KEYS = {
    "author_name",
    "author_handle",
    "email",
    "phone",
    "raw_text",
    "raw_voice",
}
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class GTMEvidencePacketError(ValueError):
    pass


def _digest(value: Any) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode()
    return hashlib.sha256(encoded).hexdigest()


def _is_sha256(value: Any) -> bool:
    return bool(SHA256_RE.fullmatch(str(value or "")))


def _find_forbidden_keys(value: Any, path: str = "$") -> list[str]:
    findings: list[str] = []
    if isinstance(value, Mapping):
        for key, child in value.items():
            child_path = f"{path}.{key}"
            if str(key) in FORBIDDEN_PERSONAL_OR_RAW_KEYS:
                findings.append(child_path)
            findings.extend(_find_forbidden_keys(child, child_path))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            findings.extend(_find_forbidden_keys(child, f"{path}[{index}]"))
    return findings


def _surface_status(raw: Any) -> str:
    if not isinstance(raw, Mapping):
        return "not_publicly_available"
    status = str(raw.get("status") or "not_publicly_available")
    if status not in STATUSES:
        raise GTMEvidencePacketError(f"unsupported evidence-surface status: {status}")
    return status


def _normalize_surface(name: str, raw: Any) -> dict[str, Any]:
    source = dict(raw) if isinstance(raw, Mapping) else {}
    status = _surface_status(source)
    output: dict[str, Any] = {
        "status": status,
        "availability_reason": str(
            source.get("availability_reason")
            or ("Captured from an ordinary public surface." if status == "observed" else "The bounded public capture did not expose this surface.")
        ),
    }
    if name == "engagement_thread":
        output["comments"] = list(source.get("comments") or []) if status == "observed" else []
    elif name == "edit_history":
        output["versions"] = list(source.get("versions") or []) if status == "observed" else []
    elif name == "cta":
        output.update({key: source.get(key) for key in ("text_sha256", "target_url", "action_type")})
    elif name == "landing_page":
        output.update({
            key: source.get(key)
            for key in (
                "source_url",
                "captured_at",
                "content_sha256",
                "claim_summary_sha256",
                "offer_summary_sha256",
                "form_path_summary_sha256",
            )
        })
    elif name == "follow_up_content":
        output["items"] = list(source.get("items") or []) if status == "observed" else []
    return output


def _validate_observed_surface(name: str, surface: Mapping[str, Any], packet_id: str) -> None:
    if surface["status"] != "observed":
        return
    if name == "engagement_thread":
        comments = surface.get("comments")
        if not isinstance(comments, list) or not comments:
            raise GTMEvidencePacketError(f"{packet_id} observed engagement thread has no comments")
        for row in comments:
            if not all(_is_sha256(row.get(key)) for key in ("comment_id_sha256", "content_sha256")):
                raise GTMEvidencePacketError(f"{packet_id} comment fingerprints are incomplete")
            if not row.get("published_at") or row.get("edit_status") not in {"unedited", "edited", "unknown"}:
                raise GTMEvidencePacketError(f"{packet_id} comment chronology is incomplete")
    elif name == "edit_history":
        versions = surface.get("versions")
        if not isinstance(versions, list) or not versions:
            raise GTMEvidencePacketError(f"{packet_id} observed edit history has no versions")
        for row in versions:
            if not row.get("version_id") or not row.get("captured_at") or not _is_sha256(row.get("content_sha256")):
                raise GTMEvidencePacketError(f"{packet_id} edit version is incomplete")
    elif name == "cta":
        if not _is_sha256(surface.get("text_sha256")) or not str(surface.get("target_url") or "").startswith("https://") or not surface.get("action_type"):
            raise GTMEvidencePacketError(f"{packet_id} observed CTA is incomplete")
    elif name == "landing_page":
        if not str(surface.get("source_url") or "").startswith("https://") or not surface.get("captured_at"):
            raise GTMEvidencePacketError(f"{packet_id} observed landing page lacks URL or timestamp")
        hash_fields = ("content_sha256", "claim_summary_sha256", "offer_summary_sha256", "form_path_summary_sha256")
        if not all(_is_sha256(surface.get(key)) for key in hash_fields):
            raise GTMEvidencePacketError(f"{packet_id} observed landing-page fingerprints are incomplete")
    elif name == "follow_up_content":
        items = surface.get("items")
        if not isinstance(items, list) or not items:
            raise GTMEvidencePacketError(f"{packet_id} observed follow-up surface has no items")
        for row in items:
            if not str(row.get("source_url") or "").startswith("https://") or not row.get("relationship_type") or not row.get("published_at") or not _is_sha256(row.get("content_sha256")):
                raise GTMEvidencePacketError(f"{packet_id} follow-up evidence is incomplete")


def compile_evidence_packets(records: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    packets: list[dict[str, Any]] = []
    packet_ids: set[str] = set()
    for raw in records:
        packet_id = str(raw.get("packet_id") or "")
        source_url = str(raw.get("source_url") or "")
        if not packet_id or packet_id in packet_ids or not source_url.startswith("https://"):
            raise GTMEvidencePacketError("packets require unique IDs and public HTTPS sources")
        packet_ids.add(packet_id)
        if any(bool(raw.get(key)) for key in ("authentication_used", "captcha_bypass_used", "paywall_bypass_used")):
            raise GTMEvidencePacketError(f"{packet_id} used a forbidden access method")
        if not _is_sha256(raw.get("primary_content_sha256")):
            raise GTMEvidencePacketError(f"{packet_id} lacks a primary content fingerprint")
        rights = dict(raw.get("rights") or {})
        required_rights = ("publicity_status", "license_status", "permitted_use", "retention_boundary")
        if any(not rights.get(key) for key in required_rights):
            raise GTMEvidencePacketError(f"{packet_id} rights and retention boundary are incomplete")
        surfaces_raw = raw.get("surfaces") if isinstance(raw.get("surfaces"), Mapping) else {}
        surfaces = {name: _normalize_surface(name, surfaces_raw.get(name)) for name in SURFACES}
        for name, surface in surfaces.items():
            _validate_observed_surface(name, surface, packet_id)
        forbidden = _find_forbidden_keys(surfaces)
        if forbidden:
            raise GTMEvidencePacketError(f"{packet_id} retains forbidden personal/raw fields: {', '.join(forbidden)}")
        blockers = [
            f"{name}:{surface['status']}"
            for name, surface in surfaces.items()
            if surface["status"] != "observed"
        ]
        packets.append({
            "packet_id": packet_id,
            "source_url": source_url,
            "source_class": str(raw.get("source_class") or "unknown"),
            "access_method": str(raw.get("access_method") or "ordinary_public_page"),
            "captured_at": str(raw.get("captured_at") or ""),
            "primary_content_sha256": str(raw["primary_content_sha256"]),
            "rights": rights,
            "surfaces": surfaces,
            "coverage_blockers": blockers,
            "surface_coverage_count": sum(surface["status"] == "observed" for surface in surfaces.values()),
            "complete_surface_coverage": not blockers,
            "quota_credit": 0,
        })
    status_counts = {
        name: {
            status: sum(packet["surfaces"][name]["status"] == status for packet in packets)
            for status in sorted(STATUSES)
        }
        for name in SURFACES
    }
    payload: dict[str, Any] = {
        "schema": SCHEMA,
        "packet_count": len(packets),
        "complete_packet_count": sum(row["complete_surface_coverage"] for row in packets),
        "surface_status_counts": status_counts,
        "packets": sorted(packets, key=lambda row: row["packet_id"]),
        "policy": {
            "ordinary_public_access_only": True,
            "authentication_captcha_or_paywall_bypass_allowed": False,
            "raw_personal_identity_or_voice_retention_allowed": False,
            "missing_surface_must_be_explicit": True,
            "packet_alone_grants_case_or_outcome_credit": False,
        },
        "truth_boundary": "The packet preserves inspectable public-source fingerprints and explicit surface gaps. It does not establish causality, budget, outcome, or case quota credit.",
    }
    payload["content_sha256"] = _digest(payload)
    return payload


def verify_evidence_packets(payload: Mapping[str, Any]) -> None:
    unsigned = dict(payload)
    supplied = unsigned.pop("content_sha256", None)
    if payload.get("schema") != SCHEMA or supplied != _digest(unsigned):
        raise GTMEvidencePacketError("evidence packet ledger seal is invalid")
    packets = payload.get("packets")
    if not isinstance(packets, list) or payload.get("packet_count") != len(packets):
        raise GTMEvidencePacketError("evidence packet aggregate drifted")
    if any(row.get("quota_credit") != 0 for row in packets):
        raise GTMEvidencePacketError("evidence packets minted quota credit")
    for packet in packets:
        surfaces = packet.get("surfaces")
        if not isinstance(surfaces, Mapping) or set(surfaces) != set(SURFACES):
            raise GTMEvidencePacketError("a packet omits a required surface")
        expected = sum(surface.get("status") == "observed" for surface in surfaces.values())
        if packet.get("surface_coverage_count") != expected:
            raise GTMEvidencePacketError("surface coverage aggregate drifted")
    if payload.get("complete_packet_count") != sum(row.get("complete_surface_coverage") is True for row in packets):
        raise GTMEvidencePacketError("complete packet aggregate drifted")


__all__ = [
    "GTMEvidencePacketError",
    "SCHEMA",
    "SURFACES",
    "compile_evidence_packets",
    "verify_evidence_packets",
]
