from __future__ import annotations

import hashlib
import ipaddress
import json
import re
from datetime import datetime
from typing import Mapping
from urllib.parse import parse_qs, urlparse


class ManualPublicationReceiptError(ValueError):
    """A claimed manual publication could not be bound to an approved asset."""


_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_SOURCE_KINDS = frozenset({"official_platform_receipt", "operator_attestation"})


def _canonical(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _safe_id(value: object, label: str) -> str:
    if not isinstance(value, str) or not _SAFE_ID.fullmatch(value):
        raise ManualPublicationReceiptError(f"{label} is invalid")
    return value


def _sha(value: object, label: str) -> str:
    if not isinstance(value, str) or not _SHA256.fullmatch(value):
        raise ManualPublicationReceiptError(f"{label} is invalid")
    return value


def _public_https_url(value: object, expected_tags: Mapping[str, str]) -> str:
    if not isinstance(value, str) or len(value) > 2048:
        raise ManualPublicationReceiptError("public_url is invalid")
    parsed = urlparse(value)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.fragment
    ):
        raise ManualPublicationReceiptError(
            "public_url must be credential-free public HTTPS without a fragment"
        )
    hostname = parsed.hostname.lower().rstrip(".")
    if hostname == "localhost" or hostname.endswith(".localhost"):
        raise ManualPublicationReceiptError("public_url cannot target localhost")
    try:
        address = ipaddress.ip_address(hostname)
    except ValueError:
        address = None
    if address is not None and not address.is_global:
        raise ManualPublicationReceiptError("public_url cannot target a private IP")
    query = parse_qs(parsed.query, keep_blank_values=True, strict_parsing=False)
    for key, expected in expected_tags.items():
        values = query.get(key)
        if values != [expected]:
            raise ManualPublicationReceiptError(
                f"public_url must contain the exact candidate attribution tag {key}"
            )
    return value


def compile_manual_publication_receipt(
    payload: Mapping[str, object],
    *,
    run_id: str,
    campaign_id: str,
    experiment_id: str,
    strategy_plan_sha256: str,
    attribution_plan_sha256: str,
    candidate_tags: Mapping[str, str],
    allowed_assets: Mapping[str, str],
    authenticated_operator: str,
) -> dict[str, object]:
    """Compile an operator-attested receipt without performing publication."""

    receipt_id = _safe_id(payload.get("receipt_id"), "receipt_id")
    channel = _safe_id(payload.get("channel"), "channel")
    asset_name = _safe_id(payload.get("asset_name"), "asset_name")
    expected_asset_sha256 = allowed_assets.get(asset_name)
    if expected_asset_sha256 is None:
        raise ManualPublicationReceiptError("asset_name is not an approved workspace asset")
    supplied_asset_sha256 = _sha(payload.get("asset_sha256"), "asset_sha256")
    if supplied_asset_sha256 != expected_asset_sha256:
        raise ManualPublicationReceiptError("asset_sha256 does not match the approved asset")
    source_kind = payload.get("source_kind")
    if source_kind not in _SOURCE_KINDS:
        raise ManualPublicationReceiptError("source_kind is unsupported")
    source_reference_sha256 = _sha(
        payload.get("source_reference_sha256"), "source_reference_sha256"
    )
    published_at = payload.get("published_at")
    if not isinstance(published_at, str):
        raise ManualPublicationReceiptError("published_at is invalid")
    try:
        timestamp = datetime.fromisoformat(published_at.replace("Z", "+00:00"))
    except ValueError as error:
        raise ManualPublicationReceiptError("published_at must be ISO-8601") from error
    if timestamp.tzinfo is None or timestamp.utcoffset() is None:
        raise ManualPublicationReceiptError("published_at must be timezone-aware")
    if payload.get("operator_attested") is not True:
        raise ManualPublicationReceiptError("operator_attested must be true")
    if not authenticated_operator.strip():
        raise ManualPublicationReceiptError("authenticated operator is missing")
    tags = {
        key: _safe_id(value, f"candidate_tags.{key}")
        for key, value in candidate_tags.items()
    }
    public_url = _public_https_url(payload.get("public_url"), tags)
    core: dict[str, object] = {
        "schema": "ProofLaunchManualPublicationReceiptV1",
        "receipt_id": receipt_id,
        "run_id": _safe_id(run_id, "run_id"),
        "campaign_id": _safe_id(campaign_id, "campaign_id"),
        "experiment_id": _safe_id(experiment_id, "experiment_id"),
        "strategy_plan_sha256": _sha(
            strategy_plan_sha256, "strategy_plan_sha256"
        ),
        "attribution_plan_sha256": _sha(
            attribution_plan_sha256, "attribution_plan_sha256"
        ),
        "arm": "candidate",
        "channel": channel,
        "asset_name": asset_name,
        "asset_sha256": supplied_asset_sha256,
        "public_url": public_url,
        "published_at": timestamp.isoformat(),
        "source_kind": source_kind,
        "source_reference_sha256": source_reference_sha256,
        "operator_attested": True,
        "operator_identity": authenticated_operator.strip(),
        "attribution_tags": tags,
        "publication_performed_by_prooflaunch": False,
        "platform_delivery_verified": False,
        "credentials_persisted": False,
        "effect_claim_eligible": False,
        "causal_revenue_claim_eligible": False,
        "truth_boundary": (
            "This append-only receipt binds a named operator attestation or hashed official "
            "platform receipt to one approved candidate asset and exact attribution tags. "
            "ProofLaunch did not publish the asset, does not verify platform delivery from "
            "the URL alone, and does not infer effectiveness, causality, revenue lift, or 4A quality."
        ),
    }
    receipt = dict(core)
    receipt["content_sha256"] = hashlib.sha256(_canonical(core)).hexdigest()
    return receipt
