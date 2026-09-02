#!/usr/bin/env python3
"""Record the PolicyCut demo walkthrough with Playwright (scene-per-file).

Drives the real UI end to end at a deliberate, watchable pace and records
each scene to its own WebM under --out. Works against any running PolicyCut
instance (local CPU dev box or the Radeon server through an SSH port
forward) — the UI itself displays which GPU the backend is using.

Scenes:
  01_home      Projects page, system bar (GPU chip), create/open project
  02_upload    Upload video, media info, type + interpret + save policy
  03_analysis  Processing page: stages with live metrics
  04_review    Review workspace: browse events, ignore the low-confidence
               false positive, add a manual region, confirm the rest
  05_export    Render, final video, downloads, audit stats

Modes:
  Fresh run (default): creates a new project, uploads --video, saves the
  policy and runs a real analysis job.

  Seeded run (--project-id): reuses an existing project (e.g. one prepared
  by ops/seed_demo.py) WITHOUT re-running analysis, so curated events are
  preserved. Scene 01 opens the existing project card, scene 02 shows the
  policy round-trip on the saved text, and scene 03 replays the COMPLETED
  analysis job's stages/metrics on the processing page (pass --analysis-job;
  without it scene 03 is skipped gracefully).

Usage:
  python scripts/record_demo.py --base http://127.0.0.1:8000 \
      --video tests/fixtures/interview.mp4 --out /tmp/demo_scenes \
      [--policy "..."] [--max-analysis-s 900] \
      [--project-id p_xxx --analysis-job j_xxx --replay-s 24]
"""
from __future__ import annotations

import argparse
import contextlib
import json
import sys
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from playwright.sync_api import sync_playwright, Page, expect

VIEW = {"width": 1920, "height": 1080}

DEFAULT_POLICY = ("Pixelate every face, license plate, identity document and screen. "
                  "Beep phone numbers, email addresses and street addresses.")

# Replay schedule for the seeded scene 03: (stage, slice, p0, p1, message).
REPLAY_STAGES = [
    ("NORMALIZING", 0.08, 0.02, 0.10, "Normalizing video"),
    ("PARSING_POLICY", 0.05, 0.11, 0.13, "Validating saved policy"),
    ("TRANSCRIBING", 0.17, 0.15, 0.33, "Transcribing audio (Whisper)"),
    ("DETECTING_PII", 0.08, 0.34, 0.38, "Scanning transcript for PII"),
    ("DETECTING_VISUAL", 0.22, 0.40, 0.62, "Detecting visual targets (GroundingDINO + YuNet)"),
    ("TRACKING", 0.20, 0.64, 0.85, "Tracking objects (SAM 2.1)"),
    ("BUILDING_PREVIEW", 0.14, 0.88, 0.97, "Building review preview"),
    ("REVIEW_READY", 0.06, 0.99, 1.0, "Finalizing"),
]


def wait_health(base: str, timeout_s: float = 30) -> None:
    end = time.time() + timeout_s
    while time.time() < end:
        with contextlib.suppress(Exception):
            with urllib.request.urlopen(f"{base}/api/v1/health", timeout=3) as r:
                if r.status == 200:
                    return
        time.sleep(0.5)
    raise RuntimeError(f"backend not reachable at {base}")


def api_get(base: str, path: str):
    with urllib.request.urlopen(f"{base}/api/v1{path}", timeout=30) as r:
        return json.loads(r.read())


def pause(page: Page, s: float) -> None:
    page.wait_for_timeout(int(s * 1000))


def click_first_visible(page: Page, *selectors: str) -> bool:
    for sel in selectors:
        loc = page.locator(sel)
        for i in range(loc.count()):
            item = loc.nth(i)
            if item.is_visible():
                item.click()
                return True
    return False


class Demo:
    def __init__(self, base: str, out: Path, video: Path, policy: str,
                 max_analysis_s: int, project_id: str | None = None,
                 analysis_job: str | None = None, replay_s: float = 24.0):
        self.base = base
        self.out = out
        self.video = video
        self.policy = policy
        self.max_analysis_s = max_analysis_s
        self.project_id = project_id
        self.seeded = project_id is not None
        self.analysis_job = analysis_job
        self.replay_s = max(8.0, replay_s)

    # -- scene infra -------------------------------------------------------
    def scene(self, browser, name: str):
        ctx = browser.new_context(viewport=VIEW,
                                  record_video_dir=str(self.out / name),
                                  record_video_size=VIEW)
        page = ctx.new_page()
        page.set_default_timeout(30_000)
        page.on("dialog", lambda d: d.accept("Campus interview — privacy cut"))
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

        if self.seeded:
            # open the already-seeded project card
            card = page.locator(f".project-card[data-id='{self.project_id}']")
            card.first.scroll_into_view_if_needed()
            card.first.hover()
            pause(page, 1.5)
            card.locator(".act-open").first.click()
            with contextlib.suppress(Exception):
                page.wait_for_url("**/*.html*", timeout=15_000)
            pause(page, 1.5)
            self.finish(ctx, page)
            return

        # fresh mode: create project via UI
        for sel in ("#btn-new", "#btn-new-project", "button:has-text('New Project')"):
            if page.locator(sel).count():
                page.locator(sel).first.click()
                break
        # modal path (if the app uses its own modal instead of window.prompt)
        with contextlib.suppress(Exception):
            inp = page.wait_for_selector("#new-name, #new-project-name, .modal input[type=text]",
                                         timeout=4000)
            inp.fill("Campus interview — privacy cut")
            pause(page, 1.0)
            page.locator("#new-create, .modal button.primary, .modal button:has-text('Create')").first.click()
        page.wait_for_url("**/project.html*", timeout=15_000)
        self.project_id = page.url.split("id=")[1].split("&")[0]
        pause(page, 1.5)
        self.finish(ctx, page)

    def s02_upload_policy(self, browser) -> None:
        ctx, page = self.scene(browser, "02_upload")
        page.goto(f"{self.base}/project.html?id={self.project_id}")
        pause(page, 1.5)
        if not self.seeded:
            page.set_input_files("input[type=file]", str(self.video))
        # media table appears after upload+probe (or immediately when seeded)
        try:
            page.wait_for_selector("#media-table tr", timeout=60_000)
        except Exception:
            page.wait_for_selector("text=/Resolution|1080|640/i", timeout=60_000)
        pause(page, 3.0)
        ta = page.locator("#policy-text, textarea").first
        ta.click()
        ta.fill("")
        ta.type(self.policy, delay=28)        # visible typing
        pause(page, 1.2)
        page.locator("#btn-interpret, button:has-text('Interpret')").first.click()
        try:
            page.wait_for_selector("#rules-section", timeout=120_000)
        except Exception:
            page.wait_for_selector("text=/face/i", timeout=120_000)
        pause(page, 5.0)                      # viewer reads the parsed rules
        click_first_visible(page, "#btn-save-policy", "button:has-text('Save Policy')")
        pause(page, 2.0)
        self.finish(ctx, page)

    # ---- scene 03: fresh (real job) --------------------------------------
    def _s03_fresh(self, browser) -> None:
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

    # ---- scene 03: seeded (replay the completed job's stages) ------------
    def _flatten_metrics(self, raw: dict) -> dict:
        flat = {}
        for stage, entry in (raw or {}).items():
            if isinstance(entry, dict) and isinstance(entry.get(stage), dict):
                entry = entry[stage]
            if isinstance(entry, dict):
                flat[stage] = entry
        return flat

    def _s03_replay(self, browser) -> None:
        jid = self.analysis_job
        try:
            job = api_get(self.base, f"/jobs/{jid}")
        except Exception as exc:
            print(f"[scene 03] cannot load job {jid}: {exc}; skipping", file=sys.stderr)
            return
        if job.get("status") != "done":
            print(f"[scene 03] job {jid} is {job.get('status')}, not done; skipping",
                  file=sys.stderr)
            return
        real_metrics = self._flatten_metrics(job.get("metrics") or {})
        try:
            n_events = len(api_get(
                self.base, f"/projects/{self.project_id}/events")["events"])
        except Exception:
            n_events = 0

        t0 = time.time()
        started_iso = datetime.now(timezone.utc).isoformat()

        def synth_state() -> dict:
            frac = min(1.0, (time.time() - t0) / self.replay_s)
            acc = 0.0
            stage_name, message, progress = REPLAY_STAGES[-1][0], "", 1.0
            done_stages: list[str] = []
            for name, width, p0, p1, msg in REPLAY_STAGES:
                if frac < acc + width:
                    inner = (frac - acc) / width
                    stage_name, message = name, msg
                    progress = p0 + (p1 - p0) * inner
                    break
                done_stages.append(name)
                acc += width
            else:
                stage_name, message, progress = "REVIEW_READY", "", 1.0
            finished = frac >= 1.0
            metrics = {}
            for name in done_stages:
                metrics[name] = real_metrics.get(name) or {
                    "wall_s": None, "peak_vram_mb": None,
                    "frames": None, "precision": None}
            state = {
                "id": jid, "project_id": self.project_id, "type": "analysis",
                "status": "done" if finished else "running",
                "stage": "REVIEW_READY" if finished else stage_name,
                "progress": 1.0 if finished else round(progress, 3),
                "message": (f"Analysis complete: {n_events} events ready for review"
                            if finished else message),
                "created_at": started_iso, "started_at": started_iso,
                "finished_at": datetime.now(timezone.utc).isoformat() if finished else None,
                "error": None,
                "metrics": (real_metrics or metrics) if finished else metrics,
            }
            return state

        ctx, page = self.scene(browser, "03_analysis")
        # SSE off -> the page falls back to 2s polling, which we intercept
        # and answer with the completed job's stages replayed over time.
        page.route(f"**/api/v1/jobs/{jid}/events", lambda route: route.abort())
        page.route(f"**/api/v1/jobs/{jid}",
                   lambda route: route.fulfill(
                       status=200, content_type="application/json",
                       body=json.dumps(synth_state())))
        page.goto(f"{self.base}/processing.html?id={self.project_id}&job={jid}")
        deadline = time.time() + self.replay_s + 30
        while time.time() < deadline:
            if page.url.split("/")[-1].startswith("review.html"):
                break
            pause(page, 1.0)
        pause(page, 1.5)
        self.finish(ctx, page)

    def s03_analysis(self, browser) -> None:
        if not self.seeded:
            self._s03_fresh(browser)
        elif self.analysis_job:
            self._s03_replay(browser)
        else:
            print("[scene 03] --project-id given without --analysis-job; "
                  "skipping (re-running analysis would wipe the seeded events)",
                  file=sys.stderr)

    def s04_review(self, browser) -> None:
        ctx, page = self.scene(browser, "04_review")
        page.goto(f"{self.base}/review.html?id={self.project_id}")
        page.wait_for_selector("video", timeout=30_000)
        pause(page, 3.0)
        # let the preview play a bit with overlay boxes
        with contextlib.suppress(Exception):
            page.locator("#t-play, button:has-text('▶')").first.click()
        pause(page, 4.0)
        with contextlib.suppress(Exception):
            page.locator("#t-play").first.click()   # pause playback
        pause(page, 1.0)

        rows = page.locator(".event-row, [data-event-id]")
        n = rows.count()
        # walk a few events so the panel + seek behaviour is on camera
        for i in range(min(n, 3)):
            rows.nth(i).click()
            pause(page, 2.2)

        # 1) ignore the low-confidence false positive (correction on camera)
        if n:
            clicked = click_first_visible(
                page, "#btn-lowest-conf", "#btn-lowest-conf2",
                "button:has-text('Jump to lowest confidence')")
            if not clicked:
                rows.first.click()
            pause(page, 2.0)
            click_first_visible(page, "#p-ignore", "button:has-text('Ignore')")
            pause(page, 2.2)

        # 2) add a manual fixed region (the human catches what the model missed)
        click_first_visible(page, "#t-add-region", "button:has-text('Add region')")
        pause(page, 1.0)
        canvas = page.locator("#overlay-canvas, canvas").first
        box = canvas.bounding_box()
        if box:
            x0 = box["x"] + box["width"] * 0.33
            y0 = box["y"] + box["height"] * 0.56
            page.mouse.move(x0, y0)
            page.mouse.down()
            steps = 22
            for k in range(1, steps + 1):
                page.mouse.move(x0 + box["width"] * 0.20 * k / steps,
                                y0 + box["height"] * 0.26 * k / steps)
                page.wait_for_timeout(28)
            page.mouse.up()
        pause(page, 1.2)
        # region form: solid fill, then confirm
        for sel in ("#rf-effect", "#manual-effect"):
            eff = page.locator(sel)
            if eff.count():
                with contextlib.suppress(Exception):
                    eff.first.select_option("solid")
                break
        pause(page, 0.8)
        click_first_visible(page, "#rf-add", ".region-form button.primary",
                            ".modal button.primary", "button:has-text('Create event')")
        pause(page, 2.5)

        # 3) confirm everything else
        click_first_visible(page, "#btn-confirm-all", "button:has-text('Confirm All')")
        pause(page, 2.5)

        # overlay/original toggle on camera (there and back)
        if click_first_visible(page, "#t-toggle-src", "button:has-text('Overlay')",
                               "#btn-toggle-overlay"):
            pause(page, 2.5)
            click_first_visible(page, "#t-toggle-src", "button:has-text('Original')")
            pause(page, 1.5)

        click_first_visible(page, "#btn-complete", "button:has-text('Complete Review')")
        page.wait_for_url("**/export.html*", timeout=15_000)
        pause(page, 1.5)
        self.finish(ctx, page)

    def s05_export(self, browser) -> None:
        ctx, page = self.scene(browser, "05_export")
        page.goto(f"{self.base}/export.html?id={self.project_id}")
        try:
            page.wait_for_selector("#btn-render", timeout=30_000)
        except Exception:
            page.wait_for_selector("button:has-text('Render redacted video')",
                                   timeout=30_000)
        pause(page, 3.0)                       # viewer reads the summary tiles
        click_first_visible(page, "#btn-render", "#btn-rerender",
                            "button:has-text('Render redacted video')")
        pause(page, 2.0)
        deadline = time.time() + self.max_analysis_s
        while time.time() < deadline:
            done = False
            # authoritative check: render finished and exports are fresh
            with contextlib.suppress(Exception):
                proj = api_get(self.base, f"/projects/{self.project_id}")
                done = (proj.get("status") == "complete"
                        and not proj.get("exports_stale"))
            with contextlib.suppress(Exception):
                if done and page.locator("#results").first.is_visible():
                    break
            pause(page, 2.0)
        pause(page, 2.0)
        # play the redacted result on camera
        with contextlib.suppress(Exception):
            page.locator("#result-video, video").first.scroll_into_view_if_needed()
            page.evaluate(
                "() => { const v = document.querySelector('#result-video')"
                " || document.querySelector('video'); if (v) { v.muted = false;"
                " v.play().catch(() => { v.muted = true; v.play().catch(()=>{}); }); } }")
        pause(page, 8.0)
        # linger on the verification / performance stats
        with contextlib.suppress(Exception):
            page.locator("#perf-tiles, #hash-table").first.scroll_into_view_if_needed()
        pause(page, 3.5)
        self.finish(ctx, page)

    def run(self, scenes: set[str] | None = None) -> int:
        self.out.mkdir(parents=True, exist_ok=True)
        wait_health(self.base)
        all_scenes = [("01", self.s01_home), ("02", self.s02_upload_policy),
                      ("03", self.s03_analysis), ("04", self.s04_review),
                      ("05", self.s05_export)]
        with sync_playwright() as p:
            browser = p.chromium.launch(
                args=["--autoplay-policy=no-user-gesture-required"])
            for num, fn in all_scenes:
                if scenes and num not in scenes:
                    continue
                fn(browser)
            browser.close()
        manifest = {"base": self.base, "project_id": self.project_id,
                    "mode": "seeded" if self.seeded else "fresh",
                    "analysis_job": self.analysis_job,
                    "video": str(self.video), "policy": self.policy,
                    "scenes": sorted(str(f) for f in self.out.rglob("*.webm"))}
        (self.out / "manifest.json").write_text(json.dumps(manifest, indent=2))
        print(json.dumps(manifest, indent=2))
        return 0


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Record the PolicyCut demo walkthrough as per-scene WebM files.")
    ap.add_argument("--base", default="http://127.0.0.1:8000")
    ap.add_argument("--video", default="tests/fixtures/interview.mp4")
    ap.add_argument("--out", default="/tmp/demo_scenes")
    ap.add_argument("--policy", default=DEFAULT_POLICY)
    ap.add_argument("--max-analysis-s", type=int, default=900)
    ap.add_argument("--project-id", default=None,
                    help="Reuse an existing (seeded) project instead of creating "
                         "one; skips upload and never re-runs analysis")
    ap.add_argument("--analysis-job", default=None,
                    help="With --project-id: id of the COMPLETED analysis job to "
                         "replay on the processing page for scene 03")
    ap.add_argument("--replay-s", type=float, default=24.0,
                    help="Seconds over which scene 03 replays the completed job")
    ap.add_argument("--scenes", default="all",
                    help="Comma list of scene numbers to record "
                         "(e.g. '04,05'); default: all")
    a = ap.parse_args()
    scenes = None
    if a.scenes and a.scenes.lower() != "all":
        scenes = {s.strip().zfill(2) for s in a.scenes.split(",") if s.strip()}
        if scenes - {"01", "02", "03", "04", "05"}:
            ap.error(f"unknown scenes: {sorted(scenes)}")
        if "01" not in scenes and not a.project_id:
            ap.error("--scenes without 01 requires --project-id")
    return Demo(a.base, Path(a.out), Path(a.video), a.policy, a.max_analysis_s,
                project_id=a.project_id, analysis_job=a.analysis_job,
                replay_s=a.replay_s).run(scenes)


if __name__ == "__main__":
    sys.exit(main())
