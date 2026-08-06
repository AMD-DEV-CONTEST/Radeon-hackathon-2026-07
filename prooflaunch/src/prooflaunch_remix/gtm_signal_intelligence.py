from __future__ import annotations

import hashlib
import json
from collections import Counter, defaultdict
from datetime import datetime
from typing import Any, Mapping
from urllib.parse import urlparse

from .gtm_creative_alpha import CreativeAlphaError, compile_growth_case_radar
from .ledger import canonical_json


class SignalIntelligenceError(ValueError):
    """An untrusted or rights-unsafe creative signal snapshot was rejected."""


_SOURCE_KINDS = frozenset(
    {
        "official_platform_api",
        "authorized_connector",
        "authorized_open_source_collector",
        "first_party_analytics",
        "public_trend_feed",
    }
)
_RIGHTS = frozenset(
    {"owned", "licensed", "public_measurement", "account_authorized"}
)
_FORBIDDEN_RAW_FIELDS = frozenset(
    {
        "caption",
        "script",
        "transcript",
        "creative_text",
        "raw_text",
        "media_url",
        "download_url",
        "user_id",
        "username",
        "email",
        "phone",
    }
)

# Public platform counters regularly exceed one million. Keep the original
# narrow bound for rates, scores and arbitrary measurements; widen only the
# non-negative count metrics emitted by admitted read-only collectors.
_PUBLIC_COUNT_METRIC_MAX = {
    "view_count": 1_000_000_000_000,
    "like_count": 1_000_000_000_000,
    "comment_count": 1_000_000_000_000,
    "reply_count": 1_000_000_000_000,
    "repost_count": 1_000_000_000_000,
    "quote_count": 1_000_000_000_000,
    "follower_count": 1_000_000_000_000,
    "item_count": 1_000_000_000,
    "enclosure_count": 1_000_000_000,
    "timestamped_item_count": 1_000_000_000,
}


def _bounded(value: object, name: str, maximum: int = 300) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        raise SignalIntelligenceError(f"{name} must be a non-empty bounded string")
    if "\x00" in value:
        raise SignalIntelligenceError(f"{name} contains a NUL byte")
    return value.strip()


def _timestamp(value: object, name: str) -> str:
    text = _bounded(value, name, 64)
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as error:
        raise SignalIntelligenceError(f"{name} must be ISO-8601") from error
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise SignalIntelligenceError(f"{name} must include a timezone")
    return text


def _source_reference(uri: object) -> tuple[str, str]:
    text = _bounded(uri, "source_uri", 2_000)
    parsed = urlparse(text)
    if parsed.scheme not in {"https", "http"} or not parsed.netloc:
        raise SignalIntelligenceError("source_uri must be an absolute HTTP(S) URI")
    return parsed.netloc.casefold(), hashlib.sha256(text.encode("utf-8")).hexdigest()


def compile_signal_intelligence(payload: Mapping[str, Any]) -> dict[str, object]:
    """Reduce authorized measurement into non-copying creative hypotheses.

    Raw captions, scripts, media URLs and user-level identifiers are rejected.
    The returned artifact contains aggregates and source hashes only, so it can
    inform experiments without becoming an unauthorized creative corpus.
    """

    if not isinstance(payload, Mapping):
        raise SignalIntelligenceError("creative signal snapshot must be an object")
    if payload.get("schema") != "ProofLaunchCreativeSignalSnapshotV1":
        raise SignalIntelligenceError("creative signal snapshot schema is unsupported")
    if payload.get("contains_personal_data") is not False:
        raise SignalIntelligenceError("signal snapshot must explicitly contain no PII")
    if payload.get("contains_copied_creative") is not False:
        raise SignalIntelligenceError(
            "signal snapshot must explicitly contain no copied creative"
        )
    captured_at = _timestamp(payload.get("captured_at"), "captured_at")
    purpose = _bounded(payload.get("purpose"), "purpose", 200)
    retention_days = payload.get("retention_days")
    if type(retention_days) is not int or not 1 <= retention_days <= 365:
        raise SignalIntelligenceError("retention_days must be an integer in [1, 365]")
    signals = payload.get("signals")
    if not isinstance(signals, list) or not 1 <= len(signals) <= 500:
        raise SignalIntelligenceError("signals must contain between 1 and 500 rows")

    ids: set[str] = set()
    platforms: Counter[str] = Counter()
    patterns: Counter[str] = Counter()
    metrics: dict[str, list[float]] = defaultdict(list)
    sources: list[dict[str, object]] = []
    for index, row in enumerate(signals):
        if not isinstance(row, Mapping):
            raise SignalIntelligenceError(f"signals[{index}] must be an object")
        forbidden = _FORBIDDEN_RAW_FIELDS & set(row)
        if forbidden:
            raise SignalIntelligenceError(
                "raw creative or personal fields are forbidden: "
                + ", ".join(sorted(forbidden))
            )
        signal_id = _bounded(row.get("signal_id"), f"signals[{index}].signal_id", 128)
        if signal_id in ids:
            raise SignalIntelligenceError("signal_id values must be unique")
        ids.add(signal_id)
        platform = _bounded(row.get("platform"), f"signals[{index}].platform", 120)
        source_kind = _bounded(row.get("source_kind"), "source_kind", 80)
        rights = _bounded(row.get("rights"), "rights", 80)
        if source_kind not in _SOURCE_KINDS:
            raise SignalIntelligenceError("signal source is not authorized")
        if rights not in _RIGHTS:
            raise SignalIntelligenceError("signal rights are unsupported")
        observed_at = _timestamp(row.get("observed_at"), "observed_at")
        source_host, source_sha256 = _source_reference(row.get("source_uri"))
        metric = _bounded(row.get("metric"), "metric", 120)
        value = row.get("value")
        metric_maximum = _PUBLIC_COUNT_METRIC_MAX.get(metric)
        valid_value = type(value) in {int, float}
        if metric_maximum is not None:
            valid_value = valid_value and 0 <= float(value) <= metric_maximum
        else:
            valid_value = valid_value and -1_000_000 <= float(value) <= 1_000_000
        if not valid_value:
            raise SignalIntelligenceError("signal metric value is invalid")
        sample_size = row.get("sample_size")
        if type(sample_size) is not int or not 1 <= sample_size <= 1_000_000_000:
            raise SignalIntelligenceError("sample_size must be a positive integer")
        features = row.get("format_features")
        if not isinstance(features, list) or not 1 <= len(features) <= 12:
            raise SignalIntelligenceError("format_features must contain 1 to 12 labels")
        normalized_features: list[str] = []
        for feature in features:
            normalized = _bounded(feature, "format_feature", 80).casefold()
            normalized_features.append(normalized)
            patterns[normalized] += 1
        platforms[platform] += 1
        metrics[metric].append(float(value))
        sources.append(
            {
                "signal_id": signal_id,
                "platform": platform,
                "source_kind": source_kind,
                "source_host": source_host,
                "source_uri_sha256": source_sha256,
                "rights": rights,
                "observed_at": observed_at,
                "sample_size": sample_size,
                "format_feature_count": len(normalized_features),
            }
        )

    enough_for_hypotheses = len(signals) >= 5 and len(platforms) >= 2
    top_patterns = [
        {"feature": feature, "observations": count}
        for feature, count in sorted(
            patterns.items(), key=lambda item: (-item[1], item[0])
        )[:10]
    ]
    metric_summaries = [
        {
            "metric": metric,
            "observation_count": len(values),
            "unweighted_mean": sum(values) / len(values),
            "minimum": min(values),
            "maximum": max(values),
        }
        for metric, values in sorted(metrics.items())
    ]
    hypotheses = (
        [
            {
                "hypothesis_id": f"format-{index:02d}",
                "feature": item["feature"],
                "statement": (
                    f"Test the abstract format feature '{item['feature']}' against a "
                    "frozen control using the preregistered channel metric."
                ),
                "status": "untested",
            }
            for index, item in enumerate(top_patterns[:3], start=1)
        ]
        if enough_for_hypotheses
        else []
    )
    growth_cases = payload.get("growth_cases")
    if growth_cases is None:
        growth_case_radar: dict[str, object] = {
            "schema": "ProofLaunchGrowthCaseRadarV1",
            "status": "not_supplied",
            "case_count": 0,
            "eligible_case_count": 0,
            "cells": [],
            "copied_creative_retained": False,
            "automatic_strategy_mutation_executed": False,
        }
    else:
        if not isinstance(growth_cases, list):
            raise SignalIntelligenceError("growth_cases must be a list when supplied")
        try:
            growth_case_radar = compile_growth_case_radar(
                growth_cases,
                as_of=captured_at,
            )
        except CreativeAlphaError as error:
            raise SignalIntelligenceError(
                f"growth-case radar safety gate failed: {error}"
            ) from error
    snapshot_sha256 = hashlib.sha256(
        canonical_json(payload).encode("utf-8")
    ).hexdigest()
    return {
        "schema": "ProofLaunchCreativeSignalIntelligenceV1",
        "source_snapshot_sha256": snapshot_sha256,
        "captured_at": captured_at,
        "purpose": purpose,
        "retention_days": retention_days,
        "signal_count": len(signals),
        "platform_counts": dict(sorted(platforms.items())),
        "top_abstract_format_patterns": top_patterns,
        "metric_summaries": metric_summaries,
        "source_evidence": sources,
        "hypotheses": hypotheses,
        "growth_case_radar": growth_case_radar,
        "evidence_sufficient_for_hypothesis_generation": enough_for_hypotheses,
        "strategy_mutation_executed": False,
        "human_review_required_before_strategy_mutation": True,
        "copied_creative_retained": False,
        "personal_data_retained": False,
        "truth_boundary": (
            "This artifact contains authorized aggregate measurements and abstract "
            "format hypotheses only. It does not reproduce source creative, prove "
            "causality, authorize publication, or claim superior GTM effect."
        ),
    }


def empty_signal_intelligence() -> dict[str, object]:
    return {
        "schema": "ProofLaunchCreativeSignalIntelligenceV1",
        "status": "not_supplied",
        "signal_count": 0,
        "platform_counts": {},
        "top_abstract_format_patterns": [],
        "metric_summaries": [],
        "source_evidence": [],
        "hypotheses": [],
        "growth_case_radar": {
            "schema": "ProofLaunchGrowthCaseRadarV1",
            "status": "not_supplied",
            "case_count": 0,
            "eligible_case_count": 0,
            "cells": [],
            "copied_creative_retained": False,
            "automatic_strategy_mutation_executed": False,
        },
        "evidence_sufficient_for_hypothesis_generation": False,
        "strategy_mutation_executed": False,
        "human_review_required_before_strategy_mutation": True,
        "copied_creative_retained": False,
        "personal_data_retained": False,
        "truth_boundary": (
            "No authorized platform signal snapshot was supplied; the strategy was "
            "not modified using platform trend data."
        ),
    }


def parse_and_compile_signal_intelligence(raw: bytes) -> dict[str, object]:
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise SignalIntelligenceError("signal snapshot must be valid UTF-8 JSON") from error
    return compile_signal_intelligence(payload)
