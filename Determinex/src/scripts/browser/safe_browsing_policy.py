"""
Safe browsing policy — URL and action screening for browser agents.
Blocks navigation to dangerous domains and prevents accidental purchases/form submits.
"""

from __future__ import annotations

import logging
import re
import urllib.parse
from dataclasses import dataclass

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# URL policy
# ---------------------------------------------------------------------------

_BLOCKED_URL_PATTERNS: list[tuple[str, re.Pattern]] = [
    (
        "phishing_keywords",
        re.compile(r"(paypal|bank|login|account|verify|secure)\.(tk|ml|ga|cf|gq)\b", re.I),
    ),
    ("ip_only_url", re.compile(r"https?://\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}(?:[:/]|$)")),
    ("credential_in_url", re.compile(r"https?://[^@]+:[^@]+@", re.I)),
    ("data_url_exec", re.compile(r"^data:(text/html|application/javascript)", re.I)),
    ("javascript_url", re.compile(r"^javascript:", re.I)),
    (
        "local_network",
        re.compile(
            r"https?://(localhost|127\.\d+\.\d+\.\d+|192\.168\.|10\.\d+\.|172\.(1[6-9]|2\d|3[01])\.)",
            re.I,
        ),
    ),
]

_HIGH_RISK_DOMAINS: frozenset[str] = frozenset(
    {
        "payment.page",
        "checkout",
        "billing",
        "cart",
        "buy",
        "purchase",
    }
)

_ALLOWED_FORM_DOMAINS_ENV = "DETERMINEX_ALLOWED_FORM_DOMAINS"


@dataclass
class URLVerdict:
    allowed: bool
    reason: str
    url: str


def check_url(url: str) -> URLVerdict:
    """Return URLVerdict — call before navigating to any URL."""
    if not url:
        return URLVerdict(allowed=False, reason="empty_url", url=url)

    for category, pattern in _BLOCKED_URL_PATTERNS:
        if pattern.search(url):
            log.warning("[safe_browsing] BLOCKED url category=%s url=%s", category, url[:120])
            return URLVerdict(allowed=False, reason=category, url=url)

    return URLVerdict(allowed=True, reason="ok", url=url)


def is_high_risk_domain(url: str) -> bool:
    try:
        parsed = urllib.parse.urlparse(url)
        host = (parsed.netloc or "").lower()
        return any(kw in host for kw in _HIGH_RISK_DOMAINS)
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Action policy
# ---------------------------------------------------------------------------

_FORM_SUBMIT_BLOCK_PATTERNS: list[re.Pattern] = [
    re.compile(r"(credit.?card|card.?number|cvv|cvc|expir)", re.I),
    re.compile(r"(billing.?address|payment.?method)", re.I),
    re.compile(r"(subscribe|checkout|place.?order|confirm.?purchase)", re.I),
    re.compile(r"(ssn|social.?security|tax.?id|passport)", re.I),
]


def check_form_submit(form_html: str, url: str) -> tuple[bool, str]:
    """
    Returns (allowed, reason).
    Blocks form submissions that look like payment or PII forms.
    """
    for pattern in _FORM_SUBMIT_BLOCK_PATTERNS:
        if pattern.search(form_html):
            return False, f"form contains high-risk field pattern: {pattern.pattern}"
    if is_high_risk_domain(url):
        return False, f"form on high-risk domain: {url}"
    return True, "ok"


def check_download_url(url: str) -> tuple[bool, str]:
    """
    Returns (allowed, reason).
    Blocks downloads from blocked-pattern URLs.
    """
    verdict = check_url(url)
    if not verdict.allowed:
        return False, verdict.reason

    # Block executable extensions by default
    lower = url.lower()
    for ext in (".exe", ".msi", ".bat", ".cmd", ".ps1", ".sh", ".dmg", ".pkg", ".deb", ".rpm"):
        if lower.endswith(ext):
            return False, f"blocked executable extension: {ext}"

    return True, "ok"
