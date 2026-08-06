from __future__ import annotations

import hashlib
import ipaddress
from dataclasses import dataclass
from typing import Mapping, Sequence
from urllib.parse import urlparse

from .ledger import canonical_json


class SocialCollectionError(ValueError):
    pass


@dataclass(frozen=True)
class OpenSourceConnector:
    connector_id: str
    repository: str
    revision: str
    license: str
    platforms: tuple[str, ...]
    modalities: tuple[str, ...]
    execution_mode: str
    package_version: str | None = None
    external_api_key_required: bool = False
    live_execution_admitted: bool = False
    maintenance_note: str = ""


CONNECTORS = (
    OpenSourceConnector(
        "yt-dlp",
        "https://github.com/yt-dlp/yt-dlp",
        "fdcc954df4955267ec1627cbeb347b661a110e7c",
        "Unlicense_with_dependency_specific_terms",
        ("youtube", "vimeo", "tiktok", "facebook", "x", "instagram", "generic_video"),
        ("video", "audio", "content", "metadata", "subtitles", "comments"),
        "isolated_subprocess",
        "2026.7.4",
        False,
        True,
    ),
    OpenSourceConnector(
        "gallery-dl",
        "https://github.com/mikf/gallery-dl",
        "86047cf67a12bdb6ff1085774f8ad9fc347e8da9",
        "GPL-2.0",
        ("instagram", "x", "pinterest", "tumblr", "flickr", "deviantart"),
        ("image", "video", "content", "metadata", "comments"),
        "separate_GPL_subprocess",
        "1.32.9",
        False,
        True,
        "Primary development moved to Codeberg; keep the frozen GitHub revision reproducible and monitor migration.",
    ),
    OpenSourceConnector(
        "instaloader",
        "https://github.com/instaloader/instaloader",
        "543469296ec61e49c4e1d34edac39f043b16a5f1",
        "MIT",
        ("instagram",),
        ("image", "video", "content", "metadata", "comments"),
        "isolated_subprocess",
        None,
    ),
    OpenSourceConnector(
        "crawlee-python",
        "https://github.com/apify/crawlee-python",
        "acbb5a03f92c5e5e94d9ccc4ac2019b24a19caa7",
        "Apache-2.0",
        ("linkedin", "facebook", "x", "tiktok", "generic_web"),
        ("content", "metadata", "comments", "image", "video"),
        "sandboxed_collector_worker",
        None,
    ),
    OpenSourceConnector(
        "beautifulsoup4",
        "https://www.crummy.com/software/BeautifulSoup/bs4/",
        "df13521e601dbf7f685ece62e37543bbadfa9f5f",
        "MIT",
        ("linkedin", "generic_web"),
        ("content", "metadata", "image"),
        "bounded_static_html_metadata_worker",
        "4.15.0",
        False,
        True,
        "Revision pins the installed distribution RECORD SHA-1; no browser automation, login flow or script execution is admitted.",
    ),
    OpenSourceConnector(
        "praw",
        "https://github.com/praw-dev/praw",
        "b24b6f46a95b471ba0f436ec7c5d3a0e6852925d",
        "BSD-2-Clause",
        ("reddit",),
        ("content", "metadata", "comments", "image", "video"),
        "credential_scoped_worker",
        None,
        True,
    ),
    OpenSourceConnector(
        "atproto",
        "https://github.com/MarshalX/atproto",
        "15b949947741f24c419f6c7feb65af4fc0b2d008",
        "MIT",
        ("bluesky",),
        ("content", "metadata", "comments", "image", "video"),
        "native_public_protocol_worker",
        None,
        False,
        True,
        "Live execution uses the official public Bluesky AppView read contract; no session or write API is admitted.",
    ),
    OpenSourceConnector(
        "mastodon.py",
        "https://github.com/halcy/Mastodon.py",
        "5aa1cdfd8ad4e6fd270a62299f578a96f15650fa",
        "MIT",
        ("mastodon",),
        ("content", "metadata", "comments", "image", "video", "audio"),
        "native_public_protocol_worker",
        None,
        False,
        True,
        "Live execution is limited to same-origin public status and context reads; no session or write API is admitted.",
    ),
    OpenSourceConnector(
        "feedparser",
        "https://github.com/kurtmckee/feedparser",
        "9c03a51a209a50328f628014a9b4dbb9d56b8c11",
        "BSD-2-Clause",
        ("feed", "reddit", "pinterest"),
        ("content", "metadata", "image", "video", "audio"),
        "bounded_public_feed_worker",
        "6.0.12",
        False,
        True,
        "The runtime fetches a bounded HTTPS body itself and passes bytes to feedparser; feedparser may not perform a second network request.",
    ),
    OpenSourceConnector(
        "rsshub",
        "https://github.com/DIYgod/RSSHub",
        "080796cc4fb7e5552791c309d8c05fe98a25c289",
        "AGPL-3.0",
        (
            "youtube",
            "tiktok",
            "instagram",
            "facebook",
            "x",
            "reddit",
            "bluesky",
            "mastodon",
            "linkedin",
            "pinterest",
            "tumblr",
            "generic_web",
        ),
        ("content", "metadata", "image", "video", "audio"),
        "self_hosted_feed_discovery",
    ),
    OpenSourceConnector(
        "trafilatura",
        "https://github.com/adbar/trafilatura",
        "c1bc9531a2a978326112ca9987e1382745116136",
        "Apache-2.0",
        ("generic_web",),
        ("content", "metadata", "comments", "image"),
        "isolated_static_extractor",
    ),
    OpenSourceConnector(
        "scrapy",
        "https://github.com/scrapy/scrapy",
        "11d1712a2cdfde86be037553f18780c45d534222",
        "BSD-3-Clause",
        ("generic_web",),
        ("content", "metadata", "comments", "image", "video", "audio"),
        "bounded_crawl_worker",
    ),
    OpenSourceConnector(
        "crawl4ai",
        "https://github.com/unclecode/crawl4ai",
        "7e801521428ee12509994d39151006f64055ebe3",
        "Apache-2.0",
        ("generic_web",),
        ("content", "metadata", "comments", "image", "video", "audio"),
        "sandboxed_public_browser_worker",
        None,
        False,
        False,
        "Only the ordinary public-browser path is eligible; stealth or access-control evasion is forbidden.",
    ),
    OpenSourceConnector(
        "firecrawl-self-hosted",
        "https://github.com/firecrawl/firecrawl",
        "2eab3009253a56360790316fc15d1b95c0c431d2",
        "AGPL-3.0_with_component_specific_terms",
        ("generic_web",),
        ("content", "metadata", "comments", "image", "video", "audio"),
        "self_hosted_public_web_context_worker",
        None,
        False,
        False,
        "Self-hosted public-page fallback only; robots and site-policy controls remain enabled.",
    ),
)

_PUBLIC_NO_API_FALLBACK_ORDER = (
    "rsshub",
    "trafilatura",
    "scrapy",
    "crawl4ai",
    "firecrawl-self-hosted",
)
_PLATFORM_CONNECTOR_PREFERENCE = {
    "instagram": "gallery-dl",
    "x": "gallery-dl",
    "pinterest": "gallery-dl",
    "tumblr": "gallery-dl",
    "flickr": "gallery-dl",
    "deviantart": "gallery-dl",
    "linkedin": "beautifulsoup4",
}

_HOST_PLATFORM = {
    "youtube.com": "youtube",
    "youtu.be": "youtube",
    "vimeo.com": "vimeo",
    "tiktok.com": "tiktok",
    "instagram.com": "instagram",
    "facebook.com": "facebook",
    "fb.watch": "facebook",
    "x.com": "x",
    "twitter.com": "x",
    "reddit.com": "reddit",
    "bsky.app": "bluesky",
    "linkedin.com": "linkedin",
    "pinterest.com": "pinterest",
    "tumblr.com": "tumblr",
    "flickr.com": "flickr",
    "deviantart.com": "deviantart",
}
_PLATFORM_HINTS = frozenset(
    {
        "youtube",
        "vimeo",
        "tiktok",
        "instagram",
        "facebook",
        "x",
        "reddit",
        "bluesky",
        "mastodon",
        "linkedin",
        "pinterest",
        "tumblr",
        "flickr",
        "deviantart",
        "feed",
        "generic_web",
    }
)
_MODALITIES = frozenset(
    {"video", "audio", "image", "content", "metadata", "comments", "subtitles"}
)
_RIGHTS = frozenset({"owned", "licensed", "public_measurement", "account_authorized"})
_BUSINESS_MODELS = frozenset({"b2b", "b2c"})
_COMPANY_SCALES = frozenset({"small", "mid_market", "enterprise_or_mass_brand"})
_LIFECYCLES = frozenset({"pre_pmf", "launch", "growth", "mature"})
_MARKET_GROUPS = frozenset({
    "north_america", "uk_ireland", "europe_english", "southern_africa_english",
    "singapore", "hong_kong", "anz",
})
_SOURCE_CONTEXT_FIELDS = frozenset({
    "business_model", "vertical", "company_scale", "lifecycle", "market",
})


def _platform_for_url(url: str) -> tuple[str, str]:
    parsed = urlparse(url)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
        raise SocialCollectionError("source URLs must be credential-free HTTPS URLs")
    host = parsed.hostname.casefold().removeprefix("www.")
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        address = None
    if address is not None and (
        address.is_private or address.is_loopback or address.is_link_local
    ):
        raise SocialCollectionError("private or loopback source hosts are forbidden")
    platform = next(
        (
            value
            for suffix, value in _HOST_PLATFORM.items()
            if host == suffix or host.endswith("." + suffix)
        ),
        "generic_web",
    )
    return platform, host


def plan_social_collection(request: Mapping[str, object]) -> dict[str, object]:
    if not isinstance(request, Mapping):
        raise SocialCollectionError("collection request must be an object")
    urls = request.get("urls")
    platform_hints = request.get("platform_hints")
    source_contexts = request.get("source_contexts")
    modalities = request.get("modalities")
    rights = request.get("rights")
    if not isinstance(urls, list) or not 1 <= len(urls) <= 50:
        raise SocialCollectionError("urls must contain between 1 and 50 entries")
    if platform_hints is not None:
        if not isinstance(platform_hints, list) or len(platform_hints) != len(urls):
            raise SocialCollectionError("platform_hints must match urls one-for-one")
        if any(
            not isinstance(item, str) or item not in _PLATFORM_HINTS
            for item in platform_hints
        ):
            raise SocialCollectionError("platform_hints contains an unsupported platform")
    if source_contexts is not None:
        if not isinstance(source_contexts, list) or len(source_contexts) != len(urls):
            raise SocialCollectionError("source_contexts must match urls one-for-one")
        for context in source_contexts:
            if not isinstance(context, Mapping) or set(context) != _SOURCE_CONTEXT_FIELDS:
                raise SocialCollectionError("source context fields violate the closed contract")
            if context["business_model"] not in _BUSINESS_MODELS:
                raise SocialCollectionError("source context business_model is invalid")
            if not isinstance(context["vertical"], str) or not context["vertical"].strip() or len(context["vertical"]) > 120:
                raise SocialCollectionError("source context vertical is invalid")
            if context["company_scale"] not in _COMPANY_SCALES:
                raise SocialCollectionError("source context company_scale is invalid")
            if context["lifecycle"] not in _LIFECYCLES:
                raise SocialCollectionError("source context lifecycle is invalid")
            if context["market"] not in _MARKET_GROUPS:
                raise SocialCollectionError("source context market is invalid")
    if not isinstance(modalities, list) or not modalities:
        raise SocialCollectionError("modalities must be a non-empty list")
    normalized_modalities = tuple(sorted(set(str(item) for item in modalities)))
    if not set(normalized_modalities).issubset(_MODALITIES):
        raise SocialCollectionError("collection modalities are unsupported")
    if rights not in _RIGHTS:
        raise SocialCollectionError("collection rights basis is unsupported")
    max_items = request.get("maximum_items", 500)
    max_bytes = request.get("maximum_bytes", 2_000_000_000)
    timeout_seconds = request.get("timeout_seconds", 900)
    retention_days = request.get("retention_days", 30)
    if type(max_items) is not int or not 1 <= max_items <= 5_000:
        raise SocialCollectionError("maximum_items must be in [1, 5000]")
    if type(max_bytes) is not int or not 1 <= max_bytes <= 10_000_000_000:
        raise SocialCollectionError("maximum_bytes must be in [1, 10000000000]")
    if type(timeout_seconds) is not int or not 1 <= timeout_seconds <= 3_600:
        raise SocialCollectionError("timeout_seconds must be in [1, 3600]")
    if type(retention_days) is not int or not 1 <= retention_days <= 365:
        raise SocialCollectionError("retention_days must be in [1, 365]")

    plans: list[dict[str, object]] = []
    connector_order = {
        connector.connector_id: index for index, connector in enumerate(CONNECTORS)
    }
    for source_index, raw_url in enumerate(urls):
        if not isinstance(raw_url, str) or len(raw_url) > 2_000:
            raise SocialCollectionError("source URL is invalid")
        detected_platform, host = _platform_for_url(raw_url)
        platform = (
            str(platform_hints[source_index])
            if platform_hints is not None
            else detected_platform
        )
        candidates = [
            connector
            for connector in CONNECTORS
            if (platform in connector.platforms or "generic_web" in connector.platforms)
            and set(normalized_modalities).issubset(set(connector.modalities))
        ]
        if not candidates:
            raise SocialCollectionError(
                f"no admitted connector covers {platform} and requested modalities"
            )
        selected = min(
            candidates,
            key=lambda connector: (
                0 if platform in connector.platforms else 1,
                0 if connector.live_execution_admitted else 1,
                0 if not connector.external_api_key_required else 1,
                0 if connector.connector_id == _PLATFORM_CONNECTOR_PREFERENCE.get(platform) else 1,
                connector_order[connector.connector_id],
            ),
        )
        media_download_allowed = rights in {"owned", "licensed", "account_authorized"}
        fallback_steps: list[dict[str, object]] = []
        for connector_id in _PUBLIC_NO_API_FALLBACK_ORDER:
            connector = next(item for item in CONNECTORS if item.connector_id == connector_id)
            if connector.external_api_key_required:
                continue
            covered = sorted(set(normalized_modalities).intersection(connector.modalities))
            if not covered:
                continue
            fallback_steps.append(
                {
                    "order": len(fallback_steps) + 1,
                    "connector_id": connector.connector_id,
                    "connector_revision": connector.revision,
                    "execution_mode": connector.execution_mode,
                    "covered_modalities": covered,
                    "external_api_key_required": False,
                    "live_execution_admitted": connector.live_execution_admitted,
                    "access_policy": "public_or_operator_authorized_only",
                    "on_auth_captcha_paywall_or_denial": "stop_and_human_handoff",
                    "rate_policy": "bounded_polite_backoff_no_evasion",
                }
            )
        source_plan: dict[str, object] = {
                "source_url_sha256": hashlib.sha256(raw_url.encode("utf-8")).hexdigest(),
                "source_host": host,
                "platform": platform,
                "platform_detection": (
                    "operator_hint" if platform_hints is not None else "host_map"
                ),
                "connector_id": selected.connector_id,
                "connector_revision": selected.revision,
                "modalities": list(normalized_modalities),
                "media_download_allowed": media_download_allowed,
                "public_measurement_metadata_only": rights == "public_measurement",
                "raw_content_training_admitted": False,
                "public_no_api_fallback_graph": fallback_steps,
            }
        if source_contexts is not None:
            source_plan["sampling_context"] = dict(source_contexts[source_index])
        plans.append(source_plan)
    core: dict[str, object] = {
        "schema": "ProofLaunchOpenSourceSocialCollectionPlanV1",
        "status": "planned_not_executed",
        "source_count": len(plans),
        "plans": plans,
        "budgets": {
            "maximum_items": max_items,
            "maximum_bytes": max_bytes,
            "timeout_seconds": timeout_seconds,
            "retention_days": retention_days,
        },
        "rights": rights,
        "output_layers": [
            "isolated_raw_CAS",
            "PII_and_rights_filter",
            "derived_multimodal_features",
            "creative_signal_snapshot",
            "human_reviewed_strategy_hypotheses",
        ],
        "forbidden": [
            "authentication_bypass",
            "captcha_bypass",
            "paywall_bypass",
            "rate_limit_evasion",
            "default_training_on_collected_content",
            "automatic_external_publish",
        ],
        "truth_boundary": (
            "This plan selects pinned open-source collectors and a public no-external-API-key "
            "fallback graph. It does not prove a live crawl, platform permission, media "
            "ownership, training rights or strategy lift."
        ),
    }
    core["plan_sha256"] = hashlib.sha256(
        canonical_json(core).encode("utf-8")
    ).hexdigest()
    return core


def connector_registry() -> Sequence[OpenSourceConnector]:
    return CONNECTORS
