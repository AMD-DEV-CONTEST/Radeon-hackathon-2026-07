#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import signal
from datetime import datetime, timedelta, timezone
from importlib.metadata import version
from pathlib import Path
from urllib.parse import urlparse

from facebook_scraper import get_posts

from prooflaunch_remix.files import atomic_write_text
from prooflaunch_remix.ledger import canonical_json


class ProbeTimeout(RuntimeError):
    pass


def _alarm(_signum, _frame):
    raise ProbeTimeout("shadow adapter exceeded its per-source time budget")


def _as_utc(value):
    if not isinstance(value, datetime):
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", required=True)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--maximum-items", type=int, default=20)
    parser.add_argument("--maximum-pages", type=int, default=3)
    parser.add_argument("--timeout-seconds", type=int, default=30)
    args = parser.parse_args()
    parsed = urlparse(args.url)
    if parsed.scheme != "https" or not parsed.hostname or "facebook.com" not in parsed.hostname:
        raise SystemExit("an HTTPS Facebook Page URL is required")
    account = parsed.path.strip("/").split("/")[0]
    if not account:
        raise SystemExit("a Facebook Page URL is required")
    now = datetime.now(timezone.utc)
    rows = []
    error = None
    status = "human_handoff_required"
    previous_handler = signal.signal(signal.SIGALRM, _alarm)
    signal.alarm(args.timeout_seconds)
    try:
        for post in get_posts(
            account,
            pages=args.maximum_pages,
            timeout=min(args.timeout_seconds, 20),
            credentials=None,
            cookies=None,
            extra_info=False,
            options={
                "allow_extra_requests": False,
                "comments": False,
                "reactors": False,
                "posts_per_page": 4,
            },
        ):
            published = _as_utc(post.get("time"))
            rows.append({
                "published_at": published.isoformat().replace("+00:00", "Z") if published else None,
                "likes": max(0, int(post.get("likes") or 0)),
                "comments": max(0, int(post.get("comments") or 0)),
                "shares": max(0, int(post.get("shares") or 0)),
                "has_video": bool(post.get("video_id") or post.get("video")),
                "has_image": bool(post.get("image") or post.get("images")),
            })
            if len(rows) >= args.maximum_items:
                break
        status = "shadow_probe_completed" if rows else "human_handoff_required"
        if not rows:
            error = "facebook-scraper returned no public post metadata"
    except Exception as caught:
        error = f"{type(caught).__name__}: {caught}"[:500]
    finally:
        signal.alarm(0)
        signal.signal(signal.SIGALRM, previous_handler)
    dated = [datetime.fromisoformat(row["published_at"].replace("Z", "+00:00")) for row in rows if row["published_at"]]
    payload = {
        "schema": "ProofLaunchFacebookScraperShadowProbeV1",
        "connector": "facebook-scraper",
        "connector_version": version("facebook-scraper"),
        "source_url_sha256": hashlib.sha256(args.url.encode()).hexdigest(),
        "status": status,
        "error": error,
        "item_count": len(rows),
        "timestamped_item_count": len(dated),
        "recent_item_count_90d": sum(value >= now - timedelta(days=90) for value in dated),
        "recent_item_count_180d": sum(value >= now - timedelta(days=180) for value in dated),
        "oldest_publication_at": min(dated).isoformat().replace("+00:00", "Z") if dated else None,
        "newest_publication_at": max(dated).isoformat().replace("+00:00", "Z") if dated else None,
        "raw_expression_retained": False,
        "public_item_identifiers_retained": False,
        "login_attempted": False,
        "cookies_loaded": False,
        "extra_requests_allowed": False,
        "proxy_or_access_evasion_attempted": False,
        "production_admitted": False,
        "truth_boundary": "A successful shadow probe proves bounded unauthenticated public Page metadata access for one Page only. It does not admit the adapter to production or prove coverage, effectiveness, training rights or future reliability.",
    }
    payload["content_sha256"] = hashlib.sha256(canonical_json(payload).encode()).hexdigest()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(args.output, json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    print(json.dumps({key: payload[key] for key in ("status", "item_count", "recent_item_count_90d", "recent_item_count_180d", "content_sha256")}, sort_keys=True))


if __name__ == "__main__":
    main()
