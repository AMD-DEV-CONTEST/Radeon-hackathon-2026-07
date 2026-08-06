#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import time
import urllib.parse
import urllib.request
from dataclasses import asdict
from pathlib import Path
from typing import Any

from prooflaunch_remix.files import atomic_write_text
from prooflaunch_remix.v10_source_bundle import SourceBundleRecord, validate_source_bundle
from prooflaunch_remix.v10_supply_chain import stable_sha256


ROOT = Path(__file__).resolve().parents[1]
SEED = ROOT / "data/v10_open_materials/sources.jsonl"
DATA = ROOT / "data/v10_source_bundle"
EVIDENCE = ROOT / "evidence/v10/source-bundle-2000-audit.json"
OBSERVED_AT = "2026-07-31"
USER_AGENT = "ProofLaunchSourceBundle/2.0 (rights metadata audit)"


def fetch_json(url: str, *, attempts: int = 5) -> dict[str, Any]:
    last_error: Exception | None = None
    for attempt in range(attempts):
        try:
            request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(request, timeout=60) as response:
                value = json.load(response)
            if not isinstance(value, dict):
                raise TypeError("JSON response is not an object")
            return value
        except Exception as error:  # network boundary is recorded by final audit
            last_error = error
            if attempt + 1 < attempts:
                time.sleep(min(2 ** attempt, 8))
    raise RuntimeError(f"source request failed after {attempts} attempts: {url}") from last_error


def seed_records() -> list[SourceBundleRecord]:
    providers = {
        "hardware": "rocm",
        "software": "transformers",
        "brand": "cncf-artwork",
        "product_visual": "wikimedia-commons",
        "scene_visual": "wikimedia-commons",
        "video": "wikimedia-commons",
        "font": "google-fonts",
        "audio": "wikimedia-commons",
    }
    rows = []
    for line in SEED.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        source = json.loads(line)
        rows.append(
            SourceBundleRecord(
                source_id=f"seed-{source['source_id']}",
                provider=providers[source["kind"]],
                upstream_asset_id=source["asset_url"],
                kind=source["kind"],
                title=source["title"],
                asset_url=source["asset_url"],
                evidence_url=source["evidence_url"],
                license_id=source["license_id"],
                license_url=source["license_url"],
                revision=source["revision"],
                digest_algorithm=source["upstream_digest_algorithm"],
                upstream_digest=source["upstream_digest"],
                media_type=source["media_type"],
                attribution=source["attribution"],
                training_allowed=bool(source["training_allowed"]),
                trademark_hold=bool(source["trademark_hold"]),
                source_observed_at=OBSERVED_AT,
            )
        )
    if len(rows) != 24:
        raise RuntimeError("run build_v10_open_materials.py before source collection")
    return rows


def artic_records(target: int = 800) -> list[SourceBundleRecord]:
    rows: list[SourceBundleRecord] = []
    seen: set[str] = set()
    page = 1
    fields = ",".join(
        (
            "id", "title", "image_id", "is_public_domain", "artist_display",
            "date_display", "updated_at", "api_link",
        )
    )
    while len(rows) < target:
        params = urllib.parse.urlencode({"limit": 100, "page": page, "fields": fields})
        payload = fetch_json(f"https://api.artic.edu/api/v1/artworks?{params}")
        iiif = str(payload.get("config", {}).get("iiif_url") or "https://www.artic.edu/iiif/2")
        for item in payload.get("data", []):
            image_id = str(item.get("image_id") or "").strip()
            if not item.get("is_public_domain") or not image_id:
                continue
            object_id = str(item["id"])
            if object_id in seen:
                continue
            seen.add(object_id)
            rows.append(
                SourceBundleRecord(
                    source_id=f"artic-{object_id}",
                    provider="art-institute-chicago",
                    upstream_asset_id=object_id,
                    kind="museum_visual",
                    title=str(item.get("title") or f"Art Institute object {object_id}"),
                    asset_url=f"{iiif}/{image_id}/full/843,/0/default.jpg",
                    evidence_url=f"https://www.artic.edu/artworks/{object_id}",
                    license_id="CC0-1.0",
                    license_url="https://www.artic.edu/open-access/open-access-images",
                    revision=str(item.get("updated_at") or f"api-v1-object-{object_id}"),
                    digest_algorithm="sha256-canonical-api-record",
                    upstream_digest=stable_sha256(item),
                    media_type="image/jpeg",
                    attribution=str(item.get("artist_display") or "Art Institute of Chicago collection"),
                    training_allowed=True,
                    trademark_hold=False,
                    source_observed_at=OBSERVED_AT,
                )
            )
            if len(rows) == target:
                return rows
        page += 1
        if page > int(payload.get("pagination", {}).get("total_pages", page)):
            raise RuntimeError("Art Institute API exhausted before target")
    return rows


def cleveland_records(target: int = 800) -> list[SourceBundleRecord]:
    rows: list[SourceBundleRecord] = []
    seen: set[str] = set()
    skip = 0
    while len(rows) < target:
        params = urllib.parse.urlencode(
            {"limit": 100, "skip": skip, "has_image": 1, "cc0": 1}
        )
        payload = fetch_json(
            f"https://openaccess-api.clevelandart.org/api/artworks/?{params}"
        )
        for item in payload.get("data", []):
            web = (item.get("images") or {}).get("web") or {}
            asset_url = str(web.get("url") or "").strip()
            evidence_url = str(item.get("url") or "").strip()
            if item.get("share_license_status") != "CC0" or not asset_url or not evidence_url:
                continue
            object_id = str(item["id"])
            if object_id in seen:
                continue
            seen.add(object_id)
            creators = item.get("creators") or []
            attribution = "; ".join(
                str(value.get("description") or "").strip()
                for value in creators
                if isinstance(value, dict) and str(value.get("description") or "").strip()
            ) or "Cleveland Museum of Art collection"
            rows.append(
                SourceBundleRecord(
                    source_id=f"cleveland-{object_id}",
                    provider="cleveland-museum-art",
                    upstream_asset_id=object_id,
                    kind="museum_visual",
                    title=str(item.get("title") or f"Cleveland object {object_id}"),
                    asset_url=asset_url,
                    evidence_url=evidence_url,
                    license_id="CC0-1.0",
                    license_url="https://openaccess-api.clevelandart.org/",
                    revision=str(item.get("accession_number") or f"object-{object_id}"),
                    digest_algorithm="sha256-canonical-api-record",
                    upstream_digest=stable_sha256(item),
                    media_type="image/jpeg",
                    attribution=attribution,
                    training_allowed=True,
                    trademark_hold=False,
                    source_observed_at=OBSERVED_AT,
                )
            )
            if len(rows) == target:
                return rows
        skip += 100
        if skip >= int(payload.get("info", {}).get("total", 0)):
            raise RuntimeError("Cleveland API exhausted before target")
    return rows


def github_tree(repo: str, revision: str) -> list[str]:
    payload = fetch_json(
        f"https://api.github.com/repos/{repo}/git/trees/{revision}?recursive=1"
    )
    if payload.get("truncated"):
        raise RuntimeError(f"GitHub tree response was truncated: {repo}")
    return sorted(
        str(item["path"])
        for item in payload.get("tree", [])
        if item.get("type") == "blob"
    )


def github_record(
    *, source_id: str, provider: str, repo: str, revision: str, path: str,
    kind: str, license_id: str, license_path: str, media_type: str,
    attribution: str,
) -> SourceBundleRecord:
    encoded_path = urllib.parse.quote(path, safe="/")
    encoded_license = urllib.parse.quote(license_path, safe="/")
    return SourceBundleRecord(
        source_id=source_id,
        provider=provider,
        upstream_asset_id=f"{revision}:{path}",
        kind=kind,
        title=path,
        asset_url=f"https://raw.githubusercontent.com/{repo}/{revision}/{encoded_path}",
        evidence_url=f"https://github.com/{repo}/blob/{revision}/{encoded_path}",
        license_id=license_id,
        license_url=f"https://github.com/{repo}/blob/{revision}/{encoded_license}",
        revision=revision,
        digest_algorithm="git-commit-pinned-locator",
        upstream_digest=stable_sha256({"revision": revision, "path": path}),
        media_type=media_type,
        attribution=attribution,
        training_allowed=True,
        trademark_hold=False,
        source_observed_at=OBSERVED_AT,
    )


def github_records(seed_asset_urls: set[str]) -> list[SourceBundleRecord]:
    fonts_revision = "2796410152d4f9524b68ed46e69c1b60f8e0f7c3"
    rocm_revision = "397421be29ce8a87464ed599f8c61555d129d55f"
    transformers_revision = "3717b9cda226af7377da1944f395af0eac6e2b51"
    font_tree = github_tree("google/fonts", fonts_revision)
    font_set = set(font_tree)
    font_paths = [
        path for path in font_tree
        if path.startswith("ofl/") and path.endswith(".ttf")
        and f"{path.rsplit('/', 1)[0]}/OFL.txt" in font_set
    ]
    rocm_paths = [
        path for path in github_tree("ROCm/ROCm", rocm_revision)
        if path.startswith("docs/") and path.endswith((".md", ".rst"))
    ]
    transformers_paths = [
        path for path in github_tree("huggingface/transformers", transformers_revision)
        if path.startswith(("docs/source/en/", "src/transformers/"))
        and path.endswith((".md", ".py"))
    ]
    output: list[SourceBundleRecord] = []
    for index, path in enumerate(font_paths):
        license_path = f"{path.rsplit('/', 1)[0]}/OFL.txt"
        item = github_record(
            source_id=f"google-font-{index:04d}", provider="google-fonts",
            repo="google/fonts", revision=fonts_revision, path=path, kind="font",
            license_id="OFL-1.1", license_path=license_path, media_type="font/ttf",
            attribution="Google Fonts upstream family authors",
        )
        if item.asset_url not in seed_asset_urls:
            output.append(item)
        if len([row for row in output if row.provider == "google-fonts"]) == 200:
            break
    for provider, repo, revision, paths, count, kind, license_id, license_path, attribution in (
        ("rocm", "ROCm/ROCm", rocm_revision, rocm_paths, 88, "hardware", "MIT", "LICENSE", "Advanced Micro Devices, Inc."),
        ("transformers", "huggingface/transformers", transformers_revision, transformers_paths, 88, "software", "Apache-2.0", "LICENSE", "Hugging Face and Transformers contributors"),
    ):
        accepted = 0
        for index, path in enumerate(paths):
            item = github_record(
                source_id=f"{provider}-{index:04d}", provider=provider, repo=repo,
                revision=revision, path=path, kind=kind, license_id=license_id,
                license_path=license_path, media_type="text/plain", attribution=attribution,
            )
            if item.asset_url in seed_asset_urls:
                continue
            output.append(item)
            accepted += 1
            if accepted == count:
                break
        if accepted != count:
            raise RuntimeError(f"{provider} tree did not provide {count} unique records")
    if len(output) != 376:
        raise RuntimeError(f"GitHub source target mismatch: {len(output)}")
    return output


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--refresh", action="store_true", help="fetch official upstream metadata")
    args = parser.parse_args()
    output = DATA / "sources.jsonl"
    if not args.refresh and output.is_file():
        print(json.dumps({"status": "existing_bundle_retained", "path": str(output)}))
        return 0

    seed = seed_records()
    rows = (
        seed
        + artic_records(800)
        + cleveland_records(800)
        + github_records({item.asset_url for item in seed})
    )
    receipt = validate_source_bundle(tuple(rows))
    DATA.mkdir(parents=True, exist_ok=True)
    EVIDENCE.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(
        output,
        "".join(
            json.dumps(
                {**asdict(item), "identity_sha256": item.identity_sha256},
                ensure_ascii=False,
                sort_keys=True,
            ) + "\n"
            for item in rows
        ),
    )
    receipt["sources_jsonl_sha256"] = stable_sha256(
        [item.identity_sha256 for item in rows]
    )
    receipt["observed_at"] = OBSERVED_AT
    receipt["official_license_sources"] = [
        "https://api.artic.edu/docs/",
        "https://www.artic.edu/open-access/open-access-images",
        "https://openaccess-api.clevelandart.org/",
        "https://github.com/google/fonts",
        "https://github.com/ROCm/ROCm",
        "https://github.com/huggingface/transformers",
        "https://commons.wikimedia.org/wiki/Commons:Licensing",
    ]
    receipt["content_sha256"] = stable_sha256(receipt)
    atomic_write_text(
        DATA / "manifest.json",
        json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
    )
    audit = {
        "schema": "ProofLaunchSourceBundle2000AuditV1",
        "canonical_todo": "0471",
        "manifest": receipt,
        "network_collection_observed": True,
        "raw_asset_bytes_saved": 0,
        "model_training_observed": False,
        "agency_corpus_v2_frozen": False,
        "content_sha256": stable_sha256({"manifest": receipt, "todo": "0471"}),
    }
    atomic_write_text(
        EVIDENCE,
        json.dumps(audit, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
    )
    print(json.dumps({"status": "collected", "source_count": len(rows), "providers": receipt["provider_counts"], "content_sha256": receipt["content_sha256"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
