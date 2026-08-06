from __future__ import annotations

from collections import defaultdict
import hashlib
import json
import re
import unicodedata
from typing import Any, Mapping, Sequence
from urllib.parse import urlparse


SCHEMA = "ProofLaunchGTMCaseIdentityResolutionLedgerV2"


class GTMCaseIdentityResolutionError(ValueError):
    """A duplicate, ambiguous entity, or unsealed identity escaped the case funnel."""


_LEGAL_SUFFIXES = {
    "ag", "co", "company", "corp", "corporation", "gmbh", "group", "inc",
    "incorporated", "limited", "llc", "llp", "ltd", "plc", "pty", "sa",
}
_GENERIC_HOST_PREFIXES = {"www", "blog", "news", "stories"}


def _digest(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    ).hexdigest()


def _normalize_text(value: Any) -> str:
    text = unicodedata.normalize("NFKD", str(value or "")).encode("ascii", "ignore").decode("ascii")
    tokens = re.findall(r"[a-z0-9]+", text.casefold())
    while tokens and tokens[-1] in _LEGAL_SUFFIXES:
        tokens.pop()
    return " ".join(tokens)


def _canonical_domain(value: Any) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    parsed = urlparse(raw if "://" in raw else f"https://{raw}")
    host = (parsed.hostname or "").casefold().rstrip(".")
    labels = host.split(".")
    if labels and labels[0] in _GENERIC_HOST_PREFIXES:
        labels = labels[1:]
    return ".".join(labels)


def _stable_key(prefix: str, *parts: str) -> str:
    material = "\x1f".join(parts)
    return f"{prefix}-{hashlib.sha256(material.encode('utf-8')).hexdigest()[:24]}"


def _token_jaccard(left: str, right: str) -> float:
    a, b = set(left.split()), set(right.split())
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def _required(row: Mapping[str, Any], field: str) -> str:
    value = str(row.get(field) or "").strip()
    if not value:
        raise GTMCaseIdentityResolutionError(f"{field} is required")
    return value


def compile_case_identity_resolution(
    records: Sequence[Mapping[str, Any]],
    *,
    fuzzy_threshold: float = 0.84,
) -> dict[str, Any]:
    """Resolve entity and episode identity without granting new evidence credit.

    Exact episode mirrors are collapsed deterministically. Fuzzy similarities are
    review flags only: they never auto-merge and never earn quota credit.
    """
    if not 0.75 <= fuzzy_threshold <= 0.98:
        raise GTMCaseIdentityResolutionError("fuzzy_threshold must be in [0.75, 0.98]")

    prepared: list[dict[str, Any]] = []
    record_ids: set[str] = set()
    for source in records:
        record_id = _required(source, "record_id")
        if record_id in record_ids:
            raise GTMCaseIdentityResolutionError(f"duplicate record_id: {record_id}")
        record_ids.add(record_id)
        company = _required(source, "company")
        product = _required(source, "product")
        motion = _required(source, "campaign_or_motion")
        market = _required(source, "primary_market")
        observed_start = _required(source, "observed_start")
        observed_end = _required(source, "observed_end")
        normalized_company = _normalize_text(company)
        normalized_product = _normalize_text(product)
        normalized_motion = _normalize_text(motion)
        domain = _canonical_domain(source.get("company_domain"))
        entity_basis = f"domain:{domain}" if domain else f"name:{normalized_company}"
        entity_key = _stable_key("entity", entity_basis)
        episode_key = _stable_key(
            "episode", entity_key, normalized_product, normalized_motion,
            _normalize_text(market), observed_start, observed_end,
        )
        prepared.append({
            "record_id": record_id,
            "company": company,
            "company_domain": domain,
            "normalized_company": normalized_company,
            "entity_key": entity_key,
            "product": product,
            "normalized_product": normalized_product,
            "campaign_or_motion": motion,
            "normalized_campaign_or_motion": normalized_motion,
            "primary_market": market,
            "observed_start": observed_start,
            "observed_end": observed_end,
            "episode_key": episode_key,
            "source_urls": sorted({str(url) for url in source.get("source_urls", []) if str(url).strip()}),
            "input_quota_credit": int(source.get("quota_credit", 0)),
        })

    by_episode: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in prepared:
        by_episode[row["episode_key"]].append(row)

    resolved: list[dict[str, Any]] = []
    mirror_groups: list[dict[str, Any]] = []
    for episode_key, group in sorted(by_episode.items()):
        ordered = sorted(group, key=lambda row: row["record_id"])
        primary_id = ordered[0]["record_id"]
        if len(ordered) > 1:
            mirror_groups.append({
                "episode_key": episode_key,
                "primary_record_id": primary_id,
                "mirror_record_ids": [row["record_id"] for row in ordered[1:]],
                "cross_platform_mirrors_count_once": True,
            })
        for index, row in enumerate(ordered):
            resolved.append({
                **row,
                "resolution_status": "unique_primary" if index == 0 else "exact_episode_mirror",
                "primary_record_id": primary_id,
                "resolved_quota_credit": row["input_quota_credit"] if index == 0 else 0,
            })

    fuzzy_flags: list[dict[str, Any]] = []
    primaries = [row for row in resolved if row["resolution_status"] == "unique_primary"]
    for left_index, left in enumerate(primaries):
        for right in primaries[left_index + 1:]:
            same_entity = left["entity_key"] == right["entity_key"]
            if not same_entity:
                continue
            product_similarity = _token_jaccard(left["normalized_product"], right["normalized_product"])
            motion_similarity = _token_jaccard(
                left["normalized_campaign_or_motion"], right["normalized_campaign_or_motion"]
            )
            if max(product_similarity, motion_similarity) >= fuzzy_threshold:
                fuzzy_flags.append({
                    "left_record_id": left["record_id"],
                    "right_record_id": right["record_id"],
                    "entity_key": left["entity_key"],
                    "product_jaccard": round(product_similarity, 6),
                    "motion_jaccard": round(motion_similarity, 6),
                    "decision": "manual_review_required",
                    "automatic_merge_allowed": False,
                })

    payload: dict[str, Any] = {
        "schema": SCHEMA,
        "record_count": len(resolved),
        "unique_entity_count": len({row["entity_key"] for row in resolved}),
        "unique_episode_count": len(by_episode),
        "exact_mirror_count": sum(len(group) - 1 for group in by_episode.values()),
        "fuzzy_review_count": len(fuzzy_flags),
        "fuzzy_threshold": fuzzy_threshold,
        "records": sorted(resolved, key=lambda row: row["record_id"]),
        "exact_mirror_groups": mirror_groups,
        "fuzzy_review_flags": fuzzy_flags,
        "promotion_policy": {
            "exact_episode_mirror_quota_credit": 0,
            "fuzzy_match_auto_merge_allowed": False,
            "fuzzy_match_auto_promotion_allowed": False,
            "unresolved_entity_auto_promotion_allowed": False,
        },
        "truth_boundary": (
            "This ledger resolves identity and suppresses exact mirrors. It does not prove claims, causality, budget, "
            "recency, or transferability and cannot create candidate quota credit."
        ),
    }
    payload["content_sha256"] = _digest(payload)
    return payload


def verify_case_identity_resolution(payload: Mapping[str, Any]) -> None:
    unsigned = dict(payload)
    supplied = unsigned.pop("content_sha256", None)
    if payload.get("schema") != SCHEMA or supplied != _digest(unsigned):
        raise GTMCaseIdentityResolutionError("identity resolution seal is invalid")
    records = payload.get("records")
    if not isinstance(records, list) or payload.get("record_count") != len(records):
        raise GTMCaseIdentityResolutionError("identity record aggregate drifted")
    ids = [row.get("record_id") for row in records]
    if len(ids) != len(set(ids)):
        raise GTMCaseIdentityResolutionError("record identities are duplicated")
    primary_episodes = [
        row.get("episode_key") for row in records if row.get("resolution_status") == "unique_primary"
    ]
    if len(primary_episodes) != len(set(primary_episodes)):
        raise GTMCaseIdentityResolutionError("more than one primary survived for an episode")
    for row in records:
        if row.get("resolution_status") == "exact_episode_mirror" and row.get("resolved_quota_credit") != 0:
            raise GTMCaseIdentityResolutionError("an exact mirror retained quota credit")
        if row.get("resolved_quota_credit", 0) > row.get("input_quota_credit", 0):
            raise GTMCaseIdentityResolutionError("identity resolution minted quota credit")
    if payload.get("exact_mirror_count") != sum(
        1 for row in records if row.get("resolution_status") == "exact_episode_mirror"
    ):
        raise GTMCaseIdentityResolutionError("exact mirror aggregate drifted")


__all__ = [
    "GTMCaseIdentityResolutionError",
    "compile_case_identity_resolution",
    "verify_case_identity_resolution",
]
