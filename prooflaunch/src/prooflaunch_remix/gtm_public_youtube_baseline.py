from __future__ import annotations

import hashlib
import json
import math
import re
import statistics
from collections import Counter
from datetime import date, datetime, timedelta
from typing import Any, Mapping, Sequence


CONFIG_SCHEMA = "ProofLaunchPublicYoutubeNamedProductBaselineAnalysisDraftV1"
OUTPUT_SCHEMA = "ProofLaunchPublicYoutubeNamedProductBaselineV1"


class PublicYoutubeBaselineError(ValueError):
    pass


_ARCHETYPES = (
    ("behind_the_scenes", re.compile(r"\b(making of|behind the scenes|breakdown|inside)\b", re.I)),
    ("product_release", re.compile(r"\b(launch|introduc|announce|new in|release|what'?s new|available now|is here|meet)\b", re.I)),
    ("contrarian_thesis", re.compile(r"\b(gets? wrong|nobody|real reason|invisible|crushed|rewriting|don'?t scale|not what|hard questions|betting billions|inflection point)\b", re.I)),
    ("tutorial_demo", re.compile(r"\b(how(?: to)?|tutorial|guide|tips|demo|getting started|workflow|build|create|edit|make|learn|course|configure|deploy|explained)\b", re.I)),
    ("event_interview", re.compile(r"\b(webinar|keynote|interview|podcast|session|conference|live)\b", re.I)),
    ("customer_story", re.compile(r"\b(customer|case study|story|scales?|used|helps?|with [A-Z])\b", re.I)),
    ("research_comparison", re.compile(r"\b(report|research|benchmark|versus|\bvs\b|study)\b", re.I)),
)


def _digest(value: object) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")).hexdigest()


def _parse_date(value: object) -> date | None:
    if not isinstance(value, str) or not re.fullmatch(r"\d{8}", value):
        return None
    try:
        return datetime.strptime(value, "%Y%m%d").date()
    except ValueError:
        return None


def _number(value: object) -> float | None:
    if type(value) not in {int, float}:
        return None
    number = float(value)
    if not math.isfinite(number) or number < 0:
        return None
    return number


def _archetype(title: object) -> str:
    text = title if isinstance(title, str) else ""
    for name, pattern in _ARCHETYPES:
        if pattern.search(text):
            return name
    return "other"


def _duration_bucket(duration: float | None) -> str:
    if duration is None:
        return "unknown"
    if duration <= 60:
        return "short_le_60s"
    if duration <= 300:
        return "mid_1_to_5m"
    return "long_gt_5m"


def _robust_scores(values: Sequence[float]) -> list[float]:
    logged = [math.log1p(value) for value in values]
    center = statistics.median(logged)
    mad = statistics.median(abs(value - center) for value in logged)
    if mad == 0:
        return [0.0 for _ in values]
    return [max(-3.0, min(3.0, 0.6745 * (value - center) / mad)) for value in logged]


def compile_public_youtube_baseline(
    config: Mapping[str, Any],
    *,
    source_payloads: Mapping[int, Mapping[str, Any]],
    source_bindings: list[dict[str, Any]],
) -> dict[str, Any]:
    if config.get("schema") != CONFIG_SCHEMA:
        raise PublicYoutubeBaselineError("YouTube baseline config schema drifted")
    sources = config.get("sources")
    if not isinstance(sources, list) or len(sources) != 10:
        raise PublicYoutubeBaselineError("exactly ten named-product sources are required")
    as_of = date.fromisoformat(str(config["as_of_date"]))
    window_days = int(config["window_days"])
    cutoff = as_of - timedelta(days=window_days)
    minimum = int(config["minimum_recent_items_for_full_sample"])
    product_rows: list[dict[str, Any]] = []
    breakout_rows: list[dict[str, Any]] = []
    for spec in sources:
        index = int(spec["source_index"])
        raw = source_payloads.get(index)
        if not isinstance(raw, Mapping):
            raise PublicYoutubeBaselineError(f"source {index} is missing")
        channel = str(raw.get("channel") or raw.get("uploader") or "").strip()
        if str(spec["expected_channel"]).casefold() not in channel.casefold():
            raise PublicYoutubeBaselineError(f"source {index} channel identity drifted")
        follower_count = _number(raw.get("channel_follower_count"))
        entries = raw.get("entries")
        if not isinstance(entries, list) or not entries:
            raise PublicYoutubeBaselineError(f"source {index} contains no entries")
        recent: list[dict[str, Any]] = []
        for entry in entries:
            if not isinstance(entry, Mapping):
                continue
            published = _parse_date(entry.get("upload_date"))
            views = _number(entry.get("view_count"))
            if published is None or views is None or published > as_of or published < cutoff:
                continue
            likes = _number(entry.get("like_count")) or 0.0
            comments = _number(entry.get("comment_count")) or 0.0
            duration = _number(entry.get("duration"))
            age_days = max(1, (as_of - published).days)
            video_id = str(entry.get("id") or "")
            recent.append({
                "video_ref_sha256": hashlib.sha256(video_id.encode("utf-8")).hexdigest(),
                "published_date": published.isoformat(),
                "age_days": age_days,
                "duration_seconds": duration,
                "duration_bucket": _duration_bucket(duration),
                "content_archetype": _archetype(entry.get("title")),
                "views": int(views),
                "likes": int(likes),
                "comments": int(comments),
                "views_per_day_proxy": views / age_days,
                "engagement_actions_per_1000_views": ((likes + comments) / views * 1000.0) if views else 0.0,
                "views_per_channel_follower": (views / follower_count) if follower_count else None,
            })
        view_scores = _robust_scores([float(row["views"]) for row in recent]) if recent else []
        velocity_scores = _robust_scores([float(row["views_per_day_proxy"]) for row in recent]) if recent else []
        for row, view_score, velocity_score in zip(recent, view_scores, velocity_scores):
            row["distribution_outlier_score"] = round(0.6 * view_score + 0.4 * velocity_score, 4)
        recent.sort(key=lambda row: (-float(row["distribution_outlier_score"]), -int(row["views"]), row["video_ref_sha256"]))
        status = "eligible_current_window_snapshot" if len(recent) >= minimum else ("limited_current_window_snapshot" if recent else "no_current_window_observation")
        views = [int(row["views"]) for row in recent]
        product_row = {
            "product": spec["product"],
            "pk_lanes": list(spec["pk_lanes"]),
            "public_channel": channel,
            "public_channel_verified": raw.get("channel_is_verified") if type(raw.get("channel_is_verified")) is bool else None,
            "channel_follower_count": int(follower_count) if follower_count is not None else None,
            "captured_item_count": len(entries),
            "recent_item_count": len(recent),
            "sample_status": status,
            "window_start": cutoff.isoformat(),
            "window_end": as_of.isoformat(),
            "median_views": statistics.median(views) if views else None,
            "maximum_views": max(views) if views else None,
            "median_engagement_actions_per_1000_views": statistics.median(float(row["engagement_actions_per_1000_views"]) for row in recent) if recent else None,
            "archetype_counts": dict(sorted(Counter(str(row["content_archetype"]) for row in recent).items())),
            "duration_bucket_counts": dict(sorted(Counter(str(row["duration_bucket"]) for row in recent).items())),
            "top_distribution_outliers": recent[:3],
        }
        product_rows.append(product_row)
        breakout_rows.extend({"product": spec["product"], **row} for row in recent[:3])
    full_count = sum(row["sample_status"] == "eligible_current_window_snapshot" for row in product_rows)
    pattern_counts = Counter((row["content_archetype"], row["duration_bucket"]) for row in breakout_rows)
    heavy_tail_products = [
        {
            "product": row["product"],
            "maximum_to_median_views_ratio": round(float(row["maximum_views"]) / max(1.0, float(row["median_views"])), 2),
        }
        for row in product_rows
        if row["maximum_views"] is not None
        and row["median_views"] is not None
        and float(row["maximum_views"]) / max(1.0, float(row["median_views"])) >= 20.0
    ]
    top_archetypes = Counter(str(row["content_archetype"]) for row in breakout_rows)
    top_durations = Counter(str(row["duration_bucket"]) for row in breakout_rows)
    clean_room_hypotheses = [
        {
            "hypothesis_id": "route-level-heavy-tail",
            "observation": "Several named-product channels show a maximum-to-median view ratio above 20x in the bounded snapshot.",
            "test": "Compare the Rejection Rule mechanism with an autonomy-demo route while freezing audience, proof object, platform, CTA and release window.",
            "success_measure": "source-hidden publishability plus qualified-review acceptance after an authorized exposure",
            "copy_source_expression": False,
        },
        {
            "hypothesis_id": "short-long-job-bifurcation",
            "observation": "Top distribution outliers span short and long duration jobs rather than one universal length.",
            "test": "Produce one <=30 second physical rejection-gate film and one >5 minute buyer audit; give each a separate brief, promise and evaluation contract.",
            "success_measure": "platform-native completion proxy and qualified action, never pooled raw views",
            "copy_source_expression": False,
        },
        {
            "hypothesis_id": "decision-proof-over-generic-tour",
            "observation": "The abstract outlier mix includes demonstrations, theses, releases and proof-led stories; no single archetype is sufficient evidence.",
            "test": "Replace generic feature tours with a decision-specific proof object, explicit rejection condition and role-native payoff while preserving original language and visual identity.",
            "success_measure": "five-reviewer source-hidden preference and major-rework gate",
            "copy_source_expression": False,
        },
    ]
    payload = {
        "schema": OUTPUT_SCHEMA,
        "as_of_date": as_of.isoformat(),
        "window_days": window_days,
        "window_start": cutoff.isoformat(),
        "named_product_count": len(product_rows),
        "full_sample_product_count": full_count,
        "limited_sample_product_count": sum(row["sample_status"] == "limited_current_window_snapshot" for row in product_rows),
        "product_rows": product_rows,
        "cross_product_outlier_pattern_counts": [
            {"content_archetype": key[0], "duration_bucket": key[1], "top_outlier_occurrences": count}
            for key, count in sorted(pattern_counts.items(), key=lambda item: (-item[1], item[0]))
        ],
        "cross_product_summary": {
            "heavy_tail_product_count": len(heavy_tail_products),
            "heavy_tail_products": sorted(heavy_tail_products, key=lambda row: (-row["maximum_to_median_views_ratio"], row["product"])),
            "top_outlier_archetypes": [
                {"content_archetype": name, "occurrences": count}
                for name, count in sorted(top_archetypes.items(), key=lambda item: (-item[1], item[0]))
            ],
            "top_outlier_duration_buckets": [
                {"duration_bucket": name, "occurrences": count}
                for name, count in sorted(top_durations.items(), key=lambda item: (-item[1], item[0]))
            ],
        },
        "clean_room_execution_hypotheses": clean_room_hypotheses,
        "interpretation_contract": {
            "distribution_outlier_is_viral_proof": False,
            "single_snapshot_is_growth_curve": False,
            "views_are_qualified_conversion": False,
            "public_titles_or_descriptions_retained": False,
            "source_expression_copying_allowed": False,
            "allowed_use": "abstract format, cadence and measurement hypotheses for a clean-room same-brief challenger"
        },
        "source_bindings": source_bindings,
        "raw_content_training_admitted": False,
        "strategy_mutation_executed": False,
        "external_publish_executed": False,
        "truth_boundary": config["truth_boundary"],
    }
    payload["content_sha256"] = _digest(payload)
    return payload


def verify(payload: Mapping[str, Any]) -> None:
    unsigned = dict(payload)
    supplied = unsigned.pop("content_sha256", None)
    if payload.get("schema") != OUTPUT_SCHEMA or supplied != _digest(unsigned):
        raise PublicYoutubeBaselineError("YouTube baseline seal is invalid")
    if payload.get("named_product_count") != 10 or payload.get("raw_content_training_admitted") is not False:
        raise PublicYoutubeBaselineError("YouTube baseline boundary drifted")
    if payload.get("strategy_mutation_executed") is not False or payload.get("external_publish_executed") is not False:
        raise PublicYoutubeBaselineError("YouTube baseline external-action boundary drifted")


__all__ = ["PublicYoutubeBaselineError", "compile_public_youtube_baseline", "verify"]
