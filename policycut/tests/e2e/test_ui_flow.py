"""End-to-end UI test: drives the real PolicyCut web frontend with Playwright.

Covers the complete closed loop against a live server subprocess:

    home -> new project -> upload -> policy interpret/save -> analysis job
    -> processing page (SSE) -> review workspace (manual region + audio
    interval, toggles, keyboard, PATCH) -> complete review -> export page
    -> render job -> artifacts + audit stats.

Requires: playwright (chromium), ffmpeg/ffprobe on PATH. Skips cleanly when
playwright is not importable. A video of the run is recorded to
/tmp/policycut_e2e_video.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

import pytest

pytest.importorskip("playwright")

from playwright.sync_api import expect, sync_playwright  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / "tests" / "fixtures" / "interview.mp4"

HOST = "127.0.0.1"
PORT = 8017
BASE = f"http://{HOST}:{PORT}"
API = f"{BASE}/api/v1"
VIDEO_DIR = "/tmp/policycut_e2e_video"

# Console errors matching any of these substrings are expected and allowed:
# - favicon.ico is not shipped (every page 404s it)
# - the export page probes /artifacts/srt to hide the link when no subtitle
#   file was generated (no transcript locally), which logs a 404.
ALLOWED_CONSOLE_PATTERNS = ("favicon", "/artifacts/srt")


def _http(method: str, url: str) -> tuple[int, bytes]:
    req = urllib.request.Request(url, method=method)
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status, resp.read()
    except urllib.error.HTTPError as exc:  # noqa: PERF203
        return exc.code, exc.read()


@pytest.fixture(scope="module")
def server(tmp_path_factory):
    """Start the real app with ``run.py`` on a temp data dir; wait for health."""
    data_dir = tmp_path_factory.mktemp("pc_e2e_data")
    env = dict(os.environ)
    env["POLICYCUT_NO_LLM"] = "1"
    env.pop("POLICYCUT_REQUIRE_ROCM", None)
    log_path = tmp_path_factory.mktemp("pc_e2e_logs") / "server.log"
    log_fh = open(log_path, "wb")
    proc = subprocess.Popen(
        [
            sys.executable,
            "run.py",
            "--host",
            HOST,
            "--port",
            str(PORT),
            "--data-dir",
            str(data_dir),
        ],
        cwd=str(ROOT),
        env=env,
        stdout=log_fh,
        stderr=subprocess.STDOUT,
    )
    try:
        deadline = time.time() + 45
        last_err = None
        while time.time() < deadline:
            if proc.poll() is not None:
                break
            try:
                status, body = _http("GET", f"{API}/health")
                if status == 200 and b"ok" in body:
                    break
            except Exception as exc:  # noqa: BLE001
                last_err = exc
            time.sleep(0.3)
        else:
            proc.terminate()
            raise RuntimeError(
                f"server did not become healthy: {last_err}\n"
                f"--- server log ---\n{log_path.read_text(errors='replace')[-4000:]}"
            )
        if proc.poll() is not None:
            raise RuntimeError(
                "server exited early\n"
                f"--- server log ---\n{log_path.read_text(errors='replace')[-4000:]}"
            )
        yield BASE
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
        log_fh.close()


@pytest.fixture(scope="module")
def browser_page(server):
    """Headless chromium page (1440x900) with video recording + error capture."""
    shutil.rmtree(VIDEO_DIR, ignore_errors=True)
    console_errors: list[str] = []
    page_errors: list[str] = []
    responses_409: list[str] = []

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=["--autoplay-policy=no-user-gesture-required"],
        )
        context = browser.new_context(
            viewport={"width": 1440, "height": 900},
            record_video_dir=VIDEO_DIR,
        )
        page = context.new_page()

        def on_console(msg):
            if msg.type != "error":
                return
            loc = ""
            try:
                loc = (msg.location or {}).get("url", "")
            except Exception:  # noqa: BLE001
                pass
            entry = f"[{page.url}] {msg.text} (resource: {loc})"
            haystack = f"{msg.text} {loc}"
            if any(pat in haystack for pat in ALLOWED_CONSOLE_PATTERNS):
                return
            console_errors.append(entry)

        page.on("console", on_console)
        page.on("pageerror", lambda exc: page_errors.append(f"[{page.url}] {exc}"))
        page.on(
            "response",
            lambda resp: responses_409.append(f"{resp.request.method} {resp.url}")
            if resp.status == 409
            else None,
        )
        # Auto-accept any confirm() dialog (Complete Review guard, etc.).
        page.on("dialog", lambda dialog: dialog.accept())

        yield {
            "page": page,
            "console_errors": console_errors,
            "page_errors": page_errors,
            "responses_409": responses_409,
        }
        context.close()
        browser.close()


def _api_events(project_id: str) -> dict:
    status, body = _http("GET", f"{API}/projects/{project_id}/events")
    assert status == 200, f"GET events failed: {status}"
    return json.loads(body)


def _project_id_from_url(url: str) -> str:
    m = re.search(r"[?&]id=([^&]+)", url)
    assert m, f"no project id in url: {url}"
    return m.group(1)


def test_full_ui_flow(server, browser_page):
    page = browser_page["page"]
    try:
        _run_flow(page)
    except Exception:
        try:
            page.screenshot(path="/tmp/e2e_failure.png", full_page=True)
        except Exception:  # noqa: BLE001
            pass
        raise

    # ---- 7. no uncaught JS errors / unexpected console errors / 409s ----
    assert not browser_page["page_errors"], (
        "uncaught page errors:\n" + "\n".join(browser_page["page_errors"])
    )
    assert not browser_page["console_errors"], (
        "unexpected console errors:\n" + "\n".join(browser_page["console_errors"])
    )
    assert not browser_page["responses_409"], (
        "unexpected 409 responses:\n" + "\n".join(browser_page["responses_409"])
    )


def _run_flow(page):
    # ================= 1. Home page =================
    page.goto(BASE + "/")
    expect(page.locator(".badge-local")).to_be_visible()
    expect(page.locator("#gpu-chip")).to_be_visible()
    # system info resolved (chip no longer in its initial "Detecting" state)
    expect(page.locator("#gpu-chip")).not_to_contain_text("Detecting", timeout=15000)
    expect(page.locator("#rocm-chip")).to_be_visible()

    page.click("#btn-new")
    expect(page.locator("#modal-new")).to_be_visible()
    page.fill("#new-name", "E2E Demo")
    page.click("#new-create")
    page.wait_for_url("**/project.html?id=*", timeout=15000)
    project_id = _project_id_from_url(page.url)

    # ================= 2. Upload source =================
    expect(page.locator("#proj-name")).to_have_text("E2E Demo")
    page.set_input_files("#file-input", str(FIXTURE))
    expect(page.locator("#media-section")).to_be_visible(timeout=30000)
    media_table = page.locator("#media-table")
    expect(media_table).to_contain_text("interview.mp4")
    expect(media_table).to_contain_text("00:10.000")  # duration 10s
    expect(media_table).to_contain_text("640 × 360")  # resolution
    audio_cell = page.locator("#media-table tr", has_text="Audio").locator("td").nth(1)
    assert audio_cell.inner_text().strip().lower() not in ("none", "", "—"), (
        "media table should report an audio track"
    )

    # ================= 3. Policy: interpret / save / analyze =================
    policy_text = page.input_value("#policy-text")
    assert "Pixelate every face" in policy_text, "default example policy expected"
    page.click("#btn-interpret")
    expect(page.locator("#rules-section")).to_be_visible(timeout=15000)
    expect(page.locator("#parse-source")).to_have_text("Keyword fallback")
    expect(page.locator("#rules-visual .rule-row")).to_have_count(4)
    expect(page.locator("#rules-audio .rule-row")).to_have_count(3)

    page.click("#btn-save-policy")
    expect(page.locator("#policy-saved")).to_have_text("Saved", timeout=15000)

    expect(page.locator("#btn-analyze")).to_be_enabled()
    page.click("#btn-analyze")
    page.wait_for_url("**/processing.html*", timeout=20000)

    # ================= 4. Processing page =================
    expect(page.locator("#stage-list li")).to_have_count(8)
    # Analysis finishes locally in a few seconds (models unavailable -> zero
    # auto events is expected); page then redirects to the review workspace.
    page.wait_for_url("**/review.html*", timeout=120000)

    # ================= 5. Review workspace =================
    expect(page.locator("#proj-name")).to_have_text("E2E Demo", timeout=15000)
    # zero auto events -> empty state in the list
    expect(page.locator("#event-list")).to_contain_text("No events")
    expect(page.locator("#pending-badge")).to_have_text("0")

    # video (overlay preview falls back to normalized) becomes ready
    page.wait_for_function(
        "() => { const v = document.querySelector('#video'); return !!v && v.readyState >= 1; }",
        timeout=30000,
    )

    # ---- Overlay / Original toggle ----
    src0 = page.evaluate("document.querySelector('#video').getAttribute('src')")
    assert "/preview/overlay" in src0, f"initial video src should be overlay: {src0}"
    page.click("#t-toggle-src")
    page.wait_for_function(
        "() => (document.querySelector('#video').getAttribute('src') || '').includes('/preview/original')",
        timeout=15000,
    )
    expect(page.locator("#t-toggle-src")).to_have_text("Original")
    page.click("#t-toggle-src")
    page.wait_for_function(
        "() => (document.querySelector('#video').getAttribute('src') || '').includes('/preview/overlay')",
        timeout=15000,
    )
    expect(page.locator("#t-toggle-src")).to_have_text("Overlay")
    page.wait_for_function(
        "() => document.querySelector('#video').readyState >= 1", timeout=30000
    )

    # ---- keyboard: space toggles play/pause ----
    page.evaluate("document.activeElement && document.activeElement.blur()")
    assert page.evaluate("document.querySelector('#video').paused") is True
    page.keyboard.press("Space")
    page.wait_for_function(
        "() => !document.querySelector('#video').paused", timeout=10000
    )
    page.keyboard.press("Space")
    page.wait_for_function(
        "() => document.querySelector('#video').paused", timeout=10000
    )

    # ---- manual visual region: enter add mode, drag a rect on the canvas ----
    page.click("#t-add-region")
    expect(page.locator("#t-add-region")).to_have_class(re.compile(r"\bactive\b"))
    canvas_box = page.locator("#overlay-canvas").bounding_box()
    assert canvas_box and canvas_box["width"] > 200 and canvas_box["height"] > 200
    cx = canvas_box["x"] + canvas_box["width"] / 2
    cy = canvas_box["y"] + canvas_box["height"] / 2
    page.mouse.move(cx - 120, cy - 70)
    page.mouse.down()
    page.mouse.move(cx - 40, cy - 10, steps=6)
    page.mouse.move(cx + 60, cy + 60, steps=6)
    page.mouse.up()
    expect(page.locator("#region-form")).to_be_visible()
    page.select_option("#rf-category", "manual")
    page.select_option("#rf-effect", "solid")
    page.click("#rf-add")
    expect(page.locator("#event-list .event-row")).to_have_count(1, timeout=15000)
    # new event is auto-selected; property panel flags the fixed region
    expect(page.locator("#prop-body")).to_contain_text("Manual fixed region")
    assert page.locator("#p-action").input_value() == "solid"
    expect(page.locator("#event-list .event-row").first).to_contain_text("(manual)")

    # ---- manual audio interval ----
    page.click("#t-add-audio")
    expect(page.locator("#event-list .event-row")).to_have_count(2, timeout=15000)
    expect(page.locator("#event-list .status-dot.confirmed")).to_have_count(2)

    # both events reach the server
    project_id = _project_id_from_url(page.url)
    data = _api_events(project_id)
    kinds = sorted(e["kind"] for e in data["events"])
    assert kinds == ["audio", "visual"], f"server events mismatch: {kinds}"
    assert all(e["status"] == "confirmed" for e in data["events"])
    assert all(e["source"] == "manual" for e in data["events"])
    visual_ev = next(e for e in data["events"] if e["kind"] == "visual")
    assert visual_ev["manual_fixed_region"] is True
    assert visual_ev["action"]["type"] == "solid"

    # ---- both events render on the timeline canvas (confirmed = green) ----
    green_px = page.evaluate(
        """() => {
          const c = document.querySelector('#timeline-canvas');
          const ctx = c.getContext('2d');
          const d = ctx.getImageData(0, 0, c.width, c.height).data;
          let n = 0;
          for (let i = 0; i < d.length; i += 4) {
            if (d[i + 3] > 60 && d[i + 1] > 120 && d[i] < 110 && d[i + 2] < 110) n++;
          }
          return n;
        }"""
    )
    assert green_px > 0, "expected confirmed (green) event bars on the timeline canvas"

    # ---- PATCH end_s via the property panel (no 409) ----
    page.locator("#event-list .event-row").first.click()
    expect(page.locator("#prop-body")).to_be_visible()
    selected_id = page.evaluate("selectedId")
    page.fill("#p-end", "2.5")
    page.wait_for_timeout(150)  # debounce kicks the save-state to "Saving…"
    expect(page.locator("#save-state")).to_have_text("Saved", timeout=15000)
    data = _api_events(project_id)
    patched = next(e for e in data["events"] if e["id"] == selected_id)
    assert abs(patched["end_s"] - 2.5) < 1e-6, f"end_s not persisted: {patched['end_s']}"

    # ---- Confirm All Remaining: no-op with zero pending ----
    page.click("#btn-confirm-all")
    expect(page.locator(".toast").last).to_contain_text("Confirmed 0 events", timeout=15000)
    expect(page.locator("#btn-confirm-all")).to_be_enabled()

    # ---- Complete Review -> export page ----
    page.click("#btn-complete")
    page.wait_for_url("**/export.html*", timeout=20000)

    # ================= 6. Export page =================
    expect(page.locator("#proj-name")).to_have_text("E2E Demo", timeout=15000)

    def tile_value(label: str) -> str:
        tile = page.locator("#summary-tiles .stat-tile", has_text=label)
        return tile.locator(".v").inner_text().strip()

    expect(page.locator("#summary-tiles .stat-tile")).to_have_count(6)
    assert tile_value("Confirmed") == "2"
    assert tile_value("Manual") == "2"
    assert tile_value("Pending") == "0"
    expect(page.locator("#pending-banner")).to_be_hidden()
    expect(page.locator("#btn-render")).to_be_enabled()

    page.click("#btn-render")
    expect(page.locator("#results")).to_be_visible(timeout=180000)

    # result video wired up
    result_src = page.evaluate(
        "document.querySelector('#result-video').getAttribute('src') || ''"
    )
    assert "/artifacts/video" in result_src, f"result video src: {result_src}"

    # download links present and live (video / audit / zip)
    for link_id, kind in (("#dl-video", "video"), ("#dl-audit", "audit"), ("#dl-zip", "zip")):
        link = page.locator(link_id)
        expect(link).to_be_visible()
        href = link.get_attribute("href") or ""
        assert f"/artifacts/{kind}" in href, f"{link_id} href: {href}"
        status, _ = _http("GET", f"{API}/projects/{project_id}/artifacts/{kind}")
        assert status == 200, f"artifact {kind} not downloadable: {status}"

    # SRT: no transcript locally, so the artifact may be absent — the page
    # must handle that gracefully (hide the link rather than 404 on click).
    srt_status, _ = _http("GET", f"{API}/projects/{project_id}/artifacts/srt")
    srt_link = page.locator("#dl-srt")
    if srt_status == 200:
        expect(srt_link).to_be_visible()
    else:
        expect(srt_link).to_be_hidden()

    # stats panel: SHA-256 of input and output from audit.json
    hash_text = page.locator("#hash-table").inner_text()
    hashes = re.findall(r"\b[0-9a-f]{64}\b", hash_text)
    assert len(hashes) >= 2, f"expected input+output SHA-256 in stats panel:\n{hash_text}"
    expect(page.locator("#hash-table")).to_contain_text("Input SHA-256")
    expect(page.locator("#hash-table")).to_contain_text("Output SHA-256")
    expect(page.locator("#perf-tiles .stat-tile")).to_have_count(4)

    # project reached its terminal state
    status, body = _http("GET", f"{API}/projects/{project_id}")
    assert status == 200
    assert json.loads(body)["status"] == "complete"
