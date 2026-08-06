from __future__ import annotations

import hashlib
import ipaddress
import json
import math
import re
import shutil
import socket
import subprocess
import sys
from statistics import median
from dataclasses import dataclass
from collections import Counter
from datetime import datetime, timedelta, timezone
from importlib import metadata
from pathlib import Path
from typing import Callable, Mapping, Sequence
from urllib.parse import quote, urlencode, urljoin, urlparse

from .files import atomic_write_bytes
from .gtm_signal_intelligence import compile_signal_intelligence
from .ledger import canonical_json
from .social_collection import plan_social_collection


class SocialCollectionExecutionError(RuntimeError):
    pass


@dataclass(frozen=True)
class PublicHttpResponse:
    status_code: int
    body: bytes
    headers: Mapping[str, str]
    url: str


def _system_resolver(host: str) -> Sequence[str]:
    try:
        rows = socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
    except socket.gaierror as error:
        raise SocialCollectionExecutionError(
            "public source hostname could not be resolved"
        ) from error
    return tuple(sorted({str(row[4][0]) for row in rows}))


def _public_https_url(url: str, resolver: Callable[[str], Sequence[str]]) -> str:
    if not isinstance(url, str) or not 1 <= len(url) <= 2_000:
        raise SocialCollectionExecutionError("public source URL is invalid")
    parsed = urlparse(url)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.port not in {None, 443}
    ):
        raise SocialCollectionExecutionError(
            "public HTTP adapters require credential-free HTTPS on port 443"
        )
    host = parsed.hostname.casefold().rstrip(".")
    if host == "localhost" or host.endswith((".localhost", ".local", ".internal")):
        raise SocialCollectionExecutionError("local source hosts are forbidden")
    try:
        literal_address = ipaddress.ip_address(host)
    except ValueError:
        literal_address = None
    if literal_address is not None:
        addresses = (str(literal_address),)
    else:
        addresses = tuple(resolver(host))
    if not addresses:
        raise SocialCollectionExecutionError("source host resolved to no addresses")
    for raw_address in addresses:
        try:
            address = ipaddress.ip_address(raw_address)
        except ValueError as error:
            raise SocialCollectionExecutionError(
                "source resolver returned an invalid address"
            ) from error
        if not address.is_global:
            raise SocialCollectionExecutionError(
                "source host resolved to a non-public address"
            )
    return url


def _httpx_request_once(
    url: str,
    *,
    timeout_seconds: float,
    maximum_bytes: int,
) -> PublicHttpResponse:
    try:
        import httpx
    except ImportError as error:
        raise SocialCollectionExecutionError(
            "httpx is required for admitted public protocol collection"
        ) from error
    headers = {
        "Accept": (
            "application/json, application/atom+xml, application/rss+xml, "
            "application/xml, text/xml;q=0.9, text/html;q=0.8"
        ),
        "User-Agent": "ProofLaunch-PublicSignalCollector/1.0",
    }
    try:
        with httpx.Client(
            follow_redirects=False,
            trust_env=False,
            headers=headers,
            timeout=httpx.Timeout(timeout_seconds),
        ) as client:
            with client.stream("GET", url) as response:
                body = bytearray()
                for chunk in response.iter_bytes():
                    body.extend(chunk)
                    if len(body) > maximum_bytes:
                        raise SocialCollectionExecutionError(
                            "public response exceeded the configured byte limit"
                        )
                return PublicHttpResponse(
                    status_code=response.status_code,
                    body=bytes(body),
                    headers={key.casefold(): value for key, value in response.headers.items()},
                    url=str(response.url),
                )
    except SocialCollectionExecutionError:
        raise
    except Exception as error:
        raise SocialCollectionExecutionError(
            f"public HTTP request failed: {type(error).__name__}"
        ) from error


class BoundedPublicHttpClient:
    """HTTPS-only, no-auth client with redirect, DNS, byte and timeout bounds."""

    def __init__(
        self,
        *,
        request_once: Callable[..., PublicHttpResponse] = _httpx_request_once,
        resolver: Callable[[str], Sequence[str]] = _system_resolver,
        maximum_redirects: int = 3,
    ) -> None:
        if not 0 <= maximum_redirects <= 3:
            raise ValueError("maximum_redirects must be in [0, 3]")
        self._request_once = request_once
        self._resolver = resolver
        self._maximum_redirects = maximum_redirects

    def get(
        self,
        url: str,
        *,
        timeout_seconds: float,
        maximum_bytes: int,
    ) -> PublicHttpResponse:
        if not 1 <= maximum_bytes <= 5_000_000:
            raise SocialCollectionExecutionError(
                "public protocol response limit must be in [1, 5000000]"
            )
        if not 0.1 <= timeout_seconds <= 60:
            raise SocialCollectionExecutionError(
                "public protocol timeout must be in [0.1, 60] seconds"
            )
        current = url
        for redirect_count in range(self._maximum_redirects + 1):
            _public_https_url(current, self._resolver)
            response = self._request_once(
                current,
                timeout_seconds=timeout_seconds,
                maximum_bytes=maximum_bytes,
            )
            if len(response.body) > maximum_bytes:
                raise SocialCollectionExecutionError(
                    "public response exceeded the configured byte limit"
                )
            _public_https_url(response.url, self._resolver)
            headers = {str(key).casefold(): str(value) for key, value in response.headers.items()}
            if response.status_code not in {301, 302, 303, 307, 308}:
                if response.status_code != 200:
                    raise SocialCollectionExecutionError(
                        f"public endpoint returned HTTP {response.status_code}"
                    )
                return PublicHttpResponse(
                    response.status_code,
                    response.body,
                    headers,
                    response.url,
                )
            if redirect_count >= self._maximum_redirects:
                raise SocialCollectionExecutionError("public endpoint exceeded redirect limit")
            location = headers.get("location", "")
            if not location:
                raise SocialCollectionExecutionError("redirect response omitted Location")
            current = urljoin(response.url, location)
        raise AssertionError("redirect loop must terminate")


def _resolve_executable(name: str) -> str | None:
    sibling = Path(sys.executable).with_name(name)
    if sibling.is_file() and not sibling.is_symlink():
        return str(sibling)
    return shutil.which(name)


def _write_json(path: Path, payload: Mapping[str, object]) -> None:
    atomic_write_bytes(
        path,
        (json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode(
            "utf-8"
        ),
    )


def _safe_cookie_file(cookie_file: str | Path | None, *, rights: str) -> Path | None:
    if cookie_file is None:
        return None
    if rights != "account_authorized":
        raise SocialCollectionExecutionError(
            "cookie sessions are permitted only for account_authorized collection"
        )
    candidate = Path(cookie_file).expanduser().resolve(strict=True)
    if candidate.is_symlink() or not candidate.is_file():
        raise SocialCollectionExecutionError("cookie file must be a regular file")
    return candidate


def _yt_dlp_command(
    *,
    executable: str,
    url: str,
    output: Path,
    maximum_items: int,
    maximum_bytes: int,
    timeout_seconds: int,
    media_download_allowed: bool,
    cookie_file: Path | None,
) -> list[str]:
    command = [
        executable,
        "--ignore-config",
        "--no-update",
        "--restrict-filenames",
        "--playlist-end",
        str(maximum_items),
        "--socket-timeout",
        str(min(timeout_seconds, 60)),
        "--retries",
        "2",
        "--fragment-retries",
        "2",
        "--max-filesize",
        str(maximum_bytes),
        "--paths",
        str(output),
        "--output",
        "%(extractor)s/%(id)s/%(id)s.%(ext)s",
    ]
    if not media_download_allowed:
        command.extend((
            "--ignore-errors",
            "--skip-download",
            "--dump-json",
        ))
    else:
        command.extend((
            "--write-info-json",
            "--write-comments",
            "--write-subs",
            "--write-auto-subs",
            "--write-thumbnail",
            "--print-json",
        ))
    if cookie_file is not None:
        command.extend(("--cookies", str(cookie_file)))
    command.append(url)
    return command


def _gallery_dl_command(
    *, executable: str, url: str, maximum_items: int, timeout_seconds: int,
) -> list[str]:
    return [
        executable,
        "--config-ignore",
        "--no-input",
        "--no-download",
        "--resolve-json",
        "--option",
        "output.jsonl=true",
        "--post-range",
        f"1-{maximum_items}",
        "--http-timeout",
        str(min(timeout_seconds, 60)),
        "--retries",
        "2",
        "--sleep-request",
        "0.5",
        url,
    ]


def _gallery_dl_mappings(value: object) -> list[Mapping[str, object]]:
    rows: list[Mapping[str, object]] = []
    if isinstance(value, Mapping):
        keys = {str(key).casefold() for key in value}
        if keys.intersection({
            "id", "post_id", "tweet_id", "shortcode", "date", "timestamp",
            "likes", "like_count", "views", "view_count", "comments", "comment_count",
        }):
            rows.append(value)
        for child in value.values():
            rows.extend(_gallery_dl_mappings(child))
    elif isinstance(value, list):
        for child in value:
            rows.extend(_gallery_dl_mappings(child))
    return rows


def _gallery_dl_primary_mappings(value: object) -> list[Mapping[str, object]]:
    """Return one top-level metadata object per gallery-dl event.

    gallery-dl emits JSONL events such as ``[2, metadata]`` and
    ``[3, url, metadata]``. Recursing through the metadata tree would mistake
    nested creator/board objects for independent posts and bias the sample.
    """

    if isinstance(value, list):
        if value and type(value[0]) is int and isinstance(value[-1], Mapping):
            return [value[-1]]
        rows: list[Mapping[str, object]] = []
        for child in value:
            rows.extend(_gallery_dl_primary_mappings(child))
        return rows
    if isinstance(value, Mapping):
        return [value]
    return []


def _gallery_dl_rows(log_path: Path, *, maximum_items: int) -> list[Mapping[str, object]]:
    rows: list[Mapping[str, object]] = []
    with log_path.open("rb") as handle:
        for raw_line in handle:
            if len(raw_line) > 2_000_000:
                continue
            try:
                decoded = json.loads(raw_line.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                continue
            rows.extend(_gallery_dl_primary_mappings(decoded))
            if len(rows) >= maximum_items:
                break
    # gallery-dl versions or extractor-level output overrides may still emit a
    # single pretty-printed JSON array. Admit that bounded legacy shape without
    # changing the no-download/network contract.
    if not rows and log_path.stat().st_size <= 5_000_000:
        try:
            decoded = json.loads(log_path.read_text(encoding="utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            decoded = None
        rows.extend(_gallery_dl_primary_mappings(decoded))
    unique: list[Mapping[str, object]] = []
    seen: set[str] = set()
    for index, row in enumerate(rows):
        identity = str(row.get("id") or row.get("post_id") or row.get("tweet_id") or row.get("shortcode") or index)
        if identity in seen:
            continue
        seen.add(identity)
        unique.append(row)
        if len(unique) >= maximum_items:
            break
    return unique


def _gallery_dl_publication_timestamp(row: Mapping[str, object]) -> float | None:
    raw = row.get("timestamp") or row.get("date") or row.get("created_at") or row.get("published_at")
    if type(raw) in {int, float} and math.isfinite(float(raw)):
        return float(raw)
    normalized = _public_timestamp(raw)
    if normalized is None:
        return None
    return datetime.fromisoformat(normalized.replace("Z", "+00:00")).timestamp()


def _run_gallery_dl(
    *,
    executable: str,
    version: str,
    command_runner: Callable[..., subprocess.CompletedProcess],
    url: str,
    source_plan: Mapping[str, object],
    source_output: Path,
    observed_at: str,
    rights: str,
    timeout_seconds: int,
    maximum_items: int,
) -> tuple[dict[str, object], list[dict[str, object]]]:
    log_path = source_output / "collector-output.jsonl"
    command = _gallery_dl_command(
        executable=executable, url=url, maximum_items=maximum_items,
        timeout_seconds=timeout_seconds,
    )
    with log_path.open("wb") as log:
        completed = command_runner(
            command, stdout=log, stderr=subprocess.PIPE, timeout=timeout_seconds,
            check=False, shell=False,
        )
    rows = _gallery_dl_rows(log_path, maximum_items=maximum_items)
    if not rows:
        raise SocialCollectionExecutionError(
            "gallery-dl returned no public metadata rows: "
            + bytes(completed.stderr or b"")[:500].decode("utf-8", errors="replace")
        )
    source_sha = str(source_plan["source_url_sha256"])
    signal_source_uri = _redacted_source_uri(url, source_sha)
    signals: list[dict[str, object]] = []
    organic_rows: list[dict[str, object]] = []
    sequence = 0
    for index, row in enumerate(rows):
        metrics: dict[str, float] = {}
        aliases = {
            "view_count": ("view_count", "views", "play_count"),
            "like_count": (
                "like_count", "likes", "favorite_count", "favorite_user_count", "favourites",
            ),
            "comment_count": ("comment_count", "comments", "reply_count", "replies"),
            "repost_count": (
                "repost_count", "reposts", "retweet_count", "repin_count", "shares", "share_count",
            ),
        }
        for metric, fields in aliases.items():
            raw = next((row.get(field) for field in fields if row.get(field) is not None), None)
            if type(raw) in {int, float} and math.isfinite(float(raw)) and float(raw) >= 0:
                metrics[metric] = float(raw)
                sequence += 1
                signals.append(_metric_signal(
                    source_sha256=source_sha, sequence=sequence,
                    platform=str(source_plan["platform"]), source_uri=signal_source_uri,
                    observed_at=observed_at, rights=rights, metric=metric, value=float(raw),
                    sample_size=1, features=["public_media_metadata"],
                ))
        organic_rows.append({
            "id": hashlib.sha256(f"{source_sha}:{index}".encode()).hexdigest(),
            "title": next((row.get(field) for field in ("content", "caption", "description", "title", "text") if row.get(field)), None),
            "timestamp": _gallery_dl_publication_timestamp(row),
            **metrics,
            "platform_interaction_count": sum(
                value for key, value in metrics.items() if key != "view_count"
            ),
        })
    attention_metric = "view_count" if any("view_count" in row for row in organic_rows) else "platform_interaction_count"
    organic = _yt_dlp_organic_summary(
        organic_rows, source_sha256=source_sha, observed_at=observed_at,
        primary_attention_metric=attention_metric,
    )
    if not signals:
        signals.append(_metric_signal(
            source_sha256=source_sha, sequence=1, platform=str(source_plan["platform"]),
            source_uri=signal_source_uri, observed_at=observed_at, rights=rights,
            metric="item_count", value=len(rows), sample_size=len(rows),
            features=["public_media_metadata"],
        ))
    return ({
        "source_url_sha256": source_sha,
        "connector_id": "gallery-dl",
        "connector_revision": source_plan["connector_revision"],
        "connector_package_version": version,
        "implementation_contract": "bounded_no_download_public_metadata_v1",
        "status": "completed" if completed.returncode == 0 else "completed_with_item_handoffs",
        "return_code": completed.returncode,
        "output_log_sha256": hashlib.sha256(log_path.read_bytes()).hexdigest(),
        "stderr_excerpt": bytes(completed.stderr or b"")[:1_000].decode("utf-8", errors="replace"),
        "normalized_signal_count": len(signals),
        "public_freshness": {key: organic[key] for key in (
            "timestamped_item_count", "recent_item_count_90d", "recent_item_count_180d",
            "oldest_publication_at", "newest_publication_at",
        )},
        "organic_signal_summary": organic,
        "abstract_content_pattern_counts": organic["abstract_content_pattern_counts"],
        "captcha_or_auth_bypass_attempted": False,
        "raw_content_training_admitted": False,
    }, signals)


def _json_object(response: PublicHttpResponse, name: str) -> Mapping[str, object]:
    try:
        value = json.loads(response.body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise SocialCollectionExecutionError(f"{name} returned invalid UTF-8 JSON") from error
    if not isinstance(value, Mapping):
        raise SocialCollectionExecutionError(f"{name} response must be an object")
    return value


def _raw_receipt(
    source_output: Path,
    response: PublicHttpResponse,
    *,
    label: str,
) -> dict[str, object]:
    digest = hashlib.sha256(response.body).hexdigest()
    path = source_output / f"raw-{label}-{digest}.bin"
    atomic_write_bytes(path, response.body)
    return {
        "label": label,
        "sha256": digest,
        "bytes": len(response.body),
        "http_status": response.status_code,
        "content_type": response.headers.get("content-type", "unknown"),
        "credential_sent": False,
    }


def _format_features(payload: Mapping[str, object], *, thread_present: bool) -> list[str]:
    features = ["public_post"]
    embed = payload.get("embed")
    embed_type = ""
    if isinstance(embed, Mapping):
        embed_type = str(embed.get("$type", "")).casefold()
    if "images" in embed_type:
        features.append("image")
    if "video" in embed_type:
        features.append("video")
    if "external" in embed_type:
        features.append("external_link")
    if "record" in embed_type:
        features.append("quote")
    if thread_present:
        features.append("threaded_conversation")
    return sorted(set(features))


def _metric_signal(
    *,
    source_sha256: str,
    sequence: int,
    platform: str,
    source_uri: str,
    observed_at: str,
    rights: str,
    metric: str,
    value: int | float,
    sample_size: int,
    features: Sequence[str],
) -> dict[str, object]:
    return {
        "signal_id": f"{source_sha256[:20]}-{sequence:02d}",
        "platform": platform,
        "source_kind": "authorized_open_source_collector",
        "source_uri": source_uri,
        "observed_at": observed_at,
        "rights": rights,
        "metric": metric,
        "value": value,
        "sample_size": sample_size,
        "format_features": list(features),
    }


def _redacted_source_uri(source_url: str, source_sha256: str) -> str:
    """Retain platform provenance without leaking handles, post IDs or query data."""

    parsed = urlparse(source_url)
    if not parsed.hostname:
        raise SocialCollectionExecutionError("source URL is missing a hostname")
    return f"https://{parsed.hostname.casefold()}/source/{source_sha256}"


def _public_timestamp(value: object) -> str | None:
    """Normalize a public source timestamp without retaining source text."""

    if not isinstance(value, str) or not value.strip() or len(value) > 80:
        return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _freshness_counts(publication_times: Sequence[datetime], observed_at: str) -> dict[str, object]:
    observed = datetime.fromisoformat(observed_at.replace("Z", "+00:00")).astimezone(timezone.utc)
    normalized = sorted(
        item.astimezone(timezone.utc) for item in publication_times if item <= observed + timedelta(days=1)
    )
    return {
        "timestamped_item_count": len(normalized),
        "recent_item_count_90d": sum(item >= observed - timedelta(days=90) for item in normalized),
        "recent_item_count_180d": sum(item >= observed - timedelta(days=180) for item in normalized),
        "oldest_publication_at": (
            normalized[0].isoformat().replace("+00:00", "Z") if normalized else None
        ),
        "newest_publication_at": (
            normalized[-1].isoformat().replace("+00:00", "Z") if normalized else None
        ),
    }


def _abstract_content_patterns(value: object) -> set[str]:
    """Derive non-copying editorial structure labels and immediately discard text."""

    if not isinstance(value, str):
        return set()
    text = " ".join(value.casefold().split())[:1_000]
    if not text:
        return set()
    patterns: set[str] = set()
    if "?" in text:
        patterns.add("question_hook")
    if re.search(r"\b\d+(?:[.,]\d+)?%?\b", text):
        patterns.add("number_or_data_hook")
    if re.match(r"^(how|why|what|when|where)\b", text):
        patterns.add("answer_first_hook")
    if re.search(r"\b(vs\.?|versus|compared?|comparison)\b", text):
        patterns.add("comparison_frame")
    if re.search(r"\b(i|we|our|my)\b", text):
        patterns.add("first_person_evidence")
    if re.search(r"\b(case study|study|research|data|benchmark|tested|experiment)\b", text):
        patterns.add("evidence_led_frame")
    if re.search(r"\b(free|template|checklist|calculator|generator|tool)\b", text):
        patterns.add("portable_utility")
    if re.search(r"\b(launch|launched|new|update|release|introducing)\b", text):
        patterns.add("news_or_launch_frame")
    if re.search(r"\b(trend|2026|this month|this week|today|now)\b", text):
        patterns.add("time_bound_relevance")
    if re.search(r"\b(mistake|wrong|myth|doesn.t|don.t|stop|instead|but)\b", text):
        patterns.add("contrarian_correction")
    return patterns


def _run_bluesky(
    *,
    client: BoundedPublicHttpClient,
    url: str,
    source_plan: Mapping[str, object],
    source_output: Path,
    observed_at: str,
    rights: str,
    timeout_seconds: int,
    maximum_bytes: int,
    maximum_items: int,
) -> tuple[dict[str, object], list[dict[str, object]]]:
    parts = [part for part in urlparse(url).path.split("/") if part]
    if not (
        len(parts) in {2, 4}
        and parts[0] == "profile"
        and (len(parts) == 2 or parts[2] == "post")
    ):
        raise SocialCollectionExecutionError(
            "Bluesky source must match /profile/{actor} or /profile/{actor}/post/{rkey}"
        )
    actor = parts[1]
    raw_artifacts: list[dict[str, object]] = []
    if actor.startswith("did:"):
        did = actor
    else:
        resolve_url = (
            "https://public.api.bsky.app/xrpc/com.atproto.identity.resolveHandle?"
            + urlencode({"handle": actor})
        )
        resolved = client.get(
            resolve_url,
            timeout_seconds=min(timeout_seconds, 60),
            maximum_bytes=min(maximum_bytes, 5_000_000),
        )
        raw_artifacts.append(_raw_receipt(source_output, resolved, label="resolve-handle"))
        did = str(_json_object(resolved, "Bluesky handle resolution").get("did", ""))
    if not did.startswith("did:") or len(did) > 256:
        raise SocialCollectionExecutionError("Bluesky actor did not resolve to a valid DID")
    if len(parts) == 2:
        feed_url = (
            "https://public.api.bsky.app/xrpc/app.bsky.feed.getAuthorFeed?"
            + urlencode({"actor": did, "limit": min(maximum_items, 100), "filter": "posts_no_replies"})
        )
        response = client.get(
            feed_url,
            timeout_seconds=min(timeout_seconds, 60),
            maximum_bytes=min(maximum_bytes, 5_000_000),
        )
        raw_artifacts.append(_raw_receipt(source_output, response, label="author-feed"))
        decoded = _json_object(response, "Bluesky author feed")
        feed = decoded.get("feed")
        if not isinstance(feed, list) or not feed:
            raise SocialCollectionExecutionError("Bluesky author feed contained no public posts")
        source_sha = str(source_plan["source_url_sha256"])
        signal_source_uri = _redacted_source_uri(url, source_sha)
        signals: list[dict[str, object]] = []
        organic_rows: list[dict[str, object]] = []
        sequence = 0
        for item_index, item in enumerate(feed[:maximum_items]):
            if not isinstance(item, Mapping) or not isinstance(item.get("post"), Mapping):
                continue
            post = item["post"]
            assert isinstance(post, Mapping)
            record = post.get("record")
            record = record if isinstance(record, Mapping) else {}
            features = _format_features(post, thread_present=False)
            metrics: dict[str, int] = {}
            for metric, field in (
                ("like_count", "likeCount"), ("repost_count", "repostCount"),
                ("reply_count", "replyCount"), ("quote_count", "quoteCount"),
            ):
                value = post.get(field, 0)
                if type(value) is not int or value < 0:
                    raise SocialCollectionExecutionError("Bluesky engagement count is invalid")
                metrics[metric] = value
                sequence += 1
                signals.append(_metric_signal(
                    source_sha256=source_sha, sequence=sequence, platform="bluesky",
                    source_uri=signal_source_uri, observed_at=observed_at, rights=rights,
                    metric=metric, value=value, sample_size=1, features=features,
                ))
            organic_rows.append({
                "id": hashlib.sha256(f"{source_sha}:{item_index}".encode()).hexdigest(),
                "title": record.get("text"),
                "timestamp": (
                    datetime.fromisoformat(str(record.get("createdAt")).replace("Z", "+00:00")).timestamp()
                    if _public_timestamp(record.get("createdAt")) is not None
                    else None
                ),
                **metrics,
                "platform_interaction_count": sum(metrics.values()),
            })
        if not signals:
            raise SocialCollectionExecutionError("Bluesky author feed had no measurable posts")
        organic = _yt_dlp_organic_summary(
            organic_rows, source_sha256=source_sha, observed_at=observed_at,
            primary_attention_metric="platform_interaction_count",
        )
        return ({
            "source_url_sha256": source_sha,
            "connector_id": "atproto",
            "connector_revision": source_plan["connector_revision"],
            "implementation_contract": "official_public_author_feed_appview_v1",
            "status": "completed",
            "http_request_count": len(raw_artifacts),
            "raw_artifacts": raw_artifacts,
            "normalized_signal_count": len(signals),
            "public_freshness": {key: organic[key] for key in (
                "timestamped_item_count", "recent_item_count_90d", "recent_item_count_180d",
                "oldest_publication_at", "newest_publication_at",
            )},
            "organic_signal_summary": organic,
            "abstract_content_pattern_counts": organic["abstract_content_pattern_counts"],
            "captcha_or_auth_bypass_attempted": False,
            "raw_content_training_admitted": False,
        }, signals)

    rkey = parts[3]
    at_uri = f"at://{did}/app.bsky.feed.post/{rkey}"
    thread_url = (
        "https://public.api.bsky.app/xrpc/app.bsky.feed.getPostThread?"
        + urlencode({"uri": at_uri, "depth": 2, "parentHeight": 1})
    )
    response = client.get(
        thread_url,
        timeout_seconds=min(timeout_seconds, 60),
        maximum_bytes=min(maximum_bytes, 5_000_000),
    )
    raw_artifacts.append(_raw_receipt(source_output, response, label="post-thread"))
    decoded = _json_object(response, "Bluesky thread")
    thread = decoded.get("thread")
    if not isinstance(thread, Mapping) or not isinstance(thread.get("post"), Mapping):
        raise SocialCollectionExecutionError("Bluesky thread is unavailable or blocked")
    post = thread["post"]
    assert isinstance(post, Mapping)
    replies = thread.get("replies")
    record = post.get("record")
    published_at = _public_timestamp(
        record.get("createdAt") if isinstance(record, Mapping) else None
    ) or _public_timestamp(post.get("indexedAt"))
    features = _format_features(post, thread_present=isinstance(replies, list) and bool(replies))
    source_sha = str(source_plan["source_url_sha256"])
    signal_source_uri = _redacted_source_uri(url, source_sha)
    signals = []
    for sequence, (metric, field) in enumerate(
        (
            ("like_count", "likeCount"),
            ("repost_count", "repostCount"),
            ("reply_count", "replyCount"),
            ("quote_count", "quoteCount"),
        ),
        start=1,
    ):
        value = post.get(field, 0)
        if type(value) is not int or value < 0:
            raise SocialCollectionExecutionError("Bluesky engagement count is invalid")
        signals.append(
            _metric_signal(
                source_sha256=source_sha,
                sequence=sequence,
                platform="bluesky",
                source_uri=signal_source_uri,
                observed_at=observed_at,
                rights=rights,
                metric=metric,
                value=value,
                sample_size=1,
                features=features,
            )
        )
    return (
        {
            "source_url_sha256": source_sha,
            "connector_id": "atproto",
            "connector_revision": source_plan["connector_revision"],
            "implementation_contract": "official_public_appview_rest_v1",
            "status": "completed",
            "http_request_count": len(raw_artifacts),
            "raw_artifacts": raw_artifacts,
            "normalized_signal_count": len(signals),
            "public_freshness": {
                "timestamped_item_count": int(published_at is not None),
                "recent_item_count_90d": None,
                "recent_item_count_180d": None,
                "oldest_publication_at": published_at,
                "newest_publication_at": published_at,
            },
            "captcha_or_auth_bypass_attempted": False,
            "raw_content_training_admitted": False,
        },
        signals,
    )


def _run_mastodon(
    *,
    client: BoundedPublicHttpClient,
    url: str,
    source_plan: Mapping[str, object],
    source_output: Path,
    observed_at: str,
    rights: str,
    timeout_seconds: int,
    maximum_bytes: int,
    maximum_items: int,
) -> tuple[dict[str, object], list[dict[str, object]]]:
    parsed = urlparse(url)
    parts = [part for part in parsed.path.split("/") if part]
    if not parts:
        raise SocialCollectionExecutionError("Mastodon public source path is empty")
    if not parts[-1].isdigit():
        handle = parts[-1].removeprefix("@")
        if not re.fullmatch(r"[A-Za-z0-9_.-]{1,64}", handle):
            raise SocialCollectionExecutionError("Mastodon public profile handle is invalid")
        origin = f"https://{parsed.hostname}"
        lookup_url = f"{origin}/api/v1/accounts/lookup?" + urlencode({"acct": handle})
        lookup_response = client.get(
            lookup_url,
            timeout_seconds=min(timeout_seconds, 60),
            maximum_bytes=min(maximum_bytes, 5_000_000),
        )
        account = _json_object(lookup_response, "Mastodon account lookup")
        account_id = str(account.get("id", ""))
        if not re.fullmatch(r"[0-9]+", account_id):
            raise SocialCollectionExecutionError("Mastodon account lookup returned an invalid id")
        statuses_url = f"{origin}/api/v1/accounts/{quote(account_id, safe='')}/statuses?" + urlencode({
            "limit": min(maximum_items, 40), "exclude_replies": "true", "exclude_reblogs": "true",
        })
        statuses_response = client.get(
            statuses_url,
            timeout_seconds=min(timeout_seconds, 60),
            maximum_bytes=min(maximum_bytes, 5_000_000),
        )
        try:
            statuses = json.loads(statuses_response.body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise SocialCollectionExecutionError("Mastodon statuses returned invalid JSON") from error
        if not isinstance(statuses, list) or not statuses:
            raise SocialCollectionExecutionError("Mastodon profile contained no public statuses")
        raw_artifacts = [
            _raw_receipt(source_output, lookup_response, label="account-lookup"),
            _raw_receipt(source_output, statuses_response, label="account-statuses"),
        ]
        source_sha = str(source_plan["source_url_sha256"])
        signal_source_uri = _redacted_source_uri(url, source_sha)
        signals: list[dict[str, object]] = []
        organic_rows: list[dict[str, object]] = []
        sequence = 0
        for item_index, status in enumerate(statuses[:maximum_items]):
            if not isinstance(status, Mapping) or status.get("visibility") not in {"public", "unlisted"}:
                continue
            metrics: dict[str, int] = {}
            for metric, field in (
                ("favourite_count", "favourites_count"), ("boost_count", "reblogs_count"),
                ("reply_count", "replies_count"),
            ):
                value = status.get(field, 0)
                if type(value) is not int or value < 0:
                    raise SocialCollectionExecutionError("Mastodon engagement count is invalid")
                metrics[metric] = value
                sequence += 1
                signals.append(_metric_signal(
                    source_sha256=source_sha, sequence=sequence, platform="mastodon",
                    source_uri=signal_source_uri, observed_at=observed_at, rights=rights,
                    metric=metric, value=value, sample_size=1, features=["public_post"],
                ))
            normalized_time = _public_timestamp(status.get("created_at"))
            organic_rows.append({
                "id": hashlib.sha256(f"{source_sha}:{item_index}".encode()).hexdigest(),
                "title": re.sub(r"<[^>]+>", " ", str(status.get("content", ""))),
                "timestamp": (
                    datetime.fromisoformat(normalized_time.replace("Z", "+00:00")).timestamp()
                    if normalized_time is not None else None
                ),
                **metrics,
                "platform_interaction_count": sum(metrics.values()),
            })
        if not signals:
            raise SocialCollectionExecutionError("Mastodon profile had no measurable public statuses")
        organic = _yt_dlp_organic_summary(
            organic_rows, source_sha256=source_sha, observed_at=observed_at,
            primary_attention_metric="platform_interaction_count",
        )
        return ({
            "source_url_sha256": source_sha,
            "connector_id": "mastodon.py",
            "connector_revision": source_plan["connector_revision"],
            "implementation_contract": "same_origin_public_account_statuses_rest_v1",
            "status": "completed",
            "http_request_count": 2,
            "raw_artifacts": raw_artifacts,
            "normalized_signal_count": len(signals),
            "public_freshness": {key: organic[key] for key in (
                "timestamped_item_count", "recent_item_count_90d", "recent_item_count_180d",
                "oldest_publication_at", "newest_publication_at",
            )},
            "organic_signal_summary": organic,
            "abstract_content_pattern_counts": organic["abstract_content_pattern_counts"],
            "captcha_or_auth_bypass_attempted": False,
            "raw_content_training_admitted": False,
        }, signals)
    if not parts[-1].isdigit():
        raise SocialCollectionExecutionError(
            "Mastodon public status URL must end in a numeric status id"
        )
    status_id = parts[-1]
    origin = f"https://{parsed.hostname}"
    response = client.get(
        f"{origin}/api/v1/statuses/{quote(status_id, safe='')}",
        timeout_seconds=min(timeout_seconds, 60),
        maximum_bytes=min(maximum_bytes, 5_000_000),
    )
    context = client.get(
        f"{origin}/api/v1/statuses/{quote(status_id, safe='')}/context",
        timeout_seconds=min(timeout_seconds, 60),
        maximum_bytes=min(maximum_bytes, 5_000_000),
    )
    raw_artifacts = [
        _raw_receipt(source_output, response, label="status"),
        _raw_receipt(source_output, context, label="context"),
    ]
    status = _json_object(response, "Mastodon status")
    context_payload = _json_object(context, "Mastodon context")
    if status.get("visibility") not in {"public", "unlisted"}:
        raise SocialCollectionExecutionError("Mastodon status is not publicly measurable")
    attachments = status.get("media_attachments")
    features = ["public_post"]
    if isinstance(attachments, list):
        for attachment in attachments[:12]:
            if isinstance(attachment, Mapping):
                media_type = str(attachment.get("type", "")).casefold()
                if media_type in {"image", "video", "audio", "gifv"}:
                    features.append("video" if media_type == "gifv" else media_type)
    if isinstance(status.get("poll"), Mapping):
        features.append("poll")
    if isinstance(status.get("card"), Mapping):
        features.append("external_link")
    descendants = context_payload.get("descendants")
    ancestors = context_payload.get("ancestors")
    if (isinstance(descendants, list) and descendants) or (
        isinstance(ancestors, list) and ancestors
    ):
        features.append("threaded_conversation")
    published_at = _public_timestamp(status.get("created_at"))
    source_sha = str(source_plan["source_url_sha256"])
    signal_source_uri = _redacted_source_uri(url, source_sha)
    signals = []
    for sequence, (metric, field) in enumerate(
        (
            ("favourite_count", "favourites_count"),
            ("boost_count", "reblogs_count"),
            ("reply_count", "replies_count"),
        ),
        start=1,
    ):
        value = status.get(field, 0)
        if type(value) is not int or value < 0:
            raise SocialCollectionExecutionError("Mastodon engagement count is invalid")
        signals.append(
            _metric_signal(
                source_sha256=source_sha,
                sequence=sequence,
                platform="mastodon",
                source_uri=signal_source_uri,
                observed_at=observed_at,
                rights=rights,
                metric=metric,
                value=value,
                sample_size=1,
                features=sorted(set(features)),
            )
        )
    return (
        {
            "source_url_sha256": source_sha,
            "connector_id": "mastodon.py",
            "connector_revision": source_plan["connector_revision"],
            "implementation_contract": "same_origin_public_status_rest_v1",
            "status": "completed",
            "http_request_count": 2,
            "raw_artifacts": raw_artifacts,
            "normalized_signal_count": len(signals),
            "public_freshness": {
                "timestamped_item_count": int(published_at is not None),
                "recent_item_count_90d": None,
                "recent_item_count_180d": None,
                "oldest_publication_at": published_at,
                "newest_publication_at": published_at,
            },
            "captcha_or_auth_bypass_attempted": False,
            "raw_content_training_admitted": False,
        },
        signals,
    )


def _run_feed(
    *,
    client: BoundedPublicHttpClient,
    url: str,
    source_plan: Mapping[str, object],
    source_output: Path,
    observed_at: str,
    rights: str,
    timeout_seconds: int,
    maximum_bytes: int,
    maximum_items: int,
    version_resolver: Callable[[str], str],
) -> tuple[dict[str, object], list[dict[str, object]]]:
    try:
        import feedparser
    except ImportError as error:
        raise SocialCollectionExecutionError(
            "feedparser is not installed; install the pinned social optional dependency"
        ) from error
    installed_version = version_resolver("feedparser")
    if installed_version != "6.0.12":
        raise SocialCollectionExecutionError(
            "feedparser version drifted from the admitted 6.0.12 package"
        )
    feed_url = url
    if source_plan.get("platform") == "reddit":
        parsed_source = urlparse(url)
        path = parsed_source.path.rstrip("/")
        if not path.casefold().endswith((".rss", ".xml")):
            if re.fullmatch(r"/r/[A-Za-z0-9_]+", path):
                path += "/new/.rss"
            else:
                path += "/.rss"
            feed_url = f"https://{parsed_source.hostname}{path}"
    response = client.get(
        feed_url,
        timeout_seconds=min(timeout_seconds, 60),
        maximum_bytes=min(maximum_bytes, 5_000_000),
    )

    lowered = response.body[:65_536].lower()
    if b"<!doctype" in lowered or b"<!entity" in lowered:
        raise SocialCollectionExecutionError("feed XML declarations are not admitted")
    parsed = feedparser.parse(
        response.body,
        resolve_relative_uris=False,
        sanitize_html=True,
    )
    entries = list(parsed.get("entries") or [])[:maximum_items]
    if not entries:
        raise SocialCollectionExecutionError("public feed contained no parseable entries")
    features = ["rss_or_atom"]
    abstract_patterns: Counter[str] = Counter()
    enclosure_count = 0
    publication_times: list[datetime] = []
    for entry in entries:
        if not isinstance(entry, Mapping):
            continue
        abstract_patterns.update(_abstract_content_patterns(entry.get("title")))
        parsed_time = entry.get("published_parsed") or entry.get("updated_parsed")
        if parsed_time is not None:
            try:
                publication_times.append(
                    datetime(*tuple(parsed_time)[:6], tzinfo=timezone.utc)
                )
            except (TypeError, ValueError):
                pass
        enclosures = entry.get("enclosures") or []
        if isinstance(enclosures, list):
            enclosure_count += len(enclosures)
            for enclosure in enclosures[:12]:
                if not isinstance(enclosure, Mapping):
                    continue
                media_type = str(enclosure.get("type", "")).casefold()
                if media_type.startswith("image/"):
                    features.append("image")
                elif media_type.startswith("video/"):
                    features.append("video")
                elif media_type.startswith("audio/"):
                    features.append("audio")
    source_sha = str(source_plan["source_url_sha256"])
    signal_source_uri = _redacted_source_uri(url, source_sha)
    signals = [
        _metric_signal(
            source_sha256=source_sha,
            sequence=1,
            platform="feed",
            source_uri=signal_source_uri,
            observed_at=observed_at,
            rights=rights,
            metric="item_count",
            value=len(entries),
            sample_size=len(entries),
            features=sorted(set(features)),
        ),
        _metric_signal(
            source_sha256=source_sha,
            sequence=2,
            platform="feed",
            source_uri=signal_source_uri,
            observed_at=observed_at,
            rights=rights,
            metric="enclosure_count",
            value=enclosure_count,
            sample_size=len(entries),
            features=sorted(set(features)),
        ),
        _metric_signal(
            source_sha256=source_sha,
            sequence=3,
            platform="feed",
            source_uri=signal_source_uri,
            observed_at=observed_at,
            rights=rights,
            metric="timestamped_item_count",
            value=len(publication_times),
            sample_size=len(entries),
            features=sorted(set(features)),
        ),
    ]
    raw = _raw_receipt(source_output, response, label="feed")
    public_freshness = _freshness_counts(publication_times, observed_at)
    return (
        {
            "source_url_sha256": source_sha,
            "connector_id": "feedparser",
            "connector_revision": source_plan["connector_revision"],
            "connector_package_version": installed_version,
            "implementation_contract": "bounded_bytes_to_feedparser_v1",
            "feed_endpoint_sha256": hashlib.sha256(feed_url.encode("utf-8")).hexdigest(),
            "status": "completed",
            "http_request_count": 1,
            "raw_artifacts": [raw],
            "normalized_signal_count": len(signals),
            "public_freshness": public_freshness,
            "abstract_content_pattern_counts": dict(sorted(abstract_patterns.items())),
            "captcha_or_auth_bypass_attempted": False,
            "raw_content_training_admitted": False,
        },
        signals,
    )


def _run_static_html_metadata(
    *,
    client: BoundedPublicHttpClient,
    url: str,
    source_plan: Mapping[str, object],
    source_output: Path,
    observed_at: str,
    rights: str,
    timeout_seconds: int,
    maximum_bytes: int,
    maximum_items: int,
    version_resolver: Callable[[str], str],
) -> tuple[dict[str, object], list[dict[str, object]]]:
    try:
        from bs4 import BeautifulSoup
    except ImportError as error:
        raise SocialCollectionExecutionError("beautifulsoup4 is required for static public pages") from error
    installed_version = version_resolver("beautifulsoup4")
    if installed_version != "4.15.0":
        raise SocialCollectionExecutionError("beautifulsoup4 version drifted from 4.15.0")
    response = client.get(
        url, timeout_seconds=min(timeout_seconds, 60),
        maximum_bytes=min(maximum_bytes, 5_000_000),
    )
    content_type = response.headers.get("content-type", "").casefold()
    if "html" not in content_type and b"<html" not in response.body[:4096].casefold():
        raise SocialCollectionExecutionError("public static page did not return HTML")
    soup = BeautifulSoup(response.body, "lxml")
    raw = _raw_receipt(source_output, response, label="static-html")
    records = list(soup.find_all("article", limit=maximum_items))
    if not records:
        records = [soup]
    publication_times: list[datetime] = []
    patterns: Counter[str] = Counter()
    for record in records[:maximum_items]:
        title = None
        for selector in (
            ("meta", {"property": "og:title"}), ("meta", {"name": "description"}),
            ("meta", {"property": "og:description"}),
        ):
            tag = record.find(selector[0], attrs=selector[1])
            if tag is not None and tag.get("content"):
                title = str(tag.get("content"))
                break
        if title is None:
            heading = record.find(["h1", "h2", "h3"])
            title = heading.get_text(" ", strip=True) if heading is not None else ""
        patterns.update(_abstract_content_patterns(title))
        candidates = [tag.get("datetime") for tag in record.find_all("time")]
        for attrs in (
            {"property": "article:published_time"}, {"name": "date"},
            {"itemprop": "datePublished"},
        ):
            tag = record.find("meta", attrs=attrs)
            if tag is not None:
                candidates.append(tag.get("content"))
        for candidate in candidates:
            normalized = _public_timestamp(candidate)
            if normalized is not None:
                publication_times.append(datetime.fromisoformat(normalized.replace("Z", "+00:00")))
                break
    source_sha = str(source_plan["source_url_sha256"])
    signal_source_uri = _redacted_source_uri(url, source_sha)
    freshness = _freshness_counts(publication_times, observed_at)
    sample_size = len(records[:maximum_items])
    signals = [
        _metric_signal(
            source_sha256=source_sha, sequence=1, platform=str(source_plan["platform"]),
            source_uri=signal_source_uri, observed_at=observed_at, rights=rights,
            metric="item_count", value=sample_size,
            sample_size=sample_size, features=["static_public_html"],
        ),
        _metric_signal(
            source_sha256=source_sha, sequence=2, platform=str(source_plan["platform"]),
            source_uri=signal_source_uri, observed_at=observed_at, rights=rights,
            metric="timestamped_item_count", value=len(publication_times),
            sample_size=max(1, sample_size), features=["static_public_html"],
        ),
    ]
    return ({
        "source_url_sha256": source_sha,
        "connector_id": "beautifulsoup4",
        "connector_revision": source_plan["connector_revision"],
        "connector_package_version": installed_version,
        "implementation_contract": "bounded_static_html_no_script_execution_v1",
        "status": "completed",
        "http_request_count": 1,
        "raw_artifacts": [raw],
        "normalized_signal_count": len(signals),
        "public_freshness": freshness,
        "abstract_content_pattern_counts": dict(sorted(patterns.items())),
        "captcha_or_auth_bypass_attempted": False,
        "raw_content_training_admitted": False,
    }, signals)


def _yt_dlp_signals(
    *,
    log_path: Path,
    source_plan: Mapping[str, object],
    source_uri: str,
    observed_at: str,
    rights: str,
    maximum_items: int,
) -> list[dict[str, object]]:
    rows = _yt_dlp_rows(log_path, maximum_items=maximum_items)
    signals: list[dict[str, object]] = []
    source_sha = str(source_plan["source_url_sha256"])
    signal_source_uri = _redacted_source_uri(source_uri, source_sha)
    sequence = 0
    for row in rows:
        features = _yt_dlp_features(row)
        for metric, field in (
            ("view_count", "view_count"),
            ("like_count", "like_count"),
            ("comment_count", "comment_count"),
            ("repost_count", "repost_count"),
        ):
            value = row.get(field)
            if type(value) not in {int, float} or float(value) < 0:
                continue
            sequence += 1
            signals.append(
                _metric_signal(
                    source_sha256=source_sha,
                    sequence=sequence,
                    platform=str(source_plan["platform"]),
                    source_uri=signal_source_uri,
                    observed_at=observed_at,
                    rights=rights,
                    metric=metric,
                    value=value,
                    sample_size=1,
                    features=features,
                )
            )
    return signals


def _yt_dlp_rows(log_path: Path, *, maximum_items: int) -> list[Mapping[str, object]]:
    rows: list[Mapping[str, object]] = []
    with log_path.open("rb") as handle:
        for raw_line in handle:
            if len(raw_line) > 2_000_000:
                continue
            try:
                value = json.loads(raw_line.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                continue
            if isinstance(value, Mapping):
                entries = value.get("entries")
                if isinstance(entries, list):
                    rows.extend(item for item in entries if isinstance(item, Mapping))
                else:
                    rows.append(value)
            if len(rows) >= maximum_items:
                break
    return rows[:maximum_items]


def _yt_dlp_features(row: Mapping[str, object]) -> list[str]:
    features = ["public_media"]
    duration = row.get("duration")
    if type(duration) in {int, float} and float(duration) >= 0:
        features.append("short_form" if float(duration) <= 60 else "long_form")
    if row.get("subtitles") or row.get("automatic_captions"):
        features.append("subtitles")
    if row.get("chapters"):
        features.append("chapters")
    return sorted(set(features))


def _yt_dlp_publication_time(row: Mapping[str, object]) -> datetime | None:
    timestamp = row.get("timestamp") or row.get("release_timestamp")
    if type(timestamp) in {int, float} and math.isfinite(float(timestamp)):
        try:
            return datetime.fromtimestamp(float(timestamp), tz=timezone.utc)
        except (OverflowError, OSError, ValueError):
            pass
    upload_date = row.get("upload_date") or row.get("release_date")
    if isinstance(upload_date, str) and re.fullmatch(r"\d{8}", upload_date):
        try:
            return datetime.strptime(upload_date, "%Y%m%d").replace(tzinfo=timezone.utc)
        except ValueError:
            return None
    return None


def _yt_dlp_organic_summary(
    rows: Sequence[Mapping[str, object]],
    *,
    source_sha256: str,
    observed_at: str,
    primary_attention_metric: str = "view_count",
) -> dict[str, object]:
    """Build a content-free, within-source organic baseline.

    Absolute views reward large accounts. This summary instead compares each item
    with the median of the same collected source. Titles are discarded immediately
    after abstract structure labels are extracted; ids are retained only as hashes.
    """

    observed = datetime.fromisoformat(observed_at.replace("Z", "+00:00")).astimezone(timezone.utc)
    admitted: list[dict[str, object]] = []
    publication_times: list[datetime] = []
    all_patterns: Counter[str] = Counter()
    for index, row in enumerate(rows):
        published = _yt_dlp_publication_time(row)
        if published is not None and published <= observed + timedelta(days=1):
            publication_times.append(published)
        patterns = _abstract_content_patterns(row.get("title"))
        all_patterns.update(patterns)
        raw_id = str(row.get("id") or row.get("display_id") or index)
        metrics: dict[str, float] = {}
        for field in (
            "view_count", "like_count", "comment_count", "reply_count",
            "repost_count", "quote_count", "favourite_count", "boost_count",
            "platform_interaction_count",
        ):
            value = row.get(field)
            if type(value) in {int, float} and math.isfinite(float(value)) and float(value) >= 0:
                metrics[field] = float(value)
        admitted.append(
            {
                "item_sha256": hashlib.sha256(f"{source_sha256}:{raw_id}".encode()).hexdigest(),
                "published_at": published,
                "metrics": metrics,
                "patterns": sorted(patterns),
                "features": _yt_dlp_features(row),
            }
        )

    attention_values = [
        float(item["metrics"][primary_attention_metric])
        for item in admitted
        if primary_attention_metric in item["metrics"]
    ]
    attention_baseline = float(median(attention_values)) if attention_values else None
    interaction_rates: list[float] = []
    for item in admitted:
        metrics = item["metrics"]
        views = float(metrics.get("view_count", 0))
        if views <= 0:
            continue
        interactions = sum(float(metrics.get(field, 0)) for field in ("like_count", "comment_count", "repost_count"))
        interaction_rates.append(interactions / views)
    interaction_baseline = float(median(interaction_rates)) if interaction_rates else None

    relative_attention: list[float] = []
    top_patterns: Counter[str] = Counter()
    normalized_item_count = 0
    for item in admitted:
        metrics = item["metrics"]
        attention = float(metrics.get(primary_attention_metric, 0))
        if attention_baseline is None or attention_baseline <= 0 or primary_attention_metric not in metrics:
            continue
        index = attention / attention_baseline
        relative_attention.append(index)
        normalized_item_count += 1
        if index >= 2.0:
            top_patterns.update(item["patterns"])

    freshness = _freshness_counts(publication_times, observed_at)
    return {
        "schema": "ProofLaunchWithinSourceOrganicBaselineV1",
        "source_url_sha256": source_sha256,
        "item_count": len(admitted),
        **freshness,
        "view_measured_item_count": sum("view_count" in item["metrics"] for item in admitted),
        "primary_attention_metric": primary_attention_metric,
        "primary_attention_measured_item_count": len(attention_values),
        "interaction_rate_measured_item_count": len(interaction_rates),
        "normalized_item_count": normalized_item_count,
        "baseline_method": "same_source_median_no_cross_account_absolute_rank",
        "median_view_count": (
            round(attention_baseline, 6)
            if primary_attention_metric == "view_count" and attention_baseline is not None
            else None
        ),
        "median_primary_attention_count": (
            round(attention_baseline, 6) if attention_baseline is not None else None
        ),
        "median_public_interaction_rate": (
            round(interaction_baseline, 8) if interaction_baseline is not None else None
        ),
        "relative_attention_index_max": (
            round(max(relative_attention), 6) if relative_attention else None
        ),
        "relative_attention_index_ge_2_count": sum(value >= 2.0 for value in relative_attention),
        "abstract_content_pattern_counts": dict(sorted(all_patterns.items())),
        "top_relative_attention_pattern_counts": dict(sorted(top_patterns.items())),
        "raw_expression_retained": False,
        "public_item_identifiers_retained": False,
        "human_review_required_before_learning": True,
        "truth_boundary": (
            "Within-source public-counter normalization is descriptive. It does not establish "
            "organic causality, qualified demand, conversion, revenue or future virality."
        ),
    }


def execute_social_collection(
    request: Mapping[str, object],
    *,
    output_dir: str | Path,
    cookie_file: str | Path | None = None,
    executable_resolver: Callable[[str], str | None] = _resolve_executable,
    version_resolver: Callable[[str], str] = metadata.version,
    command_runner: Callable[..., subprocess.CompletedProcess] = subprocess.run,
    http_client: BoundedPublicHttpClient | None = None,
    clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
) -> dict[str, object]:
    """Execute admitted public collectors and compile a non-copying signal layer.

    Network adapters are read-only, credential-free and fail closed on private DNS,
    redirects, oversized responses, authentication walls or non-public content.
    Raw bytes remain isolated; only aggregate metrics and abstract format features
    may enter the strategy-facing signal snapshot.
    """

    plan = plan_social_collection(request)
    root = Path(output_dir).resolve()
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    if root.is_symlink() or not root.is_dir():
        raise SocialCollectionExecutionError("collection output must be a real directory")
    root.chmod(0o700)
    rights = str(plan["rights"])
    cookies = _safe_cookie_file(cookie_file, rights=rights)
    urls = request["urls"]
    budgets = plan["budgets"]
    client = http_client or BoundedPublicHttpClient()
    captured_at = clock().astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    runs: list[dict[str, object]] = []
    signals: list[dict[str, object]] = []
    for index, (url, source_plan) in enumerate(zip(urls, plan["plans"]), start=1):
        connector_id = str(source_plan["connector_id"])
        source_output = root / f"source-{index:04d}"
        source_output.mkdir(mode=0o700)
        try:
            if connector_id == "yt-dlp":
                executable = executable_resolver("yt-dlp")
                if not executable:
                    raise SocialCollectionExecutionError(
                        "yt-dlp is not installed; install the pinned social optional dependency"
                    )
                installed_version = version_resolver("yt-dlp")
                if installed_version != "2026.7.4":
                    raise SocialCollectionExecutionError(
                        "yt-dlp version drifted from the admitted 2026.7.4 package"
                    )
                log_path = source_output / "collector-output.jsonl"
                command = _yt_dlp_command(
                    executable=executable,
                    url=str(url),
                    output=source_output,
                    maximum_items=int(budgets["maximum_items"]),
                    maximum_bytes=int(budgets["maximum_bytes"]),
                    timeout_seconds=int(budgets["timeout_seconds"]),
                    media_download_allowed=bool(source_plan["media_download_allowed"]),
                    cookie_file=cookies,
                )
                with log_path.open("wb") as log:
                    completed = command_runner(
                        command,
                        stdout=log,
                        stderr=subprocess.PIPE,
                        timeout=int(budgets["timeout_seconds"]),
                        check=False,
                        shell=False,
                    )
                stderr = bytes(completed.stderr or b"")[:8_192].decode(
                    "utf-8", errors="replace"
                )
                yt_rows = _yt_dlp_rows(
                    log_path,
                    maximum_items=int(budgets["maximum_items"]),
                )
                source_signals = (
                    _yt_dlp_signals(
                        log_path=log_path,
                        source_plan=source_plan,
                        source_uri=str(url),
                        observed_at=captured_at,
                        rights=rights,
                        maximum_items=int(budgets["maximum_items"]),
                    )
                    if yt_rows
                    else []
                )
                organic_summary = (
                    _yt_dlp_organic_summary(
                        yt_rows,
                        source_sha256=str(source_plan["source_url_sha256"]),
                        observed_at=captured_at,
                    )
                    if yt_rows
                    else None
                )
                run = {
                    "source_url_sha256": source_plan["source_url_sha256"],
                    "connector_id": connector_id,
                    "connector_revision": source_plan["connector_revision"],
                    "connector_package_version": installed_version,
                    "status": (
                        "completed"
                        if completed.returncode == 0
                        else "completed_with_item_handoffs"
                        if yt_rows
                        else "human_handoff_required"
                    ),
                    "return_code": completed.returncode,
                    "output_log_sha256": hashlib.sha256(log_path.read_bytes()).hexdigest(),
                    "stderr_excerpt": stderr,
                    "normalized_signal_count": len(source_signals),
                    "public_freshness": (
                        {
                            key: organic_summary[key]
                            for key in (
                                "timestamped_item_count", "recent_item_count_90d",
                                "recent_item_count_180d", "oldest_publication_at",
                                "newest_publication_at",
                            )
                        }
                        if organic_summary is not None
                        else {}
                    ),
                    "organic_signal_summary": organic_summary,
                    "abstract_content_pattern_counts": (
                        organic_summary["abstract_content_pattern_counts"]
                        if organic_summary is not None
                        else {}
                    ),
                    "captcha_or_auth_bypass_attempted": False,
                    "raw_content_training_admitted": False,
                }
            elif connector_id == "gallery-dl":
                executable = executable_resolver("gallery-dl")
                if not executable:
                    raise SocialCollectionExecutionError(
                        "gallery-dl is not installed; install the pinned social optional dependency"
                    )
                installed_version = version_resolver("gallery-dl")
                if installed_version != "1.32.9":
                    raise SocialCollectionExecutionError(
                        "gallery-dl version drifted from the admitted 1.32.9 package"
                    )
                run, source_signals = _run_gallery_dl(
                    executable=executable,
                    version=installed_version,
                    command_runner=command_runner,
                    url=str(url),
                    source_plan=source_plan,
                    source_output=source_output,
                    observed_at=captured_at,
                    rights=rights,
                    timeout_seconds=int(budgets["timeout_seconds"]),
                    maximum_items=int(budgets["maximum_items"]),
                )
            elif connector_id == "beautifulsoup4":
                run, source_signals = _run_static_html_metadata(
                    client=client,
                    url=str(url),
                    source_plan=source_plan,
                    source_output=source_output,
                    observed_at=captured_at,
                    rights=rights,
                    timeout_seconds=int(budgets["timeout_seconds"]),
                    maximum_bytes=int(budgets["maximum_bytes"]),
                    maximum_items=int(budgets["maximum_items"]),
                    version_resolver=version_resolver,
                )
            elif connector_id == "atproto":
                run, source_signals = _run_bluesky(
                    client=client,
                    url=str(url),
                    source_plan=source_plan,
                    source_output=source_output,
                    observed_at=captured_at,
                    rights=rights,
                    timeout_seconds=int(budgets["timeout_seconds"]),
                    maximum_bytes=int(budgets["maximum_bytes"]),
                    maximum_items=int(budgets["maximum_items"]),
                )
            elif connector_id == "mastodon.py":
                run, source_signals = _run_mastodon(
                    client=client,
                    url=str(url),
                    source_plan=source_plan,
                    source_output=source_output,
                    observed_at=captured_at,
                    rights=rights,
                    timeout_seconds=int(budgets["timeout_seconds"]),
                    maximum_bytes=int(budgets["maximum_bytes"]),
                    maximum_items=int(budgets["maximum_items"]),
                )
            elif connector_id == "feedparser":
                run, source_signals = _run_feed(
                    client=client,
                    url=str(url),
                    source_plan=source_plan,
                    source_output=source_output,
                    observed_at=captured_at,
                    rights=rights,
                    timeout_seconds=int(budgets["timeout_seconds"]),
                    maximum_bytes=int(budgets["maximum_bytes"]),
                    maximum_items=int(budgets["maximum_items"]),
                    version_resolver=version_resolver,
                )
            else:
                raise SocialCollectionExecutionError(
                    f"live execution contract is not yet admitted for {connector_id}"
                )
        except (SocialCollectionExecutionError, subprocess.TimeoutExpired) as error:
            run = {
                "source_url_sha256": source_plan["source_url_sha256"],
                "connector_id": connector_id,
                "connector_revision": source_plan["connector_revision"],
                "status": "human_handoff_required",
                "error": str(error)[:1_000],
                "normalized_signal_count": 0,
                "captcha_or_auth_bypass_attempted": False,
                "raw_content_training_admitted": False,
            }
            source_signals = []
        runs.append(run)
        signals.extend(source_signals)
        # Independent public sources must not share one failure domain. A denied
        # source remains a handoff, while later sources may still be measured.

    signal_snapshot: dict[str, object] | None = None
    signal_intelligence: dict[str, object] | None = None
    if signals:
        signal_snapshot = {
            "schema": "ProofLaunchCreativeSignalSnapshotV1",
            "captured_at": captured_at,
            "purpose": "public creative and channel experiment planning",
            "retention_days": int(budgets["retention_days"]),
            "contains_personal_data": False,
            "contains_copied_creative": False,
            "signals": signals,
        }
        signal_intelligence = compile_signal_intelligence(signal_snapshot)
        _write_json(root / "creative-signal-snapshot.json", signal_snapshot)
        _write_json(root / "creative-signal-intelligence.json", signal_intelligence)

    receipt: dict[str, object] = {
        "schema": "ProofLaunchOpenSourceSocialCollectionRunV2",
        "plan_sha256": plan["plan_sha256"],
        "captured_at": captured_at,
        "status": (
            "completed"
            if runs and all(
                item["status"] in {"completed", "completed_with_item_handoffs"}
                for item in runs
            )
            else "completed_with_handoffs"
            if any(
                item["status"] in {"completed", "completed_with_item_handoffs"}
                for item in runs
            )
            else "human_handoff_required"
        ),
        "runs": runs,
        "raw_output_isolated": True,
        "pii_and_rights_filter_pending_for_raw": True,
        "derived_signal_filter_passed": signal_snapshot is not None,
        "normalized_signal_count": len(signals),
        "creative_signal_snapshot_sha256": (
            hashlib.sha256(canonical_json(signal_snapshot).encode("utf-8")).hexdigest()
            if signal_snapshot is not None
            else None
        ),
        "creative_signal_intelligence_sha256": (
            hashlib.sha256(canonical_json(signal_intelligence).encode("utf-8")).hexdigest()
            if signal_intelligence is not None
            else None
        ),
        "training_admitted": False,
        "strategy_mutation_executed": False,
        "external_publish_executed": False,
        "truth_boundary": (
            "A completed receipt proves bounded collector execution and deterministic "
            "normalization only. Raw source bytes remain isolated and unapproved for "
            "training. Signal hypotheses remain untested and require human review before "
            "strategy mutation, publishing or spend."
        ),
    }
    receipt["receipt_sha256"] = hashlib.sha256(
        canonical_json(receipt).encode("utf-8")
    ).hexdigest()
    _write_json(root / "collection-plan.json", plan)
    _write_json(root / "collection-receipt.json", receipt)
    return receipt
