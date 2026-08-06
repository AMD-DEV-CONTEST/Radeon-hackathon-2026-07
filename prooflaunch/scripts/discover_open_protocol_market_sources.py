#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from urllib.parse import quote, urlparse


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "src"
if str(SOURCE) not in sys.path:
    sys.path.insert(0, str(SOURCE))

from prooflaunch_remix.files import atomic_write_text
from prooflaunch_remix.ledger import canonical_json
from prooflaunch_remix.social_collection_runner import BoundedPublicHttpClient, SocialCollectionExecutionError


def _host(url: str) -> str:
    return (urlparse(url).hostname or "").casefold().removeprefix("www.")


def _identity_match(*, homepage_host: str, handle: str, description: str) -> str | None:
    normalized_handle = handle.casefold().lstrip("@").rstrip(".")
    normalized_description = description.casefold()
    if normalized_handle == homepage_host or normalized_handle.endswith("." + homepage_host):
        return "domain_handle_matches_homepage"
    if homepage_host and homepage_host in normalized_description:
        return "profile_description_names_homepage_domain"
    return None


def _discover(seed: dict) -> dict:
    client = BoundedPublicHttpClient()
    homepage_host = _host(str(seed["homepage_url"]))
    result = {
        "organization_id": seed["organization_id"],
        "name": seed["name"],
        "business_model": seed["business_model"],
        "market": seed["market"],
        "vertical": seed["vertical"],
        "company_scale": seed["company_scale"],
        "lifecycle": seed["lifecycle"],
        "discovered_sources": {},
        "platform_results": {},
    }
    bsky_url = (
        "https://public.api.bsky.app/xrpc/app.bsky.actor.searchActors"
        f"?q={quote(str(seed['name']))}&limit=10"
    )
    try:
        response = client.get(bsky_url, timeout_seconds=10, maximum_bytes=1_000_000)
        actors = json.loads(response.body).get("actors", [])
        matches = []
        for actor in actors if isinstance(actors, list) else []:
            if not isinstance(actor, dict):
                continue
            handle = str(actor.get("handle") or "")
            basis = _identity_match(
                homepage_host=homepage_host,
                handle=handle,
                description=str(actor.get("description") or ""),
            )
            if basis and handle:
                matches.append({
                    "url": f"https://bsky.app/profile/{handle}",
                    "identity_basis": basis,
                })
        result["platform_results"]["bluesky"] = {
            "status": "completed",
            "candidate_count": len(matches),
        }
        if matches:
            result["discovered_sources"]["bluesky"] = matches
    except (SocialCollectionExecutionError, json.JSONDecodeError) as error:
        result["platform_results"]["bluesky"] = {
            "status": "human_handoff_required", "error": str(error)[:500]
        }

    mastodon_url = (
        "https://mastodon.social/api/v2/search"
        f"?q={quote(str(seed['name']))}&type=accounts&resolve=true&limit=10"
    )
    try:
        response = client.get(mastodon_url, timeout_seconds=10, maximum_bytes=1_000_000)
        accounts = json.loads(response.body).get("accounts", [])
        matches = []
        for account in accounts if isinstance(accounts, list) else []:
            if not isinstance(account, dict):
                continue
            account_url = str(account.get("url") or "")
            acct = str(account.get("acct") or "")
            basis = _identity_match(
                homepage_host=homepage_host,
                handle=acct,
                description=str(account.get("note") or ""),
            )
            if basis and account_url.startswith("https://"):
                matches.append({"url": account_url, "identity_basis": basis})
        result["platform_results"]["mastodon"] = {
            "status": "completed",
            "candidate_count": len(matches),
        }
        if matches:
            result["discovered_sources"]["mastodon"] = matches
    except (SocialCollectionExecutionError, json.JSONDecodeError) as error:
        result["platform_results"]["mastodon"] = {
            "status": "human_handoff_required", "error": str(error)[:500]
        }
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--seeds", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--maximum-workers", type=int, default=8)
    args = parser.parse_args()
    seeds = json.loads(args.seeds.read_text(encoding="utf-8")).get("organizations", [])
    rows = []
    with ThreadPoolExecutor(max_workers=args.maximum_workers) as executor:
        futures = [executor.submit(_discover, seed) for seed in seeds]
        for future in as_completed(futures):
            rows.append(future.result())
    rows.sort(key=lambda row: row["organization_id"])
    payload = {
        "schema": "ProofLaunchOpenProtocolSourceDiscoveryV1",
        "organization_seed_count": len(rows),
        "bluesky_candidate_count": sum(len(row["discovered_sources"].get("bluesky", [])) for row in rows),
        "mastodon_candidate_count": sum(len(row["discovered_sources"].get("mastodon", [])) for row in rows),
        "bluesky_completed_query_count": sum(row["platform_results"].get("bluesky", {}).get("status") == "completed" for row in rows),
        "mastodon_completed_query_count": sum(row["platform_results"].get("mastodon", {}).get("status") == "completed" for row in rows),
        "organizations": rows,
        "automatic_learning_memory_write_count": 0,
        "truth_boundary": "Search results are admitted only when a public profile binds itself to the organization homepage domain. Name similarity alone is rejected. Discovery does not prove recent posts, effectiveness or training rights.",
    }
    payload["content_sha256"] = hashlib.sha256(canonical_json(payload).encode()).hexdigest()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(args.output, json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    print(json.dumps({key: payload[key] for key in ("organization_seed_count", "bluesky_candidate_count", "mastodon_candidate_count", "bluesky_completed_query_count", "mastodon_completed_query_count", "content_sha256")}, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
