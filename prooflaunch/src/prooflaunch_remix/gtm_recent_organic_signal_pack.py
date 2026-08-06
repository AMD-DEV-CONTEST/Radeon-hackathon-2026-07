from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping

from .ledger import canonical_json
from .gtm_organic_signal_sampling_standard import (
    OrganicSignalSamplingStandardError,
    verify_global_organic_signal_sampling_standard,
)


SCHEMA = "ProofLaunchRecentOrganicSignalPackV1"


class RecentOrganicSignalPackError(ValueError):
    pass


def _load_object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise RecentOrganicSignalPackError(f"invalid evidence artifact: {path.name}") from error
    if not isinstance(value, dict):
        raise RecentOrganicSignalPackError(f"evidence artifact must be an object: {path.name}")
    return value


def _parse_timestamp(value: object) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed.astimezone(timezone.utc)


def _sha_without_field(value: Mapping[str, Any], field: str) -> str:
    return hashlib.sha256(
        canonical_json({key: item for key, item in value.items() if key != field}).encode("utf-8")
    ).hexdigest()


def compile_recent_organic_signal_pack(
    collection_dir: str | Path,
    *,
    maximum_age_days: int = 180,
    preferred_age_days: int = 90,
    sampling_standard: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Compile rights-safe public collection receipts into a frontier-agent context.

    This layer never promotes raw source text into prompts or training. It binds only
    freshness, public counters and abstract format features already admitted by the
    collection runner.
    """

    if not 30 <= preferred_age_days <= maximum_age_days <= 365:
        raise RecentOrganicSignalPackError("freshness windows must satisfy 30 <= preferred <= maximum <= 365")
    root = Path(collection_dir).resolve()
    if sampling_standard is not None:
        try:
            verify_global_organic_signal_sampling_standard(sampling_standard)
        except OrganicSignalSamplingStandardError as error:
            raise RecentOrganicSignalPackError("organic sampling standard is invalid") from error
    receipt = _load_object(root / "collection-receipt.json")
    plan = _load_object(root / "collection-plan.json")
    intelligence = _load_object(root / "creative-signal-intelligence.json")
    if receipt.get("schema") != "ProofLaunchOpenSourceSocialCollectionRunV2":
        raise RecentOrganicSignalPackError("unsupported collection receipt")
    if receipt.get("status") not in {"completed", "completed_with_handoffs", "human_handoff_required"}:
        raise RecentOrganicSignalPackError("collection status is unsupported")
    if receipt.get("training_admitted") is not False:
        raise RecentOrganicSignalPackError("collection must not admit raw content to training")
    if receipt.get("receipt_sha256") != _sha_without_field(receipt, "receipt_sha256"):
        raise RecentOrganicSignalPackError("collection receipt digest mismatch")
    if receipt.get("plan_sha256") != plan.get("plan_sha256"):
        raise RecentOrganicSignalPackError("collection plan binding mismatch")
    expected_intelligence_sha = hashlib.sha256(canonical_json(intelligence).encode("utf-8")).hexdigest()
    if receipt.get("creative_signal_intelligence_sha256") != expected_intelligence_sha:
        raise RecentOrganicSignalPackError("signal intelligence digest mismatch")

    captured = _parse_timestamp(receipt.get("captured_at"))
    if captured is None:
        raise RecentOrganicSignalPackError("collection capture time is invalid")
    preferred_cutoff = captured - timedelta(days=preferred_age_days)
    maximum_cutoff = captured - timedelta(days=maximum_age_days)
    plan_rows = plan.get("plans")
    runs = receipt.get("runs")
    if not isinstance(plan_rows, list) or not isinstance(runs, list) or len(plan_rows) != len(runs):
        raise RecentOrganicSignalPackError("collection source ledger is inconsistent")

    sources: list[dict[str, Any]] = []
    preferred_count = 0
    maximum_count = 0
    timestamped_count = 0
    abstract_patterns: dict[str, int] = {}
    top_relative_attention_patterns: dict[str, int] = {}
    organic_measured_items = 0
    organic_normalized_items = 0
    relative_attention_breakouts = 0
    organic_baseline_source_count = 0
    handoff_count = 0
    for plan_row, run in zip(plan_rows, runs):
        if not isinstance(plan_row, Mapping) or not isinstance(run, Mapping):
            raise RecentOrganicSignalPackError("collection source ledger row is invalid")
        if run.get("captcha_or_auth_bypass_attempted") is not False:
            raise RecentOrganicSignalPackError("a source attempted a forbidden access bypass")
        if run.get("status") not in {"completed", "completed_with_item_handoffs"}:
            handoff_count += 1
            continue
        freshness = run.get("public_freshness")
        if not isinstance(freshness, Mapping):
            freshness = {}
        oldest = _parse_timestamp(freshness.get("oldest_publication_at"))
        newest = _parse_timestamp(freshness.get("newest_publication_at"))
        timestamped = freshness.get("timestamped_item_count", 0)
        timestamped = timestamped if type(timestamped) is int and timestamped >= 0 else 0
        recent_90 = freshness.get("recent_item_count_90d")
        recent_180 = freshness.get("recent_item_count_180d")
        if recent_90 is None and newest is not None:
            recent_90 = int(newest >= preferred_cutoff)
        if recent_180 is None and newest is not None:
            recent_180 = int(newest >= maximum_cutoff)
        recent_90 = recent_90 if type(recent_90) is int and recent_90 >= 0 else 0
        recent_180 = recent_180 if type(recent_180) is int and recent_180 >= 0 else 0
        preferred_count += recent_90
        maximum_count += recent_180
        timestamped_count += timestamped
        sources.append(
            {
                "source_host": plan_row.get("source_host"),
                "platform": plan_row.get("platform"),
                "connector_id": run.get("connector_id"),
                "source_url_sha256": plan_row.get("source_url_sha256"),
                "timestamped_item_count": timestamped,
                "recent_item_count_preferred_window": recent_90,
                "recent_item_count_maximum_window": recent_180,
                "oldest_publication_at": oldest.isoformat().replace("+00:00", "Z") if oldest else None,
                "newest_publication_at": newest.isoformat().replace("+00:00", "Z") if newest else None,
                "raw_content_training_admitted": False,
                "sampling_context": plan_row.get("sampling_context"),
                "same_source_normalized_item_count": 0,
                "relative_attention_index_ge_2_count": 0,
            }
        )
        raw_patterns = run.get("abstract_content_pattern_counts")
        if isinstance(raw_patterns, Mapping):
            for pattern, count in raw_patterns.items():
                if isinstance(pattern, str) and type(count) is int and count >= 0:
                    abstract_patterns[pattern] = abstract_patterns.get(pattern, 0) + count
        organic = run.get("organic_signal_summary")
        if isinstance(organic, Mapping) and organic.get("schema") == "ProofLaunchWithinSourceOrganicBaselineV1":
            if organic.get("raw_expression_retained") is not False or organic.get("public_item_identifiers_retained") is not False:
                raise RecentOrganicSignalPackError("organic baseline retained forbidden source expression or identifiers")
            measured = organic.get("view_measured_item_count", 0)
            normalized = organic.get("normalized_item_count", 0)
            breakouts = organic.get("relative_attention_index_ge_2_count", 0)
            for candidate, name in (
                (measured, "view_measured_item_count"),
                (normalized, "normalized_item_count"),
                (breakouts, "relative_attention_index_ge_2_count"),
            ):
                if type(candidate) is not int or candidate < 0:
                    raise RecentOrganicSignalPackError(f"organic baseline {name} is invalid")
            organic_baseline_source_count += 1
            organic_measured_items += measured
            organic_normalized_items += normalized
            relative_attention_breakouts += breakouts
            sources[-1]["same_source_normalized_item_count"] = normalized
            sources[-1]["relative_attention_index_ge_2_count"] = breakouts
            top_patterns = organic.get("top_relative_attention_pattern_counts")
            if isinstance(top_patterns, Mapping):
                for pattern, count in top_patterns.items():
                    if isinstance(pattern, str) and type(count) is int and count >= 0:
                        top_relative_attention_patterns[pattern] = top_relative_attention_patterns.get(pattern, 0) + count
    if maximum_count < 1:
        raise RecentOrganicSignalPackError(
            f"no source item is dated within the last {maximum_age_days} days"
        )

    patterns = intelligence.get("top_abstract_format_patterns")
    metrics = intelligence.get("metric_summaries")
    patterns = patterns if isinstance(patterns, list) else []
    metrics = metrics if isinstance(metrics, list) else []
    measured_pattern_summary = ", ".join(
        f"{name} ({count}/{timestamped_count})"
        for name, count in sorted(abstract_patterns.items(), key=lambda item: (-item[1], item[0]))[:10]
    )
    normalized_pattern_summary = ", ".join(
        f"{item.get('feature')} ({item.get('observations')})"
        for item in patterns[:8]
        if isinstance(item, Mapping)
    ) or "no abstract format pattern cleared the evidence gate"
    pattern_summary = measured_pattern_summary or normalized_pattern_summary
    metric_summary = ", ".join(
        f"{item.get('metric')}: n={item.get('observation_count')}, range={item.get('minimum')}–{item.get('maximum')}"
        for item in metrics[:8]
        if isinstance(item, Mapping)
    ) or "no public counter summary available"
    organic_summary = (
        f"{organic_normalized_items} item(s) normalized against {organic_baseline_source_count} same-source median baseline(s); "
        f"{relative_attention_breakouts} reached a descriptive relative-attention index of at least 2.0"
        if organic_baseline_source_count
        else "no same-source public-counter baseline was available; feed rows are discovery signals only"
    )
    standard_summary = (
        f"Global sampling target: {sampling_standard['coverage_truth']['segment_market_cell_count']} segment-market cells "
        f"and {sampling_standard['coverage_truth']['platform_market_lane_count']} platform-market lanes; this run must not "
        "be represented as complete unless a separate coverage receipt satisfies those quotas"
        if sampling_standard is not None
        else "no global sampling standard was attached to this run"
    )
    context = (
        f"PUBLIC OBSERVATIONS captured {captured.date().isoformat()}: {len(sources)} source(s), "
        f"{timestamped_count} timestamped item(s); {preferred_count} fall within {preferred_age_days} days and "
        f"{maximum_count} within {maximum_age_days} days. Abstract format recurrence: {pattern_summary}. "
        f"Public counter summaries: {metric_summary}. Organic normalization: {organic_summary}. {standard_summary}. "
        "INTERPRETATION BOUNDARY: recurrence and counters are descriptive, "
        "not proof of causality, qualified demand, conversion, revenue, or future virality. Use them only to generate "
        "falsifiable creative hypotheses against a frozen control; never copy source expression."
    )
    provenance = (
        f"Open-source public measurement run {receipt['receipt_sha256']} using the pinned connectors recorded per source; "
        f"rights={plan.get('rights')}; capture={receipt.get('captured_at')}; source URLs are represented by SHA-256 and host only. "
        "Raw bytes remain isolated, contain no admitted training material, and no authentication, captcha, paywall or rate-limit "
        "bypass was attempted."
    )
    result: dict[str, Any] = {
        "schema": SCHEMA,
        "captured_at": receipt.get("captured_at"),
        "preferred_age_days": preferred_age_days,
        "maximum_age_days": maximum_age_days,
        "source_count": len(sources),
        "planned_source_count": len(plan_rows),
        "source_handoff_count": handoff_count,
        "timestamped_item_count": timestamped_count,
        "recent_item_count_preferred_window": preferred_count,
        "recent_item_count_maximum_window": maximum_count,
        "sources": sources,
        "abstract_content_pattern_counts": dict(sorted(abstract_patterns.items())),
        "organic_measurement_coverage": {
            "baseline_source_count": organic_baseline_source_count,
            "view_measured_item_count": organic_measured_items,
            "same_source_normalized_item_count": organic_normalized_items,
            "relative_attention_index_ge_2_count": relative_attention_breakouts,
            "top_relative_attention_pattern_counts": dict(sorted(top_relative_attention_patterns.items())),
            "baseline_method": "same_source_median_no_cross_account_absolute_rank",
            "learning_status": "pending_named_human_approval",
        },
        "recent_organic_signal_context": context,
        "signal_provenance": provenance,
        "collection_receipt_sha256": receipt.get("receipt_sha256"),
        "signal_intelligence_sha256": expected_intelligence_sha,
        "sampling_standard_sha256": (
            sampling_standard.get("content_sha256") if sampling_standard is not None else None
        ),
        "contains_copied_creative": False,
        "training_admitted": False,
        "strategy_mutation_executed": False,
        "human_review_required_before_learning_memory_write": True,
        "automatic_learning_memory_write_count": 0,
        "truth_boundary": (
            "This pack proves bounded public-source collection, date coverage and descriptive signal normalization only. "
            "It does not prove organic breakout, causal effect, product-market fit or a named-product win."
        ),
    }
    result["content_sha256"] = hashlib.sha256(canonical_json(result).encode("utf-8")).hexdigest()
    return result


def verify_recent_organic_signal_pack(value: Mapping[str, Any]) -> None:
    if value.get("schema") != SCHEMA:
        raise RecentOrganicSignalPackError("unsupported recent organic signal pack")
    if value.get("training_admitted") is not False or value.get("contains_copied_creative") is not False:
        raise RecentOrganicSignalPackError("signal pack rights boundary failed")
    if value.get("recent_item_count_maximum_window", 0) < 1:
        raise RecentOrganicSignalPackError("signal pack has no recent dated evidence")
    expected = hashlib.sha256(
        canonical_json({key: item for key, item in value.items() if key != "content_sha256"}).encode("utf-8")
    ).hexdigest()
    if value.get("content_sha256") != expected:
        raise RecentOrganicSignalPackError("signal pack digest mismatch")
    for field in ("recent_organic_signal_context", "signal_provenance"):
        if not isinstance(value.get(field), str) or not value[field].strip():
            raise RecentOrganicSignalPackError(f"signal pack is missing {field}")


def merge_recent_organic_signal_packs(packs: list[Mapping[str, Any]]) -> dict[str, Any]:
    if not 1 <= len(packs) <= 50:
        raise RecentOrganicSignalPackError("one to fifty signal packs are required")
    for pack in packs:
        verify_recent_organic_signal_pack(pack)
    preferred = {pack["preferred_age_days"] for pack in packs}
    maximum = {pack["maximum_age_days"] for pack in packs}
    if len(preferred) != 1 or len(maximum) != 1:
        raise RecentOrganicSignalPackError("signal pack freshness windows differ")
    standards = {
        pack.get("sampling_standard_sha256")
        for pack in packs
        if pack.get("sampling_standard_sha256") is not None
    }
    if len(standards) > 1:
        raise RecentOrganicSignalPackError("signal packs use different sampling standards")
    patterns: dict[str, int] = {}
    top_patterns: dict[str, int] = {}
    sources: list[dict[str, Any]] = []
    organic = {
        "baseline_source_count": 0,
        "view_measured_item_count": 0,
        "same_source_normalized_item_count": 0,
        "relative_attention_index_ge_2_count": 0,
    }
    for pack in packs:
        sources.extend(dict(row) for row in pack.get("sources", []) if isinstance(row, Mapping))
        for name, count in pack.get("abstract_content_pattern_counts", {}).items():
            if isinstance(name, str) and type(count) is int:
                patterns[name] = patterns.get(name, 0) + count
        measured = pack.get("organic_measurement_coverage", {})
        if isinstance(measured, Mapping):
            for key in organic:
                count = measured.get(key, 0)
                if type(count) is int and count >= 0:
                    organic[key] += count
            for name, count in measured.get("top_relative_attention_pattern_counts", {}).items():
                if isinstance(name, str) and type(count) is int:
                    top_patterns[name] = top_patterns.get(name, 0) + count
    captured_at = max(str(pack["captured_at"]) for pack in packs)
    preferred_days = next(iter(preferred))
    maximum_days = next(iter(maximum))
    recent_preferred = sum(int(pack["recent_item_count_preferred_window"]) for pack in packs)
    recent_maximum = sum(int(pack["recent_item_count_maximum_window"]) for pack in packs)
    timestamped = sum(int(pack["timestamped_item_count"]) for pack in packs)
    context = (
        f"MERGED PUBLIC OBSERVATIONS through {captured_at}: {len(sources)} completed source(s), "
        f"{timestamped} timestamped item(s); {recent_preferred} within {preferred_days} days and "
        f"{recent_maximum} within {maximum_days} days. {organic['same_source_normalized_item_count']} item(s) "
        f"were compared only with same-source medians; {organic['relative_attention_index_ge_2_count']} reached "
        "a descriptive relative-attention index of at least 2.0. Recurring and high-relative-attention abstract "
        f"patterns: {', '.join(f'{key} ({value})' for key, value in sorted(top_patterns.items(), key=lambda item: (-item[1], item[0]))[:10]) or 'none measured'}. "
        "INTERPRETATION BOUNDARY: public counters and recurrence are descriptive, not causal proof of qualified "
        "demand, conversion, revenue or future virality. Never copy source expression."
    )
    pack_digests = [str(pack["content_sha256"]) for pack in packs]
    result: dict[str, Any] = {
        "schema": SCHEMA,
        "captured_at": captured_at,
        "preferred_age_days": preferred_days,
        "maximum_age_days": maximum_days,
        "source_count": len(sources),
        "planned_source_count": sum(int(pack.get("planned_source_count", pack["source_count"])) for pack in packs),
        "source_handoff_count": sum(int(pack.get("source_handoff_count", 0)) for pack in packs),
        "timestamped_item_count": timestamped,
        "recent_item_count_preferred_window": recent_preferred,
        "recent_item_count_maximum_window": recent_maximum,
        "sources": sources,
        "abstract_content_pattern_counts": dict(sorted(patterns.items())),
        "organic_measurement_coverage": {
            **organic,
            "top_relative_attention_pattern_counts": dict(sorted(top_patterns.items())),
            "baseline_method": "same_source_median_no_cross_account_absolute_rank",
            "learning_status": "pending_named_human_approval",
        },
        "recent_organic_signal_context": context,
        "signal_provenance": (
            "Merged, verified, rights-safe public measurement packs: " + ", ".join(pack_digests) + ". "
            "Raw expression remains isolated; no authentication, captcha, paywall or rate-limit bypass was attempted."
        ),
        "collection_receipt_sha256": _sha_without_field({"packs": pack_digests}, "unused"),
        "signal_intelligence_sha256": _sha_without_field({"packs": pack_digests, "layer": "intelligence"}, "unused"),
        "sampling_standard_sha256": next(iter(standards)) if standards else None,
        "merged_from_signal_pack_sha256s": pack_digests,
        "contains_copied_creative": False,
        "training_admitted": False,
        "strategy_mutation_executed": False,
        "human_review_required_before_learning_memory_write": True,
        "automatic_learning_memory_write_count": 0,
        "truth_boundary": (
            "This merged pack proves verified freshness, bounded collection and descriptive normalization only. "
            "It does not prove organic breakout, causal effect, product-market fit or a named-product win."
        ),
    }
    result["content_sha256"] = hashlib.sha256(canonical_json(result).encode("utf-8")).hexdigest()
    verify_recent_organic_signal_pack(result)
    return result


__all__ = [
    "RecentOrganicSignalPackError",
    "SCHEMA",
    "compile_recent_organic_signal_pack",
    "merge_recent_organic_signal_packs",
    "verify_recent_organic_signal_pack",
]
