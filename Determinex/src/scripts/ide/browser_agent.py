"""
Determinex Browser Agent — headless Chrome automation for Hive workflows.

Usage:
    python scripts/ide/browser_agent.py navigate <url> [--screenshot <path>] [--extract-text]
    python scripts/ide/browser_agent.py click <url> <selector> [--screenshot <path>]
    python scripts/ide/browser_agent.py screenshot <url> <output_path>

Requires: pip install playwright && playwright install chromium
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime
from pathlib import Path


def _ensure_playwright() -> None:
    try:
        from playwright.sync_api import sync_playwright  # noqa: F401
    except ImportError:
        print(
            "ERROR: playwright not installed. Run: pip install playwright && playwright install chromium",
            file=sys.stderr,
        )
        sys.exit(1)


def cmd_navigate(url: str, screenshot_path: str | None, extract_text: bool) -> dict:
    from playwright.sync_api import sync_playwright

    result: dict = {"url": url, "timestamp": datetime.utcnow().isoformat() + "Z"}
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1280, "height": 900})
        response = page.goto(url, wait_until="networkidle", timeout=30_000)
        result["status_code"] = response.status if response else None
        result["title"] = page.title()
        if extract_text:
            result["text"] = page.inner_text("body")
        if screenshot_path:
            out = Path(screenshot_path)
            out.parent.mkdir(parents=True, exist_ok=True)
            page.screenshot(path=str(out), full_page=True)
            data = out.read_bytes()
            result["screenshot_path"] = str(out)
            result["screenshot_sha256"] = hashlib.sha256(data).hexdigest()
            result["screenshot_bytes"] = len(data)
        browser.close()
    return result


def cmd_click(url: str, selector: str, screenshot_path: str | None) -> dict:
    from playwright.sync_api import sync_playwright

    result: dict = {
        "url": url,
        "selector": selector,
        "timestamp": datetime.utcnow().isoformat() + "Z",
    }
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1280, "height": 900})
        page.goto(url, wait_until="networkidle", timeout=30_000)
        page.click(selector, timeout=10_000)
        page.wait_for_timeout(1_000)
        result["clicked"] = True
        result["title"] = page.title()
        if screenshot_path:
            out = Path(screenshot_path)
            out.parent.mkdir(parents=True, exist_ok=True)
            page.screenshot(path=str(out), full_page=True)
            data = out.read_bytes()
            result["screenshot_path"] = str(out)
            result["screenshot_sha256"] = hashlib.sha256(data).hexdigest()
        browser.close()
    return result


def cmd_screenshot(url: str, output_path: str) -> dict:
    return cmd_navigate(url, output_path, extract_text=False)


def main() -> None:
    _ensure_playwright()

    parser = argparse.ArgumentParser(description="Determinex headless browser agent")
    sub = parser.add_subparsers(dest="command", required=True)

    nav = sub.add_parser("navigate", help="Navigate and optionally screenshot a URL")
    nav.add_argument("url")
    nav.add_argument("--screenshot", default=None)
    nav.add_argument("--extract-text", action="store_true")

    clk = sub.add_parser("click", help="Navigate, click a selector, screenshot")
    clk.add_argument("url")
    clk.add_argument("selector")
    clk.add_argument("--screenshot", default=None)

    shot = sub.add_parser("screenshot", help="Navigate and save a screenshot")
    shot.add_argument("url")
    shot.add_argument("output_path")

    args = parser.parse_args()

    if args.command == "navigate":
        result = cmd_navigate(args.url, args.screenshot, args.extract_text)
    elif args.command == "click":
        result = cmd_click(args.url, args.selector, args.screenshot)
    elif args.command == "screenshot":
        result = cmd_screenshot(args.url, args.output_path)
    else:
        parser.print_help()
        sys.exit(1)

    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
