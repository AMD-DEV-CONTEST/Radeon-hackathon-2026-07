#!/usr/bin/env python3
"""Fetch a secret-safe, attributable Artificial Analysis model snapshot."""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable


BASE_URL = "https://artificialanalysis.ai/api/v2"
DOCS_URL = "https://artificialanalysis.ai/data-api/docs"
SOURCE_URL = "https://artificialanalysis.ai"
SCHEMA_VERSION = "signalforge/artificial-analysis-model-snapshot/v1"


def fetch_page(
    api_key: str,
    endpoint: str,
    page: int,
    prompt_type: str,
    opener: Callable[..., object] = urllib.request.urlopen,
) -> tuple[dict, dict[str, str]]:
    query = urllib.parse.urlencode({"page": page, "prompt_type": prompt_type})
    request = urllib.request.Request(
        f"{BASE_URL}{endpoint}?{query}",
        headers={"Accept": "application/json", "x-api-key": api_key},
    )
    try:
        with opener(request, timeout=30) as response:
            payload = json.load(response)
            headers = {
                "tier": response.headers.get("X-AA-Tier", ""),
                "limit": response.headers.get("X-RateLimit-Limit", ""),
                "remaining": response.headers.get("X-RateLimit-Remaining", ""),
                "reset": response.headers.get("X-RateLimit-Reset", ""),
            }
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")[:500]
        raise RuntimeError(f"Artificial Analysis returned HTTP {error.code}: {detail}") from error
    except urllib.error.URLError as error:
        raise RuntimeError(f"Artificial Analysis request failed: {error.reason}") from error
    if not isinstance(payload, dict) or not isinstance(payload.get("data"), list):
        raise RuntimeError("Artificial Analysis returned an unexpected response envelope")
    return payload, headers


def fetch_all(
    api_key: str,
    endpoint: str,
    prompt_type: str,
    fetcher: Callable[[str, str, int, str], tuple[dict, dict[str, str]]] = fetch_page,
) -> tuple[list[dict], dict, dict[str, str]]:
    models: list[dict] = []
    page = 1
    metadata: dict = {}
    rate_limit: dict[str, str] = {}
    while True:
        payload, rate_limit = fetcher(api_key, endpoint, page, prompt_type)
        models.extend(payload["data"])
        metadata = {
            "tier": payload.get("tier"),
            "intelligence_index_version": payload.get("intelligence_index_version"),
        }
        pagination = payload.get("pagination") or {}
        if not pagination.get("has_more"):
            return models, metadata, rate_limit
        page += 1
        if page > 100:
            raise RuntimeError("Artificial Analysis pagination exceeded the safety limit")


def build_snapshot(
    models: list[dict],
    metadata: dict,
    rate_limit: dict[str, str],
    endpoint: str,
    prompt_type: str,
    requested_slugs: list[str],
) -> dict:
    wanted = set(requested_slugs)
    selected = [model for model in models if not wanted or model.get("slug") in wanted]
    found = {model.get("slug") for model in selected}
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source": {
            "name": "Artificial Analysis",
            "url": SOURCE_URL,
            "documentation_url": DOCS_URL,
            "attribution_required": True,
        },
        "request": {
            "base_url": BASE_URL,
            "endpoint": endpoint,
            "prompt_type": prompt_type,
            "requested_slugs": sorted(wanted),
            "missing_slugs": sorted(wanted - found),
        },
        "response": {
            **metadata,
            "model_count": len(selected),
            "rate_limit": rate_limit,
        },
        "models": sorted(selected, key=lambda model: str(model.get("slug", ""))),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--tier", choices=("free", "pro"), default="pro")
    parser.add_argument(
        "--prompt-type",
        choices=("medium", "long", "100k", "vision_single_image", "medium_coding", "medium_parallel"),
        default="long",
    )
    parser.add_argument("--slug", action="append", default=[])
    args = parser.parse_args()

    api_key = os.environ.get("ARTIFICIAL_ANALYSIS_API_KEY", "").strip()
    if not api_key:
        raise SystemExit("ARTIFICIAL_ANALYSIS_API_KEY is required and must remain outside the repository")
    endpoint = "/language/models/free" if args.tier == "free" else "/language/models"
    try:
        models, metadata, rate_limit = fetch_all(api_key, endpoint, args.prompt_type)
        snapshot = build_snapshot(models, metadata, rate_limit, endpoint, args.prompt_type, args.slug)
    except RuntimeError as error:
        print(error, file=sys.stderr)
        raise SystemExit(1) from error
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(snapshot, indent=2, sort_keys=True) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
