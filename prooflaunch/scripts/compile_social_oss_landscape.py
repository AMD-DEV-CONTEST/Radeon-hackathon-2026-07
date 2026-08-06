#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path


CANDIDATES = (
    ("yt-dlp/yt-dlp", ["tiktok", "facebook", "instagram", "x"], "metadata_and_media_cli", "production_admitted"),
    ("mikf/gallery-dl", ["instagram", "x", "pinterest", "reddit", "bluesky", "mastodon"], "metadata_and_media_cli", "production_admitted"),
    ("DIYgod/RSSHub", ["linkedin", "tiktok", "instagram", "reddit", "x", "facebook", "pinterest", "bluesky", "mastodon"], "self_hosted_feed_router", "shadow_requires_route_probe"),
    ("apify/crawlee-python", ["linkedin", "tiktok", "instagram", "reddit", "x", "facebook", "pinterest"], "bounded_browser_crawler", "shadow_requires_site_adapter"),
    ("scrapy/scrapy", ["linkedin", "tiktok", "instagram", "reddit", "x", "facebook", "pinterest"], "bounded_http_crawler", "shadow_requires_site_adapter"),
    ("unclecode/crawl4ai", ["linkedin", "tiktok", "instagram", "reddit", "x", "facebook", "pinterest"], "browser_extraction", "shadow_public_pages_only"),
    ("firecrawl/firecrawl", ["linkedin", "tiktok", "instagram", "reddit", "x", "facebook", "pinterest"], "self_hosted_web_extraction", "shadow_public_pages_only"),
    ("instaloader/instaloader", ["instagram"], "profile_post_metadata", "shadow_public_or_operator_authorized"),
    ("davidteather/TikTok-Api", ["tiktok"], "unofficial_read_wrapper", "shadow_public_only_no_proxy_evasion"),
    ("dfreelon/pyktok", ["tiktok"], "metadata_research_helper", "shadow_requires_access_review"),
    ("praw-dev/praw", ["reddit"], "official_api_client", "shadow_requires_operator_credentials"),
    ("MarshalX/atproto", ["bluesky"], "public_protocol_client", "production_admitted"),
    ("halcy/Mastodon.py", ["mastodon"], "public_protocol_client", "production_admitted"),
    ("vladkens/twscrape", ["x"], "unofficial_account_pool_client", "operator_authorized_only"),
    ("ythx-101/x-tweet-fetcher", ["x"], "public_tweet_fetcher", "shadow_requires_security_and_reliability_review"),
    ("JustAnotherArchivist/snscrape", ["x", "reddit", "facebook"], "unofficial_scraper", "reject_if_archived_or_stale"),
    ("kevinzg/facebook-scraper", ["facebook"], "public_page_post_scraper", "shadow_requires_access_review"),
    ("linkedin-developers/linkedin-api-python-client", ["linkedin"], "official_oauth_client", "operator_authorized_only"),
    ("tomquirk/linkedin-api", ["linkedin"], "unofficial_authenticated_client", "operator_authorized_only"),
    ("joeyism/linkedin_scraper", ["linkedin"], "browser_scraper", "shadow_requires_access_review"),
    ("pinterest/api-description", ["pinterest"], "official_api_contract", "operator_authorized_only"),
    ("giocomai/cornucopia", ["linkedin", "instagram", "facebook"], "operator_export_normalizer", "shadow_operator_exports_only"),
    ("digitalmethodsinitiative/zeeschuimer", ["tiktok", "instagram", "x", "pinterest"], "operator_browser_capture_export", "shadow_operator_browser_capture_only"),
    ("digitalmethodsinitiative/4cat", ["linkedin", "tiktok", "instagram", "reddit", "x", "facebook", "pinterest", "bluesky"], "self_hosted_capture_and_analysis", "shadow_requires_bounded_datasource_probe"),
    ("medialab/minet", ["reddit", "x", "facebook"], "webmining_cli_and_library", "shadow_public_or_operator_authorized"),
    ("bluesky-social/jetstream", ["bluesky"], "official_public_json_event_stream", "shadow_requires_bounded_did_filter_adapter"),
    ("bluesky-social/indigo", ["bluesky"], "official_atproto_service_toolkit", "shadow_protocol_reference"),
    ("praw-dev/asyncpraw", ["reddit"], "official_api_async_client", "shadow_requires_operator_credentials"),
    ("tweepy/tweepy", ["x"], "official_api_client", "operator_authorized_only"),
    ("strohne/Facepager", ["reddit", "x", "facebook", "mastodon"], "operator_api_and_web_export", "shadow_operator_exports_only"),
    ("ArthurHeitmann/arctic_shift", ["reddit"], "public_research_archive", "blocked_license_and_freshness_review"),
    ("eracle/OpenOutreach", ["linkedin"], "stealth_browser_and_internal_api_automation", "rejected_stealth_auth_and_automated_outreach"),
    ("ArchiveBox/ArchiveBox", ["linkedin", "tiktok", "instagram", "reddit", "x", "facebook", "pinterest", "bluesky", "mastodon"], "self_hosted_multiformat_web_archive", "shadow_public_or_operator_supplied_urls_only"),
    ("webrecorder/browsertrix-crawler", ["linkedin", "tiktok", "instagram", "reddit", "x", "facebook", "pinterest", "bluesky", "mastodon"], "high_fidelity_browser_wacz_capture", "shadow_public_pages_only"),
    ("webrecorder/archiveweb.page", ["linkedin", "tiktok", "instagram", "reddit", "x", "facebook", "pinterest", "bluesky", "mastodon"], "operator_interactive_wacz_capture", "shadow_operator_browser_capture_only"),
    ("gildas-lormeau/SingleFile", ["linkedin", "tiktok", "instagram", "reddit", "x", "facebook", "pinterest", "bluesky", "mastodon"], "operator_single_page_capture", "shadow_operator_browser_capture_only"),
    ("DocNow/twarc", ["x"], "official_api_archive_client", "blocked_upstream_declares_no_longer_supported"),
    ("gwu-libraries/sfm-ui", ["x", "facebook"], "research_collection_orchestrator", "shadow_legacy_research_reference"),
    ("subzeroid/instagrapi", ["instagram"], "private_api_client", "operator_authorized_only_high_breakage_risk"),
    ("facebook/facebook-python-business-sdk", ["facebook", "instagram"], "official_marketing_api_sdk", "operator_authorized_only"),
    ("pinterest/pinterest-python-generated-api-client", ["pinterest"], "official_api_generated_client", "operator_authorized_only"),
    ("bluesky-social/atproto", ["bluesky"], "official_protocol_and_typescript_sdk", "shadow_protocol_reference"),
    ("mastodon/mastodon", ["mastodon"], "official_server_and_api_contract", "shadow_protocol_reference"),
    ("internetarchive/heritrix3", ["linkedin", "tiktok", "instagram", "reddit", "x", "facebook", "pinterest", "bluesky", "mastodon"], "archival_quality_web_crawler", "shadow_requires_bounded_site_profile"),
    ("microsoft/playwright", ["linkedin", "tiktok", "instagram", "reddit", "x", "facebook", "pinterest", "bluesky", "mastodon"], "browser_automation_runtime", "shadow_toolkit_requires_site_adapter"),
    ("apify/crawlee", ["linkedin", "tiktok", "instagram", "reddit", "x", "facebook", "pinterest", "bluesky", "mastodon"], "bounded_browser_and_http_crawler", "shadow_requires_site_adapter"),
    ("webrecorder/warcio", ["linkedin", "tiktok", "instagram", "reddit", "x", "facebook", "pinterest", "bluesky", "mastodon"], "warc_stream_normalizer", "shadow_normalization_only"),
    ("Watchful1/PushshiftDumps", ["reddit"], "historical_archive_download_tooling", "blocked_historical_only_freshness_review"),
)

EXPECTED_LICENSES = {
    "yt-dlp/yt-dlp": "Unlicense",
    "mikf/gallery-dl": "GPL-2.0",
    "DIYgod/RSSHub": "AGPL-3.0",
    "apify/crawlee-python": "Apache-2.0",
    "scrapy/scrapy": "BSD-3-Clause",
    "unclecode/crawl4ai": "Apache-2.0",
    "firecrawl/firecrawl": "AGPL-3.0",
    "instaloader/instaloader": "MIT",
    "davidteather/TikTok-Api": "MIT",
    "dfreelon/pyktok": "GPL-3.0",
    "praw-dev/praw": "BSD-2-Clause",
    "MarshalX/atproto": "MIT",
    "halcy/Mastodon.py": "MIT",
    "vladkens/twscrape": "MIT",
    "ythx-101/x-tweet-fetcher": "MIT",
    "JustAnotherArchivist/snscrape": "GPL-3.0",
    "kevinzg/facebook-scraper": "MIT",
    "linkedin-developers/linkedin-api-python-client": "Apache-2.0",
    "tomquirk/linkedin-api": "MIT",
    "joeyism/linkedin_scraper": "MIT",
    "pinterest/api-description": "MIT",
    "giocomai/cornucopia": "MIT",
    "digitalmethodsinitiative/zeeschuimer": "MPL-2.0",
    "digitalmethodsinitiative/4cat": "AGPL-3.0",
    "medialab/minet": "AGPL-3.0",
    "bluesky-social/jetstream": "MIT OR Apache-2.0",
    "bluesky-social/indigo": "MIT OR Apache-2.0",
    "praw-dev/asyncpraw": "BSD-2-Clause",
    "tweepy/tweepy": "MIT",
    "strohne/Facepager": "MIT",
    "ArthurHeitmann/arctic_shift": None,
    "eracle/OpenOutreach": "GPL-3.0",
    "ArchiveBox/ArchiveBox": "MIT",
    "webrecorder/browsertrix-crawler": "AGPL-3.0",
    "webrecorder/archiveweb.page": "AGPL-3.0",
    "gildas-lormeau/SingleFile": "AGPL-3.0",
    "DocNow/twarc": "MIT",
    "gwu-libraries/sfm-ui": "MIT",
    "subzeroid/instagrapi": "MIT",
    "facebook/facebook-python-business-sdk": "LicenseRef-Meta-Platform-SDK",
    "pinterest/pinterest-python-generated-api-client": None,
    "bluesky-social/atproto": "MIT OR Apache-2.0",
    "mastodon/mastodon": "AGPL-3.0",
    "internetarchive/heritrix3": "Apache-2.0",
    "microsoft/playwright": "Apache-2.0",
    "apify/crawlee": "Apache-2.0",
    "webrecorder/warcio": "Apache-2.0",
    "Watchful1/PushshiftDumps": "MIT",
}


PINNED_METADATA = {
    "ArchiveBox/ArchiveBox": ("dev", "da134b3154cf20c23516094c3ad37a403b5c13d3"),
    "webrecorder/browsertrix-crawler": ("main", "2f9a57d3ba14f8c2de6fe9231d4ff0d7036fee96"),
    "webrecorder/archiveweb.page": ("main", "5e796ef7766927c1818caef2dba301a2f3953764"),
    "gildas-lormeau/SingleFile": ("master", "06adf6391057eaf9d7a7687ae7cf67d1fbb48948"),
    "DocNow/twarc": ("main", "12104e080f48f849726b9662b32cb970c34e1689"),
    "gwu-libraries/sfm-ui": ("master", "d38886fb7e534973ea979caad2ab31b3904d651b"),
    "subzeroid/instagrapi": ("master", "632af6348b8a9804a52cc2aae45c737986abdb63"),
    "facebook/facebook-python-business-sdk": ("main", "542e10e31c40f7925f9ac03c000922a2fd0a2365"),
    "pinterest/pinterest-python-generated-api-client": ("main", "f8ee0afb232532f259b7bf8e4f7f5b1b52fe305a"),
    "bluesky-social/atproto": ("main", "5043c7a1c922a79baba972f27d1abb75675e9705"),
    "mastodon/mastodon": ("main", "b625f21ceab87556c990344d586a231b6c4559e3"),
    "internetarchive/heritrix3": ("master", "96b16d0e68076e028e4e6b3bdd79bc647d32892e"),
    "microsoft/playwright": ("main", "b637a5a4098789da917a4605d1966bd3f9528d63"),
    "apify/crawlee": ("master", "2de484111dedf33fad7a55d4eba479c12237d6e8"),
    "webrecorder/warcio": ("master", "2a797aa8c6d67e70966ce9d1a690208ab250fbe7"),
    "Watchful1/PushshiftDumps": ("master", "1cfbce35b74b7e783ee2a9ed43cc1512f4fccef7"),
}


LICENSE_PATHS = {
    "bluesky-social/jetstream": ("LICENSE-DUAL", "LICENSE-MIT", "LICENSE-APACHE"),
    "bluesky-social/indigo": ("LICENSE-DUAL", "LICENSE-MIT", "LICENSE-APACHE"),
    "strohne/Facepager": ("README.md",),
    "bluesky-social/atproto": ("LICENSE-DUAL", "LICENSE-MIT", "LICENSE-APACHE"),
}


AUDIT_OVERRIDES = {
    "tomquirk/linkedin-api": {
        "admission_decision": "rejected_upstream_removed_or_private",
        "audit_note": "The formerly common unofficial client no longer resolves as a public upstream; it cannot be pinned or admitted.",
    },
    "ythx-101/x-tweet-fetcher": {
        "admission_decision": "partial_shadow_single_public_object_only",
        "audit_note": "Static audit admits only explicit public tweet/profile-object routes for shadow work; Nitter timelines and anti-fingerprint browser fallback are rejected.",
    },
    "kevinzg/facebook-scraper": {
        "admission_decision": "shadow_probe_no_public_items",
        "audit_note": "A bounded no-cookie, no-login Xero Page probe returned no public post metadata; no retry loop was admitted.",
    },
    "eracle/OpenOutreach": {
        "admission_decision": "rejected_stealth_auth_and_automated_outreach",
        "audit_note": "The project advertises stealth browser behavior, LinkedIn internal APIs, credentialed sessions and automatic outreach, all outside this read-only collection boundary.",
    },
    "DocNow/twarc": {
        "admission_decision": "blocked_upstream_declares_no_longer_supported",
        "audit_note": "The upstream README says twarc is no longer actively supported after X API quota changes; retain only as an official-API archive reference.",
    },
    "subzeroid/instagrapi": {
        "admission_decision": "operator_authorized_only_high_breakage_risk",
        "audit_note": "This uses Instagram private interfaces. It is not admitted for anonymous public collection and may run only on an operator-owned account after a separate policy and breakage review.",
    },
    "ArchiveBox/ArchiveBox": {
        "audit_note": "Admit only URLs already public or explicitly supplied by an authorized operator. Bot-blocking or CAPTCHA-unblocking features remain disabled.",
    },
    "webrecorder/browsertrix-crawler": {
        "audit_note": "Useful for WARC/WACZ evidence capture of ordinary public pages; no auth-wall or CAPTCHA interaction profile is admitted.",
    },
    "webrecorder/archiveweb.page": {
        "audit_note": "Operator-interactive capture can preserve a page the operator is already permitted to view; captured private data is not admitted into the public signal corpus.",
    },
    "gildas-lormeau/SingleFile": {
        "audit_note": "Operator-side page preservation only. It does not discover accounts, prove freshness, or independently expose engagement counters.",
    },
    "gwu-libraries/sfm-ui": {
        "audit_note": "Legacy research orchestration is useful as an architecture reference, but its historical platform APIs do not establish current collection access.",
    },
    "Watchful1/PushshiftDumps": {
        "audit_note": "Historical Reddit archive tooling cannot satisfy the 90/180-day live-signal gate by itself and remains blocked pending dataset-specific rights and freshness review.",
    },
}


def _candidate_profile(capability: str, decision: str) -> dict[str, object]:
    """Describe what an OSS row can contribute without implying live access."""
    combined = f"{capability} {decision}".casefold()
    if "rejected" in combined:
        access_mode = "rejected"
    elif "operator_browser" in combined or "operator_export" in combined or "operator_single" in combined:
        access_mode = "operator_supplied_capture"
    elif "operator_authorized" in combined or "official_api" in combined or "oauth" in combined or "credential" in combined:
        access_mode = "operator_credentials_required"
    elif "historical" in combined or "archive" in combined or "warc" in combined:
        access_mode = "public_or_operator_supplied_archive_input"
    else:
        access_mode = "ordinary_public_pages_or_protocol"

    surfaces = {"content", "source_locator", "capture_timestamp"}
    if any(token in combined for token in ("media", "browser", "archive", "capture", "gallery")):
        surfaces.update({"image_or_video_reference", "rendered_evidence"})
    if any(token in combined for token in ("api", "protocol", "feed", "metadata", "client", "stream")):
        surfaces.update({"author_or_actor", "published_timestamp", "public_engagement_counters_when_exposed"})
    if any(token in combined for token in ("comment", "reddit", "mastodon", "bluesky", "4cat")):
        surfaces.add("public_replies_when_exposed")

    if "historical" in combined or "legacy" in combined or "no_longer_supported" in combined:
        freshness_mode = "historical_or_legacy_only"
    elif "operator" in access_mode:
        freshness_mode = "captured_at_operator_export_time"
    elif any(token in combined for token in ("api", "protocol", "feed", "stream")):
        freshness_mode = "live_endpoint_subject_to_source_timestamp"
    else:
        freshness_mode = "live_page_capture_subject_to_parse_success"

    if "normalization" in combined or "warc_stream" in combined:
        integration_role = "normalization_layer"
    elif "archive" in combined or "capture" in combined or "single_page" in combined:
        integration_role = "evidence_capture_layer"
    elif "toolkit" in combined or "runtime" in combined or "crawler" in combined:
        integration_role = "collector_runtime_requires_adapter"
    else:
        integration_role = "source_adapter_candidate"
    return {
        "access_mode": access_mode,
        "signal_surfaces": sorted(surfaces),
        "freshness_mode": freshness_mode,
        "integration_role": integration_role,
        "login_or_api_requirement": access_mode == "operator_credentials_required",
        "runtime_proven": decision == "production_admitted",
    }


def _get(url: str) -> dict:
    headers = {"Accept": "application/vnd.github+json", "User-Agent": "ProofLaunch-OSS-Audit/1.0"}
    token = os.environ.get("GITHUB_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(request, timeout=20) as response:
        return json.load(response)


def _sha(value: object) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _git_head(repository: str) -> tuple[str, str]:
    completed = subprocess.run(
        ["git", "ls-remote", "--symref", f"https://github.com/{repository}.git", "HEAD"],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
        shell=False,
    )
    if completed.returncode != 0:
        raise RuntimeError(completed.stderr.strip() or "git ls-remote failed")
    branch_match = re.search(r"ref: refs/heads/([^\s]+)\s+HEAD", completed.stdout)
    sha_match = re.search(r"^([0-9a-f]{40})\s+HEAD$", completed.stdout, re.MULTILINE)
    if not branch_match or not sha_match:
        raise RuntimeError("git ls-remote did not resolve a default branch and HEAD")
    return branch_match.group(1), sha_match.group(1)


def _public_bytes(url: str, *, maximum_bytes: int = 2_000_000) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": "ProofLaunch-OSS-Audit/1.0"})
    with urllib.request.urlopen(request, timeout=20) as response:
        body = response.read(maximum_bytes + 1)
    if len(body) > maximum_bytes:
        raise RuntimeError("public response exceeded audit byte limit")
    return body


def _fallback_metadata(repository: str) -> dict:
    branch, revision = _git_head(repository)
    license_body = None
    license_path = None
    for candidate in LICENSE_PATHS.get(
        repository, ("LICENSE", "LICENSE.md", "LICENSE.txt", "COPYING")
    ):
        try:
            license_body = _public_bytes(
                f"https://raw.githubusercontent.com/{repository}/{revision}/{candidate}",
                maximum_bytes=500_000,
            )
            license_path = candidate
            break
        except (urllib.error.URLError, urllib.error.HTTPError, RuntimeError, TimeoutError):
            continue
    page = _public_bytes(f"https://github.com/{repository}")
    page_text = page.decode("utf-8", errors="replace").casefold()
    return {
        "resolved": True,
        "revision": revision,
        "default_branch": branch,
        "license_spdx": EXPECTED_LICENSES.get(repository),
        "license_file_path": license_path,
        "license_file_sha256": hashlib.sha256(license_body).hexdigest() if license_body else None,
        "license_resolution": "expected_spdx_bound_to_public_license_file" if license_body else "expected_spdx_unverified_no_license_file",
        "archived": "this repository was archived by the owner" in page_text,
        "disabled": False,
        "stars": None,
        "open_issues": None,
        "pushed_at": None,
        "metadata_resolution": "git_ls_remote_and_public_repository_files",
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument(
        "--reuse-landscape",
        type=Path,
        help="Reuse already digest-sealed rows before resolving newly added repositories.",
    )
    args = parser.parse_args()
    reused_by_repository: dict[str, dict] = {}
    if args.reuse_landscape is not None:
        reused_payload = json.loads(args.reuse_landscape.read_text(encoding="utf-8"))
        unsigned_reused = dict(reused_payload)
        reused_digest = unsigned_reused.pop("content_sha256", None)
        if reused_digest != _sha(unsigned_reused):
            raise ValueError("reuse landscape digest is invalid")
        reused_by_repository = {
            str(item["repository"]): dict(item)
            for item in reused_payload.get("candidates", [])
            if isinstance(item, dict) and isinstance(item.get("repository"), str)
        }
    rows = []
    for repository, platforms, capability, proposed_status in CANDIDATES:
        row = {
            "repository": f"https://github.com/{repository}",
            "platforms": platforms,
            "capability": capability,
            "proposed_status": proposed_status,
            **_candidate_profile(capability, proposed_status),
        }
        reused = reused_by_repository.get(row["repository"])
        if reused is not None:
            preserved = dict(reused)
            preserved.update(row)
            row = preserved
            row.update(AUDIT_OVERRIDES.get(repository, {}))
            row["runtime_proven"] = row.get("admission_decision") == "production_admitted"
            rows.append(row)
            continue
        if repository in PINNED_METADATA:
            branch, revision = PINNED_METADATA[repository]
            expected_license = EXPECTED_LICENSES.get(repository)
            row.update({
                "resolved": True,
                "revision": revision,
                "default_branch": branch,
                "license_spdx": expected_license,
                "license_resolution": "git_ls_remote_and_primary_repository_review",
                "license_source_url": f"https://github.com/{repository}/blob/{revision}/LICENSE",
                "archived": False,
                "disabled": False,
                "stars": None,
                "open_issues": None,
                "pushed_at": None,
                "metadata_resolution": "git_ls_remote_and_primary_repository_review",
                "admission_decision": (
                    proposed_status if expected_license is not None else "blocked_license_review"
                ),
            })
            row.update(AUDIT_OVERRIDES.get(repository, {}))
            row["runtime_proven"] = row.get("admission_decision") == "production_admitted"
            rows.append(row)
            continue
        try:
            meta = _get(f"https://api.github.com/repos/{repository}")
            branch = str(meta["default_branch"])
            commit = _get(f"https://api.github.com/repos/{repository}/commits/{branch}")
            row.update({
                "resolved": True,
                "revision": commit["sha"],
                "default_branch": branch,
                "license_spdx": (meta.get("license") or {}).get("spdx_id"),
                "archived": bool(meta.get("archived")),
                "disabled": bool(meta.get("disabled")),
                "stars": int(meta.get("stargazers_count", 0)),
                "open_issues": int(meta.get("open_issues_count", 0)),
                "pushed_at": meta.get("pushed_at"),
            })
            if row["license_spdx"] in {None, "NOASSERTION", "OTHER"}:
                expected = EXPECTED_LICENSES.get(repository)
                license_body = None
                license_path = None
                for candidate in LICENSE_PATHS.get(
                    repository, ("LICENSE", "LICENSE.md", "LICENSE.txt", "COPYING")
                ):
                    try:
                        license_body = _public_bytes(
                            f"https://raw.githubusercontent.com/{repository}/{row['revision']}/{candidate}",
                            maximum_bytes=500_000,
                        )
                        license_path = candidate
                        break
                    except (urllib.error.URLError, urllib.error.HTTPError, RuntimeError, TimeoutError):
                        continue
                if expected is not None and license_body is not None:
                    row.update({
                        "license_spdx": expected,
                        "license_file_path": license_path,
                        "license_file_sha256": hashlib.sha256(license_body).hexdigest(),
                        "license_resolution": "expected_spdx_bound_to_public_license_file",
                    })
            if row["archived"] or row["disabled"]:
                row["admission_decision"] = "rejected_archived_or_disabled"
            elif row["license_spdx"] in {None, "NOASSERTION", "OTHER"}:
                row["admission_decision"] = "blocked_license_review"
            else:
                row["admission_decision"] = proposed_status
        except (urllib.error.URLError, urllib.error.HTTPError, KeyError, ValueError, TimeoutError) as api_error:
            try:
                row.update(_fallback_metadata(repository))
                if row["archived"] or row["disabled"]:
                    row["admission_decision"] = "rejected_archived_or_disabled"
                elif row.get("license_resolution") != "expected_spdx_bound_to_public_license_file":
                    row["admission_decision"] = "blocked_license_review"
                else:
                    row["admission_decision"] = proposed_status
                row["github_api_fallback_reason"] = f"{type(api_error).__name__}: {api_error}"[:500]
            except (urllib.error.URLError, urllib.error.HTTPError, RuntimeError, TimeoutError, subprocess.SubprocessError) as error:
                row.update({
                    "resolved": False,
                    "admission_decision": "blocked_metadata_resolution",
                    "error": f"{type(error).__name__}: {error}"[:500],
                })
        row.update(AUDIT_OVERRIDES.get(repository, {}))
        row["runtime_proven"] = row.get("admission_decision") == "production_admitted"
        rows.append(row)
        time.sleep(0.12)
    payload = {
        "schema": "ProofLaunchSocialOSSAdapterLandscapeV1",
        "candidate_count": len(rows),
        "resolved_count": sum(bool(row["resolved"]) for row in rows),
        "production_admitted_count": sum(row["admission_decision"] == "production_admitted" for row in rows),
        "platform_candidate_counts": {
            platform: sum(platform in row["platforms"] for row in rows)
            for platform in ("linkedin", "tiktok", "instagram", "reddit", "x", "facebook", "pinterest", "bluesky", "mastodon")
        },
        "access_mode_counts": {
            mode: sum(row.get("access_mode") == mode for row in rows)
            for mode in sorted({str(row.get("access_mode")) for row in rows})
        },
        "integration_role_counts": {
            role: sum(row.get("integration_role") == role for row in rows)
            for role in sorted({str(row.get("integration_role")) for row in rows})
        },
        "runtime_proven_count": sum(bool(row.get("runtime_proven")) for row in rows),
        "candidates": rows,
        "selection_gate": [
            "exact_revision_and_license_resolved",
            "ordinary_public_or_operator_authorized_access_only",
            "no_captcha_paywall_auth_or_rate_limit_evasion",
            "bounded_read_only_execution",
            "freshness_and_public_counter_schema_probe",
            "failure_is_auditable_handoff",
            "shadow_comparison_before_production_admission",
        ],
        "truth_boundary": "Repository discovery and metadata resolution do not prove that an adapter currently works against a platform. Only production_admitted adapters have an implemented, tested execution contract; all others remain shadow or blocked.",
    }
    payload["content_sha256"] = _sha(payload)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({key: payload[key] for key in ("candidate_count", "resolved_count", "production_admitted_count", "platform_candidate_counts", "content_sha256")}, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
