from __future__ import annotations

import hashlib
import json
import math
import statistics
from datetime import datetime, timezone
from typing import Any, Iterable, Mapping, Sequence
from urllib.parse import urlsplit, urlunsplit

from .gtm_production_quality_contract import evaluate_organic_breakout_candidate


SCHEMA = "ProofLaunchOrganicBreakoutAdmissionReceiptV1"


class OrganicBreakoutAdmissionError(ValueError):
    """Public signal evidence is incomplete, unsafe, or internally inconsistent."""


def _digest(value: object) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()


def _finite_number(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    return number if math.isfinite(number) and number >= 0 else None


def _public_url(record: Mapping[str, object]) -> str | None:
    for field in ("webpage_url", "original_url"):
        value = record.get(field)
        if isinstance(value, str):
            parsed = urlsplit(value)
            if parsed.scheme == "https" and parsed.hostname:
                return urlunsplit(("https", parsed.netloc, parsed.path, "", ""))
    return None


def _published_at(record: Mapping[str, object]) -> str | None:
    timestamp = _finite_number(record.get("timestamp"))
    if timestamp is not None:
        try:
            return datetime.fromtimestamp(timestamp, timezone.utc).isoformat().replace(
                "+00:00", "Z"
            )
        except (OverflowError, OSError, ValueError):
            return None
    upload_date = record.get("upload_date")
    if isinstance(upload_date, str) and len(upload_date) == 8 and upload_date.isdigit():
        try:
            return datetime.strptime(upload_date, "%Y%m%d").replace(
                tzinfo=timezone.utc
            ).isoformat().replace("+00:00", "Z")
        except ValueError:
            return None
    return None


def _iter_records(values: Iterable[object]) -> Iterable[Mapping[str, object]]:
    for value in values:
        if isinstance(value, Mapping):
            entries = value.get("entries")
            if isinstance(entries, Sequence) and not isinstance(entries, (str, bytes)):
                yield from _iter_records(entries)
            else:
                yield value
        elif isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
            yield from _iter_records(value)


def _interactions(record: Mapping[str, object]) -> float | None:
    values = [
        _finite_number(record.get(field))
        for field in (
            "like_count",
            "comment_count",
            "repost_count",
            "share_count",
            "save_count",
        )
    ]
    observed = [value for value in values if value is not None]
    return sum(observed) if observed else None


def _paid_status(record: Mapping[str, object]) -> tuple[str, list[str]]:
    flags: list[str] = []
    for field in (
        "is_ad",
        "is_paid",
        "is_sponsored",
        "paid_partnership",
        "promoted",
    ):
        value = record.get(field)
        if value is True:
            flags.append(f"{field}_observed")
    text = " ".join(
        str(record.get(field) or "") for field in ("title", "description")
    ).casefold()
    if any(token in text for token in ("giveaway", "sweepstakes", "win a free")):
        flags.append("giveaway_or_prize_inducement")
    if flags:
        return "paid_or_induced_signal_observed", flags
    return "none_observed_with_disclosure", []


def compile_organic_breakout_admissions(
    sources: Sequence[Mapping[str, object]],
    *,
    observed_at: str,
) -> dict[str, Any]:
    """Create privacy-minimized, candidate-level relative-breakout receipts.

    Raw creative expression is used only to detect inducement terms and is never
    copied into the output. A candidate remains descriptive and cannot enter
    training or durable strategy memory without a named-human abstraction review.
    """

    try:
        observed = datetime.fromisoformat(observed_at.replace("Z", "+00:00"))
    except (TypeError, ValueError) as error:
        raise OrganicBreakoutAdmissionError("observed_at must be ISO-8601") from error
    if observed.tzinfo is None:
        raise OrganicBreakoutAdmissionError("observed_at must include a timezone")
    if not sources:
        raise OrganicBreakoutAdmissionError("at least one source is required")

    admitted: list[dict[str, Any]] = []
    rejected_counts: dict[str, int] = {}
    source_summaries: list[dict[str, Any]] = []
    total_normalized = 0
    for source_index, source in enumerate(sources, start=1):
        raw_records = source.get("records")
        if not isinstance(raw_records, Sequence) or isinstance(raw_records, (str, bytes)):
            raise OrganicBreakoutAdmissionError("source records must be a sequence")
        capture_sha256 = source.get("capture_sha256")
        if not isinstance(capture_sha256, str) or len(capture_sha256) != 64:
            raise OrganicBreakoutAdmissionError("source capture_sha256 is invalid")
        normalized: list[dict[str, Any]] = []
        for record in _iter_records(raw_records):
            url = _public_url(record)
            published = _published_at(record)
            attention = _finite_number(record.get("view_count"))
            interactions = _interactions(record)
            if not url or not published or attention is None:
                continue
            expression = "\n".join(
                str(record.get(field) or "")
                for field in ("title", "description")
            )
            paid_status, pseudo_flags = _paid_status(record)
            normalized.append(
                {
                    "source_url": url,
                    "published_at": published,
                    "item_attention": attention,
                    "item_interactions": interactions,
                    "paid_distribution_status": paid_status,
                    "pseudo_breakout_flags": pseudo_flags,
                    "creative_expression_sha256": hashlib.sha256(
                        expression.encode("utf-8")
                    ).hexdigest(),
                }
            )
        total_normalized += len(normalized)
        attention_values = [row["item_attention"] for row in normalized]
        interaction_values = [
            row["item_interactions"]
            for row in normalized
            if row["item_interactions"] is not None
        ]
        median_attention = (
            statistics.median(attention_values) if attention_values else None
        )
        median_interactions = (
            statistics.median(interaction_values) if interaction_values else None
        )
        source_id = str(source.get("source_id") or f"source-{source_index:04d}")
        source_admitted = 0
        for item_index, row in enumerate(normalized, start=1):
            source_record = {
                "source_url": row["source_url"],
                "published_at": row["published_at"],
                "item_attention": row["item_attention"],
                "item_interactions": row["item_interactions"],
                "baseline_median_attention": median_attention,
                "baseline_median_interactions": median_interactions,
                "account_baseline_item_count": len(normalized),
                "paid_distribution_status": row["paid_distribution_status"],
                "rights_status": "public_measurement",
            }
            source_record["source_sha256"] = _digest(source_record)
            candidate = {
                **source_record,
                "capture_sha256": capture_sha256,
            }
            evaluation = evaluate_organic_breakout_candidate(
                candidate, observed_at=observed
            )
            failures = list(evaluation["failures"])
            if row["pseudo_breakout_flags"]:
                failures.append("pseudo_breakout_signal_detected")
            if failures:
                for failure in sorted(set(failures)):
                    rejected_counts[failure] = rejected_counts.get(failure, 0) + 1
                continue
            candidate_id = f"breakout-{_digest(candidate)[:20]}"
            admitted.append(
                {
                    "candidate_id": candidate_id,
                    "source_id": source_id,
                    "source_url": row["source_url"],
                    "published_at": row["published_at"],
                    "age_days": evaluation["age_days"],
                    "preferred_90_day_window": evaluation[
                        "preferred_90_day_window"
                    ],
                    "account_baseline_item_count": len(normalized),
                    "item_attention": row["item_attention"],
                    "baseline_median_attention": median_attention,
                    "relative_attention": evaluation["relative_attention"],
                    "item_interactions": row["item_interactions"],
                    "baseline_median_interactions": median_interactions,
                    "relative_interactions": evaluation["relative_interactions"],
                    "paid_distribution_status": row["paid_distribution_status"],
                    "paid_distribution_disclosure": (
                        "No paid/sponsored marker was present in the captured public metadata; "
                        "platform ad-library and creator-side spend were not independently audited."
                    ),
                    "source_sha256": source_record["source_sha256"],
                    "capture_sha256": capture_sha256,
                    "creative_expression_sha256": row[
                        "creative_expression_sha256"
                    ],
                    "raw_expression_retained": False,
                    "admission_status": "relative_breakout_candidate",
                    "causal_growth_claim_allowed": False,
                    "training_admitted": False,
                    "durable_memory_admitted": False,
                    "named_human_abstraction_review_required": True,
                }
            )
            source_admitted += 1
        source_summaries.append(
            {
                "source_id": source_id,
                "capture_sha256": capture_sha256,
                "normalized_item_count": len(normalized),
                "baseline_median_attention": median_attention,
                "baseline_median_interactions": median_interactions,
                "admitted_candidate_count": source_admitted,
            }
        )

    admitted.sort(
        key=lambda row: (
            -max(
                float(row["relative_attention"] or 0),
                float(row["relative_interactions"] or 0),
            ),
            row["candidate_id"],
        )
    )
    core: dict[str, Any] = {
        "schema": SCHEMA,
        "observed_at": observed_at,
        "source_count": len(source_summaries),
        "normalized_item_count": total_normalized,
        "admitted_candidate_count": len(admitted),
        "preferred_90_day_candidate_count": sum(
            row["preferred_90_day_window"] for row in admitted
        ),
        "rejected_finding_counts": dict(sorted(rejected_counts.items())),
        "sources": source_summaries,
        "candidates": admitted,
        "raw_expression_retained": False,
        "automatic_strategy_mutation_executed": False,
        "automatic_learning_memory_write_count": 0,
        "training_admitted": False,
        "truth_boundary": (
            "Admission proves a recent within-source relative-attention candidate with public "
            "counter provenance. It does not prove organic causality, qualified demand, revenue, "
            "future virality, or freedom from undisclosed paid distribution."
        ),
    }
    core["content_sha256"] = _digest(core)
    return core


def verify_organic_breakout_admissions(payload: Mapping[str, object]) -> None:
    unsigned = dict(payload)
    supplied = unsigned.pop("content_sha256", None)
    if payload.get("schema") != SCHEMA or supplied != _digest(unsigned):
        raise OrganicBreakoutAdmissionError("organic breakout receipt seal is invalid")
    candidates = payload.get("candidates")
    if not isinstance(candidates, list):
        raise OrganicBreakoutAdmissionError("organic breakout candidates must be a list")
    if payload.get("admitted_candidate_count") != len(candidates):
        raise OrganicBreakoutAdmissionError("organic breakout candidate count drifted")
    if payload.get("training_admitted") is not False:
        raise OrganicBreakoutAdmissionError("public candidates cannot enter training")
    if payload.get("automatic_learning_memory_write_count") != 0:
        raise OrganicBreakoutAdmissionError("public candidates cannot auto-write memory")
