#!/usr/bin/env python3
"""Record the PolicyCut demo walkthrough with Playwright (scene-per-file).

Drives the real UI end to end at a deliberate, watchable pace and records
each scene to its own WebM under --out. Works against any running PolicyCut
instance (local CPU dev box or the Radeon server through an SSH port
forward) — the UI itself displays which GPU the backend is using.

Scenes:
  01_home      Projects page, system bar (GPU chip), create project
  02_upload    Upload video, media info, type + interpret + save policy
  03_analysis  Start analysis, processing stages with live GPU metrics
  04_review    Review workspace: browse events, toggle overlay, ignore a
               false positive, add a manual region, confirm the rest
  05_export    Render, final video, downloads, audit stats

Usage:
  python scripts/record_demo.py --base http://127.0.0.1:8000 \
      --video tests/fixtures/interview.mp4 --out /tmp/demo_scenes \
      [--policy "..."] [--max-analysis-s 900]
"""
from __future__ import annotations

import argparse
import contextlib
import json
import sys
import time
import urllib.request
from pathlib import Path

from playwright.sync_api import sync_playwright, Page, expect

VIEW = {"width": 1920, "height": 1080}

DEFAULT_POLICY = ("Pixelate every face, license plate, identity document and screen. "
                  "Beep phone numbers, email addresses and street addresses.")


def wait_health(base: str, timeout_s: float = 30) -> None:
    end = time.time() + timeout_s
    while time.time() < end:
        with contextlib.suppress(Exception):
            with urllib.request.urlopen(f"{base}/api/v1/health", timeout=3) as r:
                if r.status == 200:
                    return
        time.sleep(0.5)
    raise RuntimeError(f"backend not reachable at {base}")


def pause(page: Page, s: float) -> None:
    page.wait_for_timeout(int(s * 1000))


class Demo:
    def __init__(self, base: str, out: Path, video: Path, policy: str, max_analysis_s: int):
        self.base = base
        self.out = out
        self.video = video
        self.policy = policy
        self.max_analysis_s = max_analysis_s
        self.project_id: str | None = None

    # -- scene infra -------------------------------------------------------
    def scene(self, browser, name: str):
        ctx = browser.new_context(viewport=VIEW,
                                  record_video_dir=str(self.out / name),
                                  record_video_size=VIEW)
        page = ctx.new_page()
        page.set_default_timeout(30_000)
        return ctx, page

    def finish(self, ctx, page) -> None:
        with contextlib.suppress(Exception):
            page.close()
        with contextlib.suppress(Exception):
            ctx.close()

    # -- scenes ------------------------------------------------------------
    def s01_home(self, browser) -> None:
        ctx, page = self.scene(browser, "01_home")
        page.goto(self.base + "/")
        page.wait_for_selector(".system-bar, #system-bar, header", state="visible")
        pause(page, 3.5)                      # let the viewer read the system bar
        # create project via UI
        page.on("dialog", lambda d: d.accept("Campus interview — privacy cut"))
        for sel in ("#btn-new-project", "#new-project", "button:has-text('New Project')"):
            if page.locator(sel).count():
                page.locator(sel).first.click()
                break
        # modal path (if the app uses its own modal instead of window.prompt)
        with contextlib.suppress(Exception):
            inp = page.wait_for_selector("#new-project-name, .modal input[type=text]",
                                         timeout=4000)
            inp.fill("Campus interview — privacy cut")
            pause(page, 1.0)
            page.locator(".modal button.primary, .modal button:has-text('Create')").first.click()
        page.wait_for_url("**/project.html*", timeout=15_000)
        self.project_id = page.url.split("id=")[1].split("&")[0]
        pause(page, 1.5)
        self.finish(ctx, page)

    def s02_upload_policy(self, browser) -> None:
        ctx, page = self.scene(browser, "02_upload")
        page.goto(f"{self.base}/project.html?id={self.project_id}")
        pause(page, 1.5)
        page.set_input_files("input[type=file]", str(self.video))
        # media table appears after upload+probe
        page.wait_for_selector("text=/Resolution|1080|640/i", timeout=60_000)
        pause(page, 3.0)
        ta = page.locator("textarea").first
        ta.click()
        ta.fill("")
        ta.type(self.policy, delay=28)        # visible typing
        pause(page, 1.2)
        page.locator("button:has-text('Interpret')").first.click()
        page.wait_for_selector("text=/face/i", timeout=120_000)
        pause(page, 5.0)                      # viewer reads the parsed rules
        for sel in ("button:has-text('Save Policy')", "#btn-save-policy"):
            if page.locator(sel).count():
                page.locator(sel).first.click()
                pause(page, 1.0)
                break
        pause(page, 1.0)
        self.finish(ctx, page)

    def s03_analysis(self, browser) -> None:
        ctx, page = self.scene(browser, "03_analysis")
        page.goto(f"{self.base}/project.html?id={self.project_id}")
        page.wait_for_selector("button:has-text('Start Analysis')")
        pause(page, 1.0)
        page.locator("button:has-text('Start Analysis')").first.click()
        page.wait_for_url("**/processing.html*", timeout=15_000)
        # record the whole run; assembly may timelapse the middle
        deadline = time.time() + self.max_analysis_s
        while time.time() < deadline:
            if page.url.split("/")[-1].startswith("review.html"):
                break
            done = page.locator("text=/Review ready|REVIEW_READY|Analysis complete/i").count()
            if done:
                break
            pause(page, 2.0)
        pause(page, 2.0)
        self.finish(ctx, page)

    def s04_review(self, browser) -> None:
        ctx, page = self.scene(browser, "04_review")
        page.goto(f"{self.base}/review.html?id={self.project_id}")
        page.wait_for_selector("video", timeout=30_000)
        pause(page, 4.0)
        # let the preview play a bit with overlay boxes
        with contextlib.suppress(Exception):
            page.locator("video").first.click()
        pause(page, 4.0)

        rows = page.locator(".event-row, [data-event-id]")
        n = rows.count()
        # walk a few events so the panel + seek behaviour is on camera
        for i in range(min(n, 3)):
            rows.nth(i).click()
            pause(page, 2.2)

        # 1) ignore one event (false-positive correction on camera)
        if n:
            rows.first.click()
            pause(page, 1.2)
            for sel in ("button:has-text('Ignore')", "#btn-ignore"):
                if page.locator(sel).count():
                    page.locator(sel).first.click()
                    break
            pause(page, 2.0)

        # 2) add a manual fixed region (the human catches what the model missed)
        for sel in ("button:has-text('Add region')", "#btn-add-region"):
            if page.locator(sel).count():
                page.locator(sel).first.click()
                break
        pause(page, 1.0)
        canvas = page.locator("canvas").first
        box = canvas.bounding_box()
        if box:
            x0 = box["x"] + box["width"] * 0.62
            y0 = box["y"] + box["height"] * 0.18
            page.mouse.move(x0, y0)
            page.mouse.down()
            steps = 22
            for k in range(1, steps + 1):
                page.mouse.move(x0 + box["width"] * 0.22 * k / steps,
                                y0 + box["height"] * 0.30 * k / steps)
                page.wait_for_timeout(28)
            page.mouse.up()
        pause(page, 1.2)
        # dialog: keep defaults where possible, pick solid if present
        with contextlib.suppress(Exception):
            sel_eff = page.locator(".modal select, #manual-effect").first
            if sel_eff.count():
                with contextlib.suppress(Exception):
                    sel_eff.select_option("solid")
        for sel in (".modal button.primary", ".modal button:has-text('Add')",
                    "button:has-text('Create event')"):
            if page.locator(sel).count():
                page.locator(sel).first.click()
                break
        pause(page, 2.5)

        # 3) confirm everything else
        for sel in ("button:has-text('Confirm All')", "#btn-confirm-all"):
            if page.locator(sel).count():
                page.locator(sel).first.click()
                break
        pause(page, 2.0)
        # overlay/original toggle on camera
        for sel in ("button:has-text('Original')", "button:has-text('Overlay')", "#btn-toggle-overlay"):
            if page.locator(sel).count():
                page.locator(sel).first.click()
                pause(page, 2.5)
                break
        for sel in ("button:has-text('Complete Review')", "#btn-complete"):
            if page.locator(sel).count():
                page.locator(sel).first.click()
                break
        page.wait_for_url("**/export.html*", timeout=15_000)
        pause(page, 1.5)
        self.finish(ctx, page)

    def s05_export(self, browser) -> None:
        ctx, page = self.scene(browser, "05_export")
        page.goto(f"{self.base}/export.html?id={self.project_id}")
        page.wait_for_selector("button:has-text('Render')", timeout=30_000)
        pause(page, 3.0)
        page.locator("button:has-text('Render')").first.click()
        deadline = time.time() + self.max_analysis_s
        while time.time() < deadline:
            if page.locator("video").count() and page.locator(
                    "a:has-text('audit'), a[href*='artifacts/audit']").count():
                break
            pause(page, 2.0)
        pause(page, 2.0)
        # play the redacted result on camera
        with contextlib.suppress(Exception):
            page.locator("video").first.scroll_into_view_if_needed()
            page.locator("video").first.click()
        pause(page, 8.0)
        pause(page, 3.0)                       # linger on stats/downloads
        self.finish(ctx, page)

    def run(self) -> int:
        self.out.mkdir(parents=True, exist_ok=True)
        wait_health(self.base)
        with sync_playwright() as p:
            browser = p.chromium.launch()
            self.s01_home(browser)
            self.s02_upload_policy(browser)
            self.s03_analysis(browser)
            self.s04_review(browser)
            self.s05_export(browser)
            browser.close()
        manifest = {"base": self.base, "project_id": self.project_id,
                    "video": str(self.video), "policy": self.policy,
                    "scenes": sorted(str(f) for f in self.out.rglob("*.webm"))}
        (self.out / "manifest.json").write_text(json.dumps(manifest, indent=2))
        print(json.dumps(manifest, indent=2))
        return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8000")
    ap.add_argument("--video", default="tests/fixtures/interview.mp4")
    ap.add_argument("--out", default="/tmp/demo_scenes")
    ap.add_argument("--policy", default=DEFAULT_POLICY)
    ap.add_argument("--max-analysis-s", type=int, default=900)
    a = ap.parse_args()
    return Demo(a.base, Path(a.out), Path(a.video), a.policy, a.max_analysis_s).run()


if __name__ == "__main__":
    sys.exit(main())
