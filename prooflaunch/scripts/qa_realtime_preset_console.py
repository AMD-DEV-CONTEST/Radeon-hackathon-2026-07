from __future__ import annotations

import json
from pathlib import Path

from playwright.sync_api import Page, sync_playwright


ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / "evidence/v10"
VIEWPORTS = {
    "desktop": {"width": 1440, "height": 1600},
    "tablet": {"width": 1024, "height": 1366},
    "mobile": {"width": 390, "height": 844},
}


def run_surface(page: Page, label: str, errors: list[str]) -> tuple[dict, dict]:
    page.goto(
        f"http://127.0.0.1:8765/control/frontier-gtm?ui=v11-six-master&viewport={label}",
        wait_until="networkidle",
    )
    page.locator('[data-frontier-recipe="technical-proof"]').click()
    page.locator("#frontier-gtm-result").wait_for(state="visible", timeout=75_000)
    page.locator("#frontier-media-gallery img").first.wait_for(state="visible", timeout=75_000)
    page.wait_for_function(
        """() => {
          const videos = [...document.querySelectorAll('#frontier-media-gallery video')];
          return videos.length === 3 && videos.every(video => video.readyState >= 1 && Number.isFinite(video.duration) && video.duration >= 8);
        }""",
        timeout=75_000,
    )
    run_payload = page.evaluate(
        "JSON.parse(document.querySelector('#frontier-run-json').textContent)"
    )

    for tab in ("overview", "copy", "assets", "review"):
        page.locator(f'[data-frontier-output-tab="{tab}"]').click()
        if page.locator(f'[data-frontier-output-panel="{tab}"]').is_hidden():
            errors.append(f"{label}: result tab {tab} did not reveal its panel")

    page.locator('[data-frontier-output-tab="copy"]').click()
    page.locator("#frontier-platform-kits .frontier-platform-kit").first.wait_for(state="visible")
    page.locator("#frontier-gtm-result").scroll_into_view_if_needed()
    page.wait_for_timeout(250)
    platform_shot = EVIDENCE / f"operator-console-v11-platform-kits-{label}-{VIEWPORTS[label]['width']}x{VIEWPORTS[label]['height']}.png"
    page.screenshot(path=str(platform_shot), full_page=False)

    page.locator("#frontier-platform-kits .frontier-platform-kit footer button").first.click()
    page.locator("#frontier-media-gallery video").first.evaluate(
        """async video => { await video.play(); await new Promise(resolve => setTimeout(resolve, 350)); video.pause(); }"""
    )
    asset_shot = EVIDENCE / f"operator-console-v11-assets-{label}-{VIEWPORTS[label]['width']}x{VIEWPORTS[label]['height']}.png"
    page.screenshot(path=str(asset_shot), full_page=False)

    observation = {
        "viewport": VIEWPORTS[label],
        "flow_steps": page.locator("[data-frontier-flow-step]").count(),
        "result_buttons": page.locator("[data-frontier-output-tab]").count(),
        "platform_kits": page.locator("#frontier-platform-kits .frontier-platform-kit").count(),
        "platform_kit_modules": page.locator("#frontier-platform-kits .frontier-platform-kit__delivery > section").count(),
        "platform_kit_surfaces": page.locator("#frontier-platform-kits .frontier-platform-kit").evaluate_all("nodes => nodes.map(node => node.dataset.surfaceId)"),
        "focused_surface_assets": page.locator('#frontier-media-gallery [data-surface-focus="true"]').count(),
        "rendered_assets": page.locator("#frontier-media-gallery figure").count(),
        "image_assets": page.locator("#frontier-media-gallery img").count(),
        "video_assets": page.locator("#frontier-media-gallery video").count(),
        "video_metadata_ready": page.locator("#frontier-media-gallery video").evaluate_all(
            "nodes => nodes.map(node => ({readyState: node.readyState, duration: node.duration, width: node.videoWidth, height: node.videoHeight}))"
        ),
        "deprecated_quality_label_visible": "4A" in page.locator("body").inner_text(),
        "horizontal_overflow": page.evaluate(
            "document.documentElement.scrollWidth > document.documentElement.clientWidth + 1"
        ),
        "media_boundary": page.locator("#frontier-media-boundary").text_content(),
    }
    if observation["flow_steps"] != 6 or observation["result_buttons"] != 4:
        errors.append(f"{label}: incomplete controls {observation}")
    if observation["platform_kits"] != 3 or observation["platform_kit_modules"] != 9:
        errors.append(f"{label}: incomplete platform kits")
    if len(set(observation["platform_kit_surfaces"])) != 3:
        errors.append(f"{label}: platform surfaces are not exclusive")
    if observation["focused_surface_assets"] != 2:
        errors.append(f"{label}: platform-to-assets jump did not focus image and film")
    if (observation["rendered_assets"], observation["image_assets"], observation["video_assets"]) != (6, 3, 3):
        errors.append(f"{label}: expected 3 images and 3 films")
    if any(row["readyState"] < 1 or row["duration"] < 8 or row["width"] <= 0 or row["height"] <= 0 for row in observation["video_metadata_ready"]):
        errors.append(f"{label}: video playback metadata is incomplete")
    if observation["deprecated_quality_label_visible"]:
        errors.append(f"{label}: deprecated quality label remains visible")
    if observation["horizontal_overflow"]:
        errors.append(f"{label}: horizontal overflow")
    if "3 image masters + 3 six-scene film storyboards" not in str(observation["media_boundary"]):
        errors.append(f"{label}: six-master disclosure missing")
    return run_payload, {"observation": observation, "screenshots": [str(platform_shot), str(asset_shot)]}


def validate_payload(payload: dict, errors: list[str]) -> dict:
    orchestration = payload["agent_orchestration"]
    media = payload["rendered_media"]
    assets = media["assets"]
    skill = orchestration["imagegen_skill_contract"]
    films = [row for row in assets if row["media_type"] == "video/mp4"]
    summary = {
        "schema": payload["schema"],
        "candidate_count": orchestration["candidate_blueprint_count"],
        "imagegen_visual_briefs": skill["placement_brief_count"],
        "unique_brief_hashes": len({row["brief_sha256"] for row in skill["placement_briefs"]}),
        "video_cuts": media["video_platform_cut_count"],
        "rendered_video_shots": media["total_rendered_video_shots"],
        "unique_shot_sources": len({source for film in films for source in film["shot_source_ids"]}),
        "unique_binary_hashes": len({row["content_sha256"] for row in assets}),
        "unique_copy_hashes": len({row["copy_payload_sha256"] for row in assets}),
        "exclusivity": media["platform_asset_exclusivity"],
    }
    if payload["schema"] != "ProofLaunchRealtimePresetCampaignV8":
        errors.append("payload: stale campaign schema")
    if summary["candidate_count"] != 12:
        errors.append("payload: creative design-space count missing")
    if (summary["imagegen_visual_briefs"], summary["unique_brief_hashes"]) != (6, 6):
        errors.append("payload: imagegen does not own six unique placements")
    if (summary["video_cuts"], summary["rendered_video_shots"], summary["unique_shot_sources"]) != (3, 18, 18):
        errors.append("payload: three six-scene films are incomplete")
    if (summary["unique_binary_hashes"], summary["unique_copy_hashes"]) != (6, 6):
        errors.append("payload: binary or copy reuse detected")
    exclusivity = summary["exclusivity"]
    if any(exclusivity.get(key) != 0 for key in (
        "cross_surface_binary_reuse_count", "cross_surface_copy_reuse_count",
        "same_surface_cross_modality_source_reuse_count", "final_asset_placement_reuse_count",
        "creative_source_reuse_count",
    )):
        errors.append("payload: no-reuse receipt failed")
    if (exclusivity.get("unique_placement_count"), exclusivity.get("unique_creative_source_count"), exclusivity.get("unique_video_shot_source_count")) != (6, 6, 18):
        errors.append("payload: exclusive source counters failed")
    return summary


def main() -> None:
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    errors: list[str] = []
    runs: dict[str, dict] = {}
    first_payload: dict | None = None
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        for label, viewport in VIEWPORTS.items():
            page = browser.new_page(viewport=viewport)
            page.on("pageerror", lambda error, label=label: errors.append(f"{label}:page:{error}"))
            page.on("console", lambda message, label=label: errors.append(f"{label}:console:{message.text}") if message.type == "error" else None)
            payload, run = run_surface(page, label, errors)
            if first_payload is None:
                first_payload = payload
            elif payload.get("envelope_sha256") != first_payload.get("envelope_sha256"):
                errors.append(f"{label}: idempotent cross-device result changed")
            runs[label] = run
            page.close()
        browser.close()
    payload_summary = validate_payload(first_payload or {}, errors)
    report = {
        "status": "failed" if errors else "passed",
        "payload": payload_summary,
        "devices": runs,
        "errors": errors,
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if errors:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
