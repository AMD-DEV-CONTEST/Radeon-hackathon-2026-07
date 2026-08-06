"""Record a multi-shot demo tour of MeshSmith (3-5 min), not a single long run.

A judge watching one standard-quality generation mostly watches a progress bar. This
walks the whole story instead: device banner -> text-to-3D (draft, fast) -> orbit the
result -> printability report + stage timings -> image-to-3D path -> downloads.

    python scripts/record_tour.py --url http://127.0.0.1:7860
Output: demo_recordings/<id>.webm  ->  ffmpeg -i in.webm -c:v libx264 out.mp4
"""
import argparse
import time
from pathlib import Path


def slow_type(page, selector_locator, text, delay=45):
    selector_locator.click()
    selector_locator.type(text, delay=delay)


def orbit(page, seconds=6.0):
    """Drag-orbit whatever 3D canvas is on screen."""
    canvas = page.locator("canvas").last
    bb = canvas.bounding_box()
    if not bb:
        time.sleep(seconds)
        return
    cx, cy = bb["x"] + bb["width"] / 2, bb["y"] + bb["height"] / 2
    deadline = time.time() + seconds
    direction = 1
    while time.time() < deadline:
        page.mouse.move(cx, cy)
        page.mouse.down()
        for step in range(18):
            page.mouse.move(cx + direction * 16 * (step + 1), cy - step * 1.5, steps=1)
            time.sleep(0.025)
        page.mouse.up()
        direction *= -1
        time.sleep(0.4)


def run_generation(page, prompt, quality, timeout_min, image_path=None):
    """Start a run and wait for it to ACTUALLY finish.

    Waiting on "Printability" is wrong for any run after the first: that text is
    already on screen from the previous result, so the wait returns instantly and
    the recording ends mid-generation. Track the progress indicator instead —
    wait for it to appear (run started) and then disappear (run finished).
    """
    if image_path:
        page.locator("input[type='file']").first.set_input_files(image_path)
        time.sleep(2.5)
    else:
        box = page.locator("textarea").first
        box.click()
        box.fill("")
        box.type(prompt, delay=42)
    time.sleep(1.0)

    # Completion is detected on the FILESYSTEM, not in the DOM. Matching Gradio's
    # progress text is fragile — the stage label changes as the run advances, so any
    # locator built from a fixed set of stage names goes "hidden" mid-run and the
    # recording stops while the pipeline is still working. A finished run is defined
    # by exactly one thing: a new outputs/<run>/report.md on disk.
    outputs = Path("outputs")
    before = {p.parent for p in outputs.glob("*/report.md")} if outputs.exists() else set()

    page.get_by_role("button", name="Forge it").click()

    deadline = time.time() + timeout_min * 60
    while time.time() < deadline:
        now = {p.parent for p in outputs.glob("*/report.md")} if outputs.exists() else set()
        if now - before:
            break
        time.sleep(2)
    else:
        raise TimeoutError("run did not produce a report within the timeout")

    # let the UI paint the finished result before the camera moves on
    page.wait_for_selector("text=Printability", timeout=60_000)
    time.sleep(3.5)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://127.0.0.1:7860")
    ap.add_argument("--quality", default="draft")
    ap.add_argument("--timeout-min", type=int, default=15)
    ap.add_argument("--image", default="assets/examples/knight_concept.png")
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
        )
        page = ctx.new_page()

        # --- Shot 1: land on the app, let the device banner read ---
        page.goto(args.url, wait_until="networkidle")
        time.sleep(4)
        page.mouse.wheel(0, 120)
        time.sleep(2)
        page.mouse.wheel(0, -120)
        time.sleep(1.5)

        # pin the quality preset so the tour is reproducible and fast
        try:
            page.get_by_label("Quality", exact=False).first.click()
            page.get_by_role("option", name=args.quality, exact=True).click()
            time.sleep(1.2)
        except Exception as exc:
            print(f"could not set quality, using UI default: {exc}")

        # --- Shot 2: text -> 3D ---
        run_generation(page, "a low-poly fox figurine", args.quality, args.timeout_min)

        # --- Shot 3: orbit the finished asset ---
        orbit(page, seconds=8)

        # --- Shot 4: the printability report and stage timings ---
        page.mouse.wheel(0, 420)
        time.sleep(6)
        page.mouse.wheel(0, 360)
        time.sleep(6)
        page.mouse.wheel(0, -700)
        time.sleep(2)

        # --- Shot 5: the image -> 3D path, no prompt needed ---
        img = Path(args.image)
        if img.exists():
            try:
                run_generation(page, None, args.quality, args.timeout_min,
                               image_path=str(img.resolve()))
                orbit(page, seconds=6)
                page.mouse.wheel(0, 420)
                time.sleep(5)
            except Exception as exc:
                print(f"image path shot skipped: {exc}")

        time.sleep(3)
        video_path = page.video.path()
        ctx.close()
        browser.close()

    print(f"recorded: {video_path}")


if __name__ == "__main__":
    main()
