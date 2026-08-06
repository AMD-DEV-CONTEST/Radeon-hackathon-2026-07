from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path

from playwright.sync_api import Locator, Page, sync_playwright


ROOT = Path(__file__).resolve().parent
OUTPUT = ROOT / "operation"
RAW = OUTPUT / "raw"
URL = "http://127.0.0.1:8765/control/frontier-gtm?ui=v11-six-master&demo-capture=v1"


def hold(page: Page, seconds: float) -> None:
    page.wait_for_timeout(round(seconds * 1000))


def move_to(page: Page, locator: Locator, *, steps: int = 36) -> tuple[float, float]:
    locator.scroll_into_view_if_needed()
    box = locator.bounding_box()
    if box is None:
        raise RuntimeError("Cannot resolve the target bounding box")
    x = box["x"] + box["width"] / 2
    y = box["y"] + box["height"] / 2
    page.mouse.move(x, y, steps=steps)
    return x, y


def move_click(page: Page, locator: Locator, *, post_hold: float = 1.5) -> None:
    move_to(page, locator)
    hold(page, 0.35)
    page.mouse.down()
    hold(page, 0.12)
    page.mouse.up()
    hold(page, post_hold)


def smooth_center(page: Page, selector: str, *, hold_after: float = 1.6) -> None:
    page.evaluate(
        """selector => {
          const node = document.querySelector(selector);
          if (!node) throw new Error(`Missing selector: ${selector}`);
          const rect = node.getBoundingClientRect();
          const top = window.scrollY + rect.top - Math.max(24, (window.innerHeight - rect.height) / 2);
          window.scrollTo({top: Math.max(0, top), behavior: 'smooth'});
        }""",
        selector,
    )
    hold(page, hold_after)


def main() -> None:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    RAW.mkdir(parents=True, exist_ok=True)
    started = time.perf_counter()
    events: list[dict[str, object]] = []

    def mark(label: str) -> None:
        events.append({"label": label, "seconds": round(time.perf_counter() - started, 3)})

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        context = browser.new_context(
            viewport={"width": 1920, "height": 1080},
            record_video_dir=str(RAW),
            record_video_size={"width": 1920, "height": 1080},
            color_scheme="light",
            reduced_motion="no-preference",
        )
        page = context.new_page()
        video = page.video
        page.goto(URL, wait_until="networkidle")
        page.mouse.move(1640, 118, steps=1)
        mark("studio_loaded")
        hold(page, 4.0)

        recipe = page.locator('[data-frontier-recipe="technical-proof"]')
        move_to(page, recipe)
        hold(page, 1.2)
        mark("technical_proof_recipe_focused")
        move_click(page, recipe, post_hold=1.0)
        mark("generation_started")

        page.locator("#frontier-gtm-result").wait_for(state="visible", timeout=90_000)
        page.locator("#frontier-media-gallery img").first.wait_for(state="visible", timeout=90_000)
        page.wait_for_function(
            """() => {
              const videos = [...document.querySelectorAll('#frontier-media-gallery video')];
              return videos.length === 3 && videos.every(v => v.readyState >= 1 && v.duration >= 8);
            }""",
            timeout=90_000,
        )
        mark("six_assets_ready")
        smooth_center(page, "#frontier-gtm-result", hold_after=4.2)

        overview = page.locator('[data-frontier-output-tab="overview"]')
        move_click(page, overview, post_hold=1.0)
        smooth_center(page, "#frontier-gtm-result", hold_after=3.2)
        mark("agent_council_overview_shown")

        copy_tab = page.locator('[data-frontier-output-tab="copy"]')
        move_click(page, copy_tab, post_hold=1.0)
        smooth_center(page, "#frontier-platform-kits", hold_after=4.0)
        mark("three_platform_kits_shown")

        inspect_buttons = page.locator("#frontier-platform-kits .frontier-platform-kit footer button")
        for index, platform_name in enumerate(("linkedin", "youtube", "google_search")):
            move_click(page, copy_tab, post_hold=0.7)
            smooth_center(page, "#frontier-platform-kits", hold_after=1.2)
            move_click(page, inspect_buttons.nth(index), post_hold=1.0)
            page.locator('#frontier-media-gallery [data-surface-focus="true"]').first.wait_for(
                state="visible"
            )
            smooth_center(page, "#frontier-media-gallery", hold_after=1.2)
            focused = page.locator('#frontier-media-gallery [data-surface-focus="true"]')
            video_locator = focused.locator("video")
            if video_locator.count():
                move_to(page, video_locator.first)
                video_locator.first.evaluate("node => { node.currentTime = 0; node.muted = true; }")
                video_locator.first.click()
                duration = (8.0, 12.0, 10.0)[index]
                mark(f"{platform_name}_film_playback_started")
                hold(page, min(duration, 6.0))
                video_locator.first.evaluate("node => node.pause()")
            mark(f"{platform_name}_assets_inspected")
            hold(page, 1.6)

        review_tab = page.locator('[data-frontier-output-tab="review"]')
        move_click(page, review_tab, post_hold=0.8)
        smooth_center(page, '[data-frontier-output-panel="review"]', hold_after=4.2)
        mark("quality_and_release_evidence_shown")

        page.keyboard.press("Home")
        hold(page, 2.5)
        mark("operation_capture_complete")
        target = RAW / "frontier-gtm-real-operation-1080p.webm"
        context.close()
        video.save_as(str(target))
        browser.close()

    receipt = {
        "schema": "FrontierGTMRealOperationCaptureV1",
        "source_url": URL,
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "continuous_browser_recording": True,
        "scripted_dom_clicks_are_real": True,
        "viewport": {"width": 1920, "height": 1080},
        "video_path": str(target),
        "duration_seconds": round(time.perf_counter() - started, 3),
        "events": events,
        "truth_boundary": (
            "This recording proves local browser operation and playback of the rendered campaign assets. "
            "It does not prove AMD Radeon execution; that evidence must be captured on the Radeon host."
        ),
    }
    (OUTPUT / "operation-capture-receipt.json").write_text(
        json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(receipt, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
