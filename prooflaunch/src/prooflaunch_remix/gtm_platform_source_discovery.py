from __future__ import annotations

import hashlib
import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from html.parser import HTMLParser
from typing import Callable, Mapping, Sequence
from urllib.parse import urljoin, urlparse

from .ledger import canonical_json
from .social_collection_runner import BoundedPublicHttpClient, SocialCollectionExecutionError


PRIORITY_PLATFORMS = (
    "linkedin", "tiktok", "instagram", "reddit", "x", "facebook",
    "pinterest", "bluesky", "mastodon",
)

PLATFORM_HOSTS = {
    "linkedin": ("linkedin.com",),
    "tiktok": ("tiktok.com",),
    "instagram": ("instagram.com",),
    "reddit": ("reddit.com",),
    "x": ("x.com", "twitter.com"),
    "facebook": ("facebook.com", "fb.com"),
    "pinterest": ("pinterest.com", "pinterest.ca", "pinterest.co.uk"),
    "bluesky": ("bsky.app",),
}


class PlatformSourceDiscoveryError(ValueError):
    pass


@dataclass(frozen=True)
class OrganizationSeed:
    organization_id: str
    name: str
    homepage_url: str
    business_model: str
    market: str
    vertical: str
    company_scale: str
    lifecycle: str


class _LinkParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.links: list[tuple[str, frozenset[str]]] = []
        self._json_ld_depth = 0
        self._json_ld_buffer: list[str] = []
        self.json_ld_documents: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = {key.casefold(): value for key, value in attrs}
        normalized_tag = tag.casefold()
        if normalized_tag == "script" and str(attributes.get("type") or "").casefold() == "application/ld+json":
            self._json_ld_depth += 1
            self._json_ld_buffer = []
            return
        if normalized_tag not in {"a", "link"}:
            return
        href = attributes.get("href")
        if href:
            rel = frozenset(str(attributes.get("rel") or "").casefold().split())
            self.links.append((href.strip(), rel))

    def handle_endtag(self, tag: str) -> None:
        if tag.casefold() == "script" and self._json_ld_depth:
            self.json_ld_documents.append("".join(self._json_ld_buffer))
            self._json_ld_buffer = []
            self._json_ld_depth = 0

    def handle_data(self, data: str) -> None:
        if self._json_ld_depth:
            self._json_ld_buffer.append(data)

    def same_as_links(self) -> list[str]:
        links: list[str] = []

        def visit(value: object) -> None:
            if isinstance(value, Mapping):
                for key, nested in value.items():
                    if key == "sameAs":
                        values = nested if isinstance(nested, list) else [nested]
                        links.extend(item for item in values if isinstance(item, str))
                    else:
                        visit(nested)
            elif isinstance(value, list):
                for nested in value:
                    visit(nested)

        for document in self.json_ld_documents:
            try:
                visit(json.loads(document))
            except json.JSONDecodeError:
                continue
        return links


def _digest(value: object) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def _platform_for_url(url: str, rel: frozenset[str] = frozenset()) -> str | None:
    parsed = urlparse(url)
    host = (parsed.hostname or "").casefold().removeprefix("www.")
    for platform, suffixes in PLATFORM_HOSTS.items():
        if any(host == suffix or host.endswith("." + suffix) for suffix in suffixes):
            return platform
    if host and "mastodon" in host:
        return "mastodon"
    path_parts = [part for part in parsed.path.split("/") if part]
    if "me" in rel and path_parts and (
        path_parts[0].startswith("@")
        or (path_parts[0] == "users" and len(path_parts) >= 2)
    ):
        return "mastodon"
    return None


def _normalized_public_profile_url(
    raw_url: str,
    homepage_url: str,
    *,
    rel: frozenset[str] = frozenset(),
) -> str | None:
    url = urljoin(homepage_url, raw_url)
    parsed = urlparse(url)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
        return None
    platform = _platform_for_url(url, rel)
    if platform is None:
        return None
    # Tracking fragments and query strings are not part of the account identity.
    path = parsed.path.rstrip("/") or "/"
    return f"https://{parsed.hostname.casefold()}{path}"


def discover_organization_sources(
    seed: OrganizationSeed,
    *,
    http_client: BoundedPublicHttpClient,
    timeout_seconds: float = 10,
    maximum_bytes: int = 1_500_000,
) -> dict[str, object]:
    try:
        response = http_client.get(
            seed.homepage_url,
            timeout_seconds=timeout_seconds,
            maximum_bytes=maximum_bytes,
        )
        content_type = response.headers.get("content-type", "").casefold()
        if "html" not in content_type and not response.body.lstrip().startswith(b"<"):
            raise SocialCollectionExecutionError("organization homepage did not return HTML")
        parser = _LinkParser()
        parser.feed(response.body.decode("utf-8", errors="replace"))
        discovered: dict[str, list[str]] = {platform: [] for platform in PRIORITY_PLATFORMS}
        candidates = list(parser.links)
        candidates.extend((url, frozenset()) for url in parser.same_as_links())
        for raw_url, rel in candidates:
            normalized = _normalized_public_profile_url(raw_url, response.url, rel=rel)
            if normalized is None:
                continue
            platform = _platform_for_url(normalized, rel)
            if platform in discovered and normalized not in discovered[platform]:
                discovered[platform].append(normalized)
        source_count = sum(len(urls) for urls in discovered.values())
        return {
            "organization_id": seed.organization_id,
            "name": seed.name,
            "homepage_url": seed.homepage_url,
            "homepage_url_sha256": hashlib.sha256(seed.homepage_url.encode()).hexdigest(),
            "business_model": seed.business_model,
            "market": seed.market,
            "vertical": seed.vertical,
            "company_scale": seed.company_scale,
            "lifecycle": seed.lifecycle,
            "status": "completed" if source_count else "completed_no_social_links_found",
            "homepage_final_host": urlparse(response.url).hostname,
            "homepage_body_sha256": hashlib.sha256(response.body).hexdigest(),
            "discovered_sources": {key: value for key, value in discovered.items() if value},
            "discovered_source_count": source_count,
            "discovery_method": "bounded_public_homepage_anchor_jsonld_sameas_and_relme_scan",
        }
    except (SocialCollectionExecutionError, UnicodeError) as error:
        return {
            "organization_id": seed.organization_id,
            "name": seed.name,
            "homepage_url": seed.homepage_url,
            "homepage_url_sha256": hashlib.sha256(seed.homepage_url.encode()).hexdigest(),
            "business_model": seed.business_model,
            "market": seed.market,
            "vertical": seed.vertical,
            "company_scale": seed.company_scale,
            "lifecycle": seed.lifecycle,
            "status": "human_handoff_required",
            "error": str(error)[:500],
            "discovered_sources": {},
            "discovered_source_count": 0,
            "discovery_method": "bounded_public_homepage_anchor_jsonld_sameas_and_relme_scan",
        }


def discover_platform_source_registry(
    seeds: Sequence[OrganizationSeed],
    *,
    http_client_factory: Callable[[], BoundedPublicHttpClient] = BoundedPublicHttpClient,
    maximum_workers: int = 8,
) -> dict[str, object]:
    if not 1 <= len(seeds) <= 200:
        raise PlatformSourceDiscoveryError("one to two hundred organization seeds are required")
    if not 1 <= maximum_workers <= 12:
        raise PlatformSourceDiscoveryError("maximum_workers must be in [1, 12]")
    identities = [seed.organization_id for seed in seeds]
    if len(identities) != len(set(identities)):
        raise PlatformSourceDiscoveryError("organization ids must be unique")
    rows: list[dict[str, object]] = []
    with ThreadPoolExecutor(max_workers=maximum_workers) as executor:
        futures = {
            executor.submit(
                discover_organization_sources,
                seed,
                http_client=http_client_factory(),
            ): seed.organization_id
            for seed in seeds
        }
        for future in as_completed(futures):
            rows.append(future.result())
    rows.sort(key=lambda row: str(row["organization_id"]))
    discovered = sum(int(row["discovered_source_count"]) for row in rows)
    completed = sum(str(row["status"]).startswith("completed") for row in rows)
    payload: dict[str, object] = {
        "schema": "ProofLaunchPlatformSourceDiscoveryRegistryV1",
        "priority_platforms": list(PRIORITY_PLATFORMS),
        "organization_seed_count": len(rows),
        "completed_homepage_count": completed,
        "handoff_homepage_count": len(rows) - completed,
        "discovered_source_count": discovered,
        "organizations": rows,
        "automatic_external_publish_count": 0,
        "automatic_learning_memory_write_count": 0,
        "truth_boundary": (
            "A discovered URL is a public source candidate proven only by an organization homepage link. "
            "It is not observed platform content, recent coverage, a training license or an effectiveness claim."
        ),
    }
    payload["content_sha256"] = _digest(payload)
    return payload


def load_organization_seeds(value: Mapping[str, object]) -> list[OrganizationSeed]:
    rows = value.get("organizations")
    if not isinstance(rows, list):
        raise PlatformSourceDiscoveryError("organizations must be a list")
    allowed_business_models = {"b2b", "b2c"}
    seeds: list[OrganizationSeed] = []
    for row in rows:
        if not isinstance(row, Mapping):
            raise PlatformSourceDiscoveryError("organization seed must be an object")
        seed = OrganizationSeed(**{field: str(row[field]) for field in OrganizationSeed.__dataclass_fields__})
        if seed.business_model not in allowed_business_models:
            raise PlatformSourceDiscoveryError("organization business_model is invalid")
        if not seed.homepage_url.startswith("https://"):
            raise PlatformSourceDiscoveryError("organization homepage must be HTTPS")
        seeds.append(seed)
    return seeds


def registry_json(payload: Mapping[str, object]) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
