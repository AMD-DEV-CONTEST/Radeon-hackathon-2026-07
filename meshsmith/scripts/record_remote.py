"""Record a demo of MeshSmith running on a REMOTE GPU (e.g. an AMD Radeon Cloud
instance exposed over a tunnel), captured from a local browser.

The Gradio banner is rendered server-side, so the video shows the *server's* GPU —
which is the point: the app under test is on Radeon even though the camera is here.

Completion is detected by watching the on-page summary text change, since the local
filesystem tells us nothing about a remote run.

    python scripts/record_remote.py --url https://<tunnel-host>/ --quality draft
"""
import argparse
import time
from pathlib import Path


def summary_text(page):
    try:
        el = page.locator("text=/Printability \\d+/").first
        return el.inner_text(timeout=2000) if el.count() else ""
    except Exception:
        return ""


def orbit(page, seconds=7.0):
    try:
        canvas = page.locator("canvas").last
        bb = canvas.bounding_box()
        if not bb:
            time.sleep(seconds)
            return
        cx, cy = bb["x"] + bb["width"] / 2, bb["y"] + bb["height"] / 2
        end, direction = time.time() + seconds, 1
        while time.time() < end:
            page.mouse.move(cx, cy)
            page.mouse.down()
            for s in range(18):
                page.mouse.move(cx + direction * 15 * (s + 1), cy - s, steps=1)
                time.sleep(0.025)
            page.mouse.up()
            direction *= -1
            time.sleep(0.4)
    except Exception:
        time.sleep(seconds)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", required=True)
    ap.add_argument("--prompt", default="a chess knight piece, ornate baroque style")
    ap.add_argument("--quality", default="draft")
    ap.add_argument("--timeout-min", type=int, default=25)
    ap.add_argument("--out", default="demo_recordings")
    args = ap.parse_args()

    from playwright.sync_api import sync_playwright

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as p:
        browser = p.chromium.launch()
        ctx = browser.new_context(
            viewport={"width": 1920, "height": 1080},
            record_video_dir=str(out_dir),
            record_video_size={"width": 1920, "height": 1080},
            ignore_https_errors=True,
        )
        page = ctx.new_page()
        page.set_default_timeout(60_000)

        # 1. land, let the AMD banner read on camera
        page.goto(args.url, wait_until="domcontentloaded")
        page.wait_for_selector("text=MeshSmith", timeout=90_000)
        time.sleep(5)

        # 2. quality preset
        try:
            page.get_by_label("Quality", exact=False).first.click()
            page.get_by_role("option", name=args.quality, exact=True).click()
            time.sleep(1.5)
        except Exception as exc:
            print("quality select skipped:", exc)

        # 3. type the prompt like a person
        box = page.locator("textarea").first
        box.click()
        box.fill("")
        box.type(args.prompt, delay=45)
        time.sleep(1.5)

        before = summary_text(page)
        page.get_by_role("button", name="Forge it").click()
        print("forging on the remote Radeon...")

        # 4. wait for the summary to CHANGE (remote: no local files to watch)
        deadline = time.time() + args.timeout_min * 60
        while time.time() < deadline:
            cur = summary_text(page)
            if cur and cur != before:
                print("done:", cur[:80])
                break
            time.sleep(3)
        else:
            print("WARNING: timed out waiting for the run to finish")
        time.sleep(3)

        # 5. show off the result
        orbit(page, seconds=8)
        page.mouse.wheel(0, 400)
        time.sleep(6)
        page.mouse.wheel(0, 350)
        time.sleep(6)
        page.mouse.wheel(0, -750)
        time.sleep(3)

        video = page.video.path()
        ctx.close()
        browser.close()
    print("recorded:", video)


if __name__ == "__main__":
    main()
