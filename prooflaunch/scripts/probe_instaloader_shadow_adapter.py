#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import signal
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlparse

import instaloader

from prooflaunch_remix.files import atomic_write_text
from prooflaunch_remix.ledger import canonical_json


class ProbeTimeout(RuntimeError):
    pass


def _alarm(_signum, _frame):
    raise ProbeTimeout("shadow adapter exceeded its per-source time budget")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", required=True)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--maximum-items", type=int, default=20)
    parser.add_argument("--timeout-seconds", type=int, default=30)
    args = parser.parse_args()
    parsed = urlparse(args.url)
    if parsed.scheme != "https" or not parsed.hostname or "instagram.com" not in parsed.hostname:
        raise SystemExit("an HTTPS Instagram profile URL is required")
    username = parsed.path.strip("/").split("/")[0]
    if not username or username in {"p", "reel", "stories"}:
        raise SystemExit("an Instagram profile URL is required")
    source_sha = hashlib.sha256(args.url.encode()).hexdigest()
    loader = instaloader.Instaloader(
        download_pictures=False,
        download_videos=False,
        download_video_thumbnails=False,
        download_geotags=False,
        download_comments=False,
        save_metadata=False,
        compress_json=False,
        post_metadata_txt_pattern="",
        quiet=True,
    )
    now = datetime.now(timezone.utc)
    rows = []
    status = "human_handoff_required"
    error = None
    previous_handler = signal.signal(signal.SIGALRM, _alarm)
    signal.alarm(args.timeout_seconds)
    try:
        profile = instaloader.Profile.from_username(loader.context, username)
        for post in profile.get_posts():
            published = post.date_utc.replace(tzinfo=timezone.utc)
            rows.append({
                "published_at": published.isoformat().replace("+00:00", "Z"),
                "likes": max(0, int(post.likes)),
                "comments": max(0, int(post.comments)),
                "is_video": bool(post.is_video),
                "video_view_count": (
                    max(0, int(post.video_view_count))
                    if post.is_video and post.video_view_count is not None
                    else None
                ),
            })
            if len(rows) >= args.maximum_items:
                break
        status = "shadow_probe_completed" if rows else "human_handoff_required"
        if not rows:
            error = "Instaloader returned no public post metadata"
    except Exception as caught:
        error = f"{type(caught).__name__}: {caught}"[:500]
    finally:
        signal.alarm(0)
        signal.signal(signal.SIGALRM, previous_handler)
        loader.close()
    recent_90 = sum(datetime.fromisoformat(row["published_at"].replace("Z", "+00:00")) >= now - timedelta(days=90) for row in rows)
    recent_180 = sum(datetime.fromisoformat(row["published_at"].replace("Z", "+00:00")) >= now - timedelta(days=180) for row in rows)
    payload = {
        "schema": "ProofLaunchInstaloaderShadowProbeV1",
        "connector": "instaloader",
        "connector_version": instaloader.__version__,
        "source_url_sha256": source_sha,
        "status": status,
        "error": error,
        "item_count": len(rows),
        "recent_item_count_90d": recent_90,
        "recent_item_count_180d": recent_180,
        "oldest_publication_at": rows[-1]["published_at"] if rows else None,
        "newest_publication_at": rows[0]["published_at"] if rows else None,
        "view_measured_item_count": sum(row["video_view_count"] is not None for row in rows),
        "raw_expression_retained": False,
        "public_item_identifiers_retained": False,
        "login_attempted": False,
        "proxy_or_access_evasion_attempted": False,
        "production_admitted": False,
        "truth_boundary": "A successful shadow probe proves bounded public metadata access for one profile only. It does not admit Instaloader to production or establish market coverage, effectiveness, training rights or future reliability.",
    }
    payload["content_sha256"] = hashlib.sha256(canonical_json(payload).encode()).hexdigest()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(args.output, json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    print(json.dumps({key: payload[key] for key in ("status", "item_count", "recent_item_count_90d", "recent_item_count_180d", "content_sha256")}, sort_keys=True))


if __name__ == "__main__":
    main()
