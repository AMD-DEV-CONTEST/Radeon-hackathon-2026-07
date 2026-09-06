"""Screenshot the browser UI driving a real generation, for the demo video.

VHS records terminals, not browsers, so the UI half of the video is captured
here: a scripted run against the live Radeon endpoint, screenshotted at each
state. Every frame is a real page showing real output; nothing is mocked up.

    DUKAAN_INSTANCE=... python scripts/capture-ui.py http://127.0.0.1:7870 /tmp/uishots
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

URL = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:7870"
OUT = Path(sys.argv[2] if len(sys.argv) > 2 else "/tmp/uishots")
OUT.mkdir(parents=True, exist_ok=True)

HEADLINE = "Blue-and-white porcelain vase"
SUBLINE = "3,200 rupees, ships anywhere in India"
CONTACT = "+91 90000 00000"

shots = 0


def shot(page, name: str) -> None:
    global shots
    shots += 1
    path = OUT / f"{shots:02d}-{name}.png"
    page.screenshot(path=str(path), full_page=False)
    print("captured", path.name, flush=True)


with sync_playwright() as p:
    browser = p.chromium.launch()
    page = browser.new_page(viewport={"width": 1500, "height": 860}, device_scale_factor=2)
    page.goto(URL, wait_until="domcontentloaded", timeout=120_000)
    page.wait_for_selector("textarea, input[type=text]", timeout=60_000)
    page.wait_for_timeout(2500)
    shot(page, "empty")

    boxes = page.locator("textarea, input[type=text]")
    boxes.nth(0).fill(HEADLINE)
    boxes.nth(1).fill(SUBLINE)
    boxes.nth(2).fill(CONTACT)
    # The examples row is the quickest way to load a real photo.
    page.locator("button:has(img)").filter(has=page.locator("img[src*='porcelain-vase']")).first.click()
    page.wait_for_timeout(2500)
    shot(page, "filled")

    page.get_by_role("button", name="Make my pack").click()
    page.wait_for_timeout(4000)
    shot(page, "generating")

    # The GPU pass is about 95s plus transfer; poll for the result rather than
    # guessing, which is the mistake that ruined two earlier video takes.
    deadline = time.time() + 420
    while time.time() < deadline:
        if "from **one** pass" in page.content() or "creatives</strong> from" in page.content():
            break
        if "one</strong> pass" in page.content() or "Done." in page.inner_text("body"):
            break
        page.wait_for_timeout(3000)
    page.wait_for_timeout(4000)
    shot(page, "pack")

    page.mouse.wheel(0, 1400)
    page.wait_for_timeout(2000)
    shot(page, "scrubber")

    slider = page.locator("input[type=range]").first
    for moment in (12, 30, 44):
        slider.evaluate(
            "(el, v) => { const s = Object.getOwnPropertyDescriptor("
            "HTMLInputElement.prototype, 'value').set; s.call(el, String(v));"
            "el.dispatchEvent(new Event('input', {bubbles:true}));"
            "el.dispatchEvent(new Event('change', {bubbles:true})); }",
            moment,
        )
        page.wait_for_timeout(5000)
        shot(page, f"moment-{moment}")

    browser.close()

print(f"\n{shots} screenshots in {OUT}")
