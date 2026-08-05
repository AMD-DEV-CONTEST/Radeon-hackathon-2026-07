"""Record a real browser session of the MeshSmith UI to video (no screen
recorder needed — Playwright drives Chromium and captures 1080p webm).
Designed for the Radeon Cloud box: run the app, then this script, and you get
demo footage of actual operation on the AMD GPU.

    pip install playwright && playwright install chromium
    python scripts/record_demo.py --url http://127.0.0.1:7860 \
        --prompt "a chess knight piece, ornate baroque style" --quality standard
Output: demo_recordings/<timestamp>.webm  (convert:  ffmpeg -i in.webm out.mp4)
"""
import argparse
import time
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://127.0.0.1:7860")
    parser.add_argument("--prompt", default="a chess knight piece, ornate baroque style")
    parser.add_argument("--quality", default="standard", choices=["draft", "standard", "high"])
    parser.add_argument("--timeout-min", type=int, default=12)
    parser.add_argument("--out", default="demo_recordings")
    args = parser.parse_args()

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
        page.goto(args.url, wait_until="networkidle")
        time.sleep(3)  # let the header/banner settle on camera

        # type the prompt like a human (real key events, visible on video)
        box = page.locator("textarea").first
        box.click()
        box.type(args.prompt, delay=45)
        time.sleep(1)

        # pick quality from the first dropdown
        combo = page.get_by_label("Quality", exact=False).first
        try:
            combo.click()
            page.get_by_role("option", name=args.quality, exact=True).click()
        except Exception:
            pass  # keep default if the dropdown DOM differs
        time.sleep(1)

        page.get_by_role("button", name="Forge it").click()

        # wait for the summary markdown to show the printability line
        page.wait_for_selector("text=Printability", timeout=args.timeout_min * 60_000)
        time.sleep(2)

        # orbit the 3D viewer with slow drags for the beauty shot
        canvas = page.locator("canvas").last
        bb = canvas.bounding_box()
        if bb:
            cx, cy = bb["x"] + bb["width"] / 2, bb["y"] + bb["height"] / 2
            for dx in (140, 140, -320, 180):
                page.mouse.move(cx, cy)
                page.mouse.down()
                for step in range(20):
                    page.mouse.move(cx + dx * (step + 1) / 20, cy, steps=1)
                    time.sleep(0.03)
                page.mouse.up()
                time.sleep(0.7)

        # linger on the report/summary, then finish
        page.mouse.wheel(0, 500)
        time.sleep(4)
        video_path = page.video.path()
        ctx.close()
        browser.close()

    print(f"recorded: {video_path}")
    print("convert with:  ffmpeg -i <webm> -c:v libx264 -pix_fmt yuv420p demo_ui.mp4")


if __name__ == "__main__":
    main()
