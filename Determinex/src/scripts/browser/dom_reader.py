"""DOM snapshot reader — extracts structured content using injected Playwright page objects."""

from __future__ import annotations

import hashlib
import logging
from typing import Any

log = logging.getLogger(__name__)


def get_dom_snapshot(page: Any) -> str:
    """Get full outer HTML from a Playwright page."""
    try:
        return page.content()
    except Exception as exc:
        log.error("[dom_reader] get_dom_snapshot failed: %s", exc)
        return ""


def dom_hash(html: str) -> str:
    return hashlib.sha256(html.encode()).hexdigest()


def find_selector(page: Any, selector: str) -> bool:
    """True if a CSS selector matches at least one element."""
    try:
        return page.locator(selector).count() > 0
    except Exception:
        return False


def get_text_content(page: Any, selector: str) -> str:
    try:
        return page.locator(selector).inner_text()
    except Exception:
        return ""


def get_input_value(page: Any, selector: str) -> str:
    try:
        return page.locator(selector).input_value()
    except Exception:
        return ""


def get_all_links(page: Any) -> list[dict[str, str]]:
    try:
        elements = page.locator("a[href]").all()
        return [{"text": e.inner_text(), "href": e.get_attribute("href") or ""} for e in elements]
    except Exception as exc:
        log.error("[dom_reader] get_all_links failed: %s", exc)
        return []


def get_all_forms(page: Any) -> list[dict[str, Any]]:
    try:
        forms = []
        form_elements = page.locator("form").all()
        for form in form_elements:
            action = form.get_attribute("action") or ""
            method = form.get_attribute("method") or "get"
            inputs = []
            for inp in form.locator("input, textarea, select").all():
                inputs.append(
                    {
                        "name": inp.get_attribute("name") or "",
                        "type": inp.get_attribute("type") or "text",
                        "value": "",
                    }
                )
            forms.append({"action": action, "method": method.upper(), "inputs": inputs})
        return forms
    except Exception as exc:
        log.error("[dom_reader] get_all_forms failed: %s", exc)
        return []


def page_title(page: Any) -> str:
    try:
        return page.title()
    except Exception:
        return ""


def current_url(page: Any) -> str:
    try:
        return page.url
    except Exception:
        return ""


def extract_visible_text(page: Any) -> str:
    """Extract all visible text content from the page."""
    try:
        return page.evaluate("() => document.body ? document.body.innerText : ''")
    except Exception:
        return ""


def has_text(page: Any, text: str, exact: bool = False) -> bool:
    try:
        if exact:
            return page.get_by_text(text, exact=True).count() > 0
        return text.lower() in (extract_visible_text(page) or "").lower()
    except Exception:
        return False
