from __future__ import annotations

import json
from pathlib import Path

from playwright.sync_api import sync_playwright


ROOT = Path(__file__).resolve().parents[2]
OUTPUT = Path(__file__).resolve().parent / "captures"
URL = "http://127.0.0.1:8765/control/frontier-gtm?ui=v11-six-master&film-capture=v1"


def capture(page, name: str) -> dict:
    target = OUTPUT / f"{name}.png"
    page.wait_for_timeout(180)
    page.screenshot(path=str(target), full_page=False)
    return {
        "name": name,
        "path": str(target),
        "scroll_y": page.evaluate("window.scrollY"),
        "width": 3840,
        "height": 2160,
    }


def center(page, selector: str) -> None:
    page.locator(selector).scroll_into_view_if_needed()
    page.evaluate(
        """selector => {
          const node = document.querySelector(selector);
          const rect = node.getBoundingClientRect();
          const target = window.scrollY + rect.top - Math.max(20, (window.innerHeight - rect.height) / 2);
          window.scrollTo({top: Math.max(0, target), behavior: 'instant'});
        }""",
        selector,
    )


def main() -> None:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    records: list[dict] = []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        context = browser.new_context(
            viewport={"width": 1920, "height": 1080},
            device_scale_factor=2,
            color_scheme="light",
            reduced_motion="no-preference",
        )
        page = context.new_page()
        page.goto(URL, wait_until="networkidle")
        records.append(capture(page, "01-studio-entry-4k"))

        page.locator('[data-frontier-recipe="technical-proof"]').click()
        page.locator("#frontier-gtm-result").wait_for(state="visible", timeout=90_000)
        page.locator("#frontier-media-gallery img").first.wait_for(state="visible", timeout=90_000)
        page.wait_for_function(
            """() => {
              const videos = [...document.querySelectorAll('#frontier-media-gallery video')];
              return videos.length === 3 && videos.every(v => v.readyState >= 1 && v.duration >= 8);
            }""",
            timeout=90_000,
        )

        page.locator('[data-frontier-output-tab="overview"]').click()
        center(page, "#frontier-gtm-result")
        records.append(capture(page, "02-agent-council-overview-4k"))

        page.locator('[data-frontier-output-tab="copy"]').click()
        center(page, "#frontier-platform-kits")
        records.append(capture(page, "03-platform-kits-4k"))

        buttons = page.locator("#frontier-platform-kits .frontier-platform-kit footer button")
        for index, label in enumerate(("linkedin", "youtube", "search")):
            page.locator('[data-frontier-output-tab="copy"]').click()
            buttons.nth(index).click()
            page.locator('#frontier-media-gallery [data-surface-focus="true"]').first.wait_for(
                state="visible"
            )
            center(page, "#frontier-media-gallery")
            video = page.locator('#frontier-media-gallery [data-surface-focus="true"] video')
            if video.count():
                video.first.evaluate(
                    """async (node, seconds) => {
                      node.pause();
                      node.currentTime = Math.min(seconds, Math.max(0, node.duration - 0.2));
                      await new Promise(resolve => node.addEventListener('seeked', resolve, {once: true}));
                    }""",
                    1.1 + index * 0.45,
                )
            records.append(capture(page, f"0{4 + index}-{label}-assets-4k"))

        page.locator('[data-frontier-output-tab="review"]').click()
        center(page, '[data-frontier-output-panel="review"]')
        records.append(capture(page, "07-release-evidence-4k"))

        payload = page.evaluate(
            "JSON.parse(document.querySelector('#frontier-run-json').textContent)"
        )
        media = payload["rendered_media"]
        assets = media["assets"]
        films = [row for row in assets if row["media_type"] == "video/mp4"]
        receipt = {
            "schema": "FrontierGTMFilmCaptureV1",
            "source_url": URL,
            "capture_count": len(records),
            "captures": records,
            "product_run_schema": payload["schema"],
            "product_run_id": payload.get("run_id") or payload.get("campaign_id") or "idempotent-local-run",
            "asset_count": len(assets),
            "image_count": sum(row["media_type"] == "image/png" for row in assets),
            "film_count": len(films),
            "video_shot_count": media["total_rendered_video_shots"],
            "unique_video_shot_source_count": len(
                {source for film in films for source in film["shot_source_ids"]}
            ),
            "platform_asset_exclusivity": media["platform_asset_exclusivity"],
        }
        (OUTPUT / "capture-receipt.json").write_text(
            json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        context.close()
        browser.close()

    print(json.dumps(receipt, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
