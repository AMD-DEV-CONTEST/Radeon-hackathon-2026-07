from __future__ import annotations

import csv
import hashlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import urlparse

from .ledger import canonical_json


OPERATOR_ATTESTATION = (
    "I confirm this export was captured through ordinary browsing or an authorized "
    "platform export, contains public content only, and was not obtained by bypassing "
    "authentication, CAPTCHA, paywalls, or rate limits."
)
SUPPORTED_PLATFORMS = frozenset(
    {"linkedin", "tiktok", "instagram", "reddit", "x", "facebook", "pinterest", "bluesky", "mastodon"}
)
_PRIVATE_VISIBILITIES = frozenset(
    {"private", "direct", "followers", "friends", "close_friends", "only_me"}
)
_METRIC_ALIASES = {
    "view_count": ("view_count", "views", "play_count", "video_view_count"),
    "like_count": ("like_count", "likes", "num_likes", "favorite_count", "favourites_count"),
    "comment_count": ("comment_count", "comments", "num_comments", "reply_count", "replies_count"),
    "share_count": ("share_count", "shares", "repost_count", "retweet_count", "reblogs_count"),
    "save_count": ("save_count", "saves", "bookmark_count", "collect_count"),
}


class OperatorSocialExportError(ValueError):
    pass


def _sha(value: object) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def _load_rows(path: Path) -> tuple[list[Mapping[str, Any]], str]:
    resolved = path.resolve(strict=True)
    if not resolved.is_file() or resolved.is_symlink():
        raise OperatorSocialExportError("operator export must be a regular file")
    size = resolved.stat().st_size
    if not 1 <= size <= 50_000_000:
        raise OperatorSocialExportError("operator export must be between 1 byte and 50 MB")
    raw = resolved.read_bytes()
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError as error:
        raise OperatorSocialExportError("operator export must be UTF-8") from error
    suffix = resolved.suffix.casefold()
    rows: list[Any]
    if suffix == ".csv":
        rows = list(csv.DictReader(text.splitlines()))
        input_format = "csv"
    elif suffix in {".ndjson", ".jsonl"}:
        try:
            rows = [json.loads(line) for line in text.splitlines() if line.strip()]
        except json.JSONDecodeError as error:
            raise OperatorSocialExportError("operator NDJSON is invalid") from error
        input_format = "ndjson"
    elif suffix == ".json":
        try:
            decoded = json.loads(text)
        except json.JSONDecodeError as error:
            raise OperatorSocialExportError("operator JSON is invalid") from error
        if isinstance(decoded, list):
            rows = decoded
        elif isinstance(decoded, Mapping) and isinstance(decoded.get("items"), list):
            rows = decoded["items"]
        else:
            raise OperatorSocialExportError("operator JSON must be an array or an object with items")
        input_format = "json"
    else:
        raise OperatorSocialExportError("operator export must use .json, .ndjson, .jsonl, or .csv")
    if not 1 <= len(rows) <= 10_000:
        raise OperatorSocialExportError("operator export must contain between 1 and 10000 rows")
    if any(not isinstance(row, Mapping) for row in rows):
        raise OperatorSocialExportError("every operator export row must be an object")
    return list(rows), input_format


def _first(row: Mapping[str, Any], names: tuple[str, ...]) -> Any:
    for name in names:
        value = row.get(name)
        if value is not None and value != "":
            return value
    return None


def _timestamp(value: Any) -> datetime | None:
    if value in {None, ""}:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)) or (isinstance(value, str) and value.strip().isdigit()):
        number = float(value)
        if number > 10_000_000_000:
            number /= 1000
        try:
            parsed = datetime.fromtimestamp(number, tz=timezone.utc)
        except (OverflowError, OSError, ValueError):
            return None
    else:
        try:
            parsed = datetime.fromisoformat(str(value).strip().replace("Z", "+00:00"))
        except ValueError:
            return None
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        parsed = parsed.astimezone(timezone.utc)
    if parsed.year < 2000 or parsed > datetime.now(timezone.utc) + timedelta(days=1):
        return None
    return parsed


def _metric(row: Mapping[str, Any], names: tuple[str, ...]) -> int:
    value = _first(row, names)
    if value is None:
        return 0
    try:
        parsed = int(float(str(value).replace(",", "")))
    except ValueError:
        return 0
    return parsed if parsed >= 0 else 0


def compile_operator_social_export(
    input_path: Path,
    *,
    platform: str,
    operator_attestation: str,
    observed_at: datetime | None = None,
) -> dict[str, Any]:
    if platform not in SUPPORTED_PLATFORMS:
        raise OperatorSocialExportError("operator export platform is unsupported")
    if operator_attestation != OPERATOR_ATTESTATION:
        raise OperatorSocialExportError("exact public-only operator attestation is required")
    rows, input_format = _load_rows(input_path)
    observed_input = observed_at or datetime.now(timezone.utc)
    if observed_input.tzinfo is None:
        raise OperatorSocialExportError("observed_at must be timezone-aware")
    observed = observed_input.astimezone(timezone.utc)
    file_sha = hashlib.sha256(input_path.resolve(strict=True).read_bytes()).hexdigest()
    accepted: list[dict[str, Any]] = []
    private_rejected = 0
    invalid_rejected = 0
    seen: set[str] = set()
    for index, wrapper in enumerate(rows):
        nested = wrapper.get("data")
        row = nested if isinstance(nested, Mapping) else wrapper
        visibility = str(
            _first(row, ("visibility", "privacy", "audience", "access")) or "public"
        ).casefold()
        if visibility in _PRIVATE_VISIBILITIES:
            private_rejected += 1
            continue
        item_id = _first(row, ("id", "post_id", "aweme_id", "code", "rest_id", "uri"))
        item_url = _first(
            row, ("url", "post_url", "web_url", "canonical_url", "permalink")
        )
        if item_url is not None:
            parsed_url = urlparse(str(item_url))
            if parsed_url.scheme != "https" or not parsed_url.hostname:
                item_url = None
        if item_id is None and item_url is None:
            invalid_rejected += 1
            continue
        identity = str(item_id or item_url)
        identity_sha = hashlib.sha256(f"{platform}:{identity}".encode("utf-8")).hexdigest()
        if identity_sha in seen:
            continue
        seen.add(identity_sha)
        published = _timestamp(
            _first(
                row,
                (
                    "timestamp", "created_at", "create_time", "taken_at",
                    "date", "created_utc", "unix_at", "published_at",
                ),
            )
        )
        text_value = _first(
            row, ("body", "caption", "text", "full_text", "title", "selftext", "description")
        )
        text_excerpt = " ".join(str(text_value or "").split())[:500]
        metrics = {
            metric: _metric(row, aliases) for metric, aliases in _METRIC_ALIASES.items()
        }
        item = {
            "platform": platform,
            "item_identity_sha256": identity_sha,
            "item_url_sha256": (
                hashlib.sha256(str(item_url).encode("utf-8")).hexdigest()
                if item_url is not None else None
            ),
            "published_at": published.isoformat() if published is not None else None,
            "text_excerpt": text_excerpt,
            "text_excerpt_sha256": hashlib.sha256(text_excerpt.encode("utf-8")).hexdigest(),
            "metrics": metrics,
            "attention_count": sum(metrics.values()),
            "source_row_index": index,
        }
        item["content_sha256"] = _sha(item)
        accepted.append(item)
    recent_90 = sum(
        item["published_at"] is not None
        and datetime.fromisoformat(item["published_at"]) >= observed - timedelta(days=90)
        for item in accepted
    )
    recent_180 = sum(
        item["published_at"] is not None
        and datetime.fromisoformat(item["published_at"]) >= observed - timedelta(days=180)
        for item in accepted
    )
    payload: dict[str, Any] = {
        "schema": "ProofLaunchOperatorSocialExportNormalizationV1",
        "platform": platform,
        "input_format": input_format,
        "source_file_sha256": file_sha,
        "input_row_count": len(rows),
        "accepted_public_item_count": len(accepted),
        "private_item_rejected_count": private_rejected,
        "invalid_item_rejected_count": invalid_rejected,
        "recent_item_count_90d": recent_90,
        "recent_item_count_180d": recent_180,
        "observed_at": observed.isoformat(),
        "items": accepted,
        "collection_mode": "operator_authorized_browser_or_platform_export",
        "raw_content_training_admitted": False,
        "automatic_learning_memory_write_count": 0,
        "authentication_captcha_paywall_or_rate_limit_bypass_attempted": False,
        "operator_attestation_sha256": hashlib.sha256(
            operator_attestation.encode("utf-8")
        ).hexdigest(),
        "truth_boundary": (
            "This receipt normalizes an operator-supplied public-only export. It does not prove "
            "platform completeness, organic causality, training rights, or automatic collection."
        ),
    }
    payload["content_sha256"] = _sha(payload)
    return payload
