"""Record a real terminal session on a remote GPU box via its JupyterLab terminal.

Used to film MeshSmith running on an AMD Radeon Cloud instance: the session shows
rocm-smi identifying the Radeon, then the MeshSmith CLI generating an asset with the
ROCm backend banner and the printability report — all live, on the actual hardware.

    python scripts/record_terminal.py --lab-url "https://host/instances/<id>/lab?token=<t>"
"""
import argparse
import time
from pathlib import Path

COMMANDS = [
    ("clear", 1.0),
    ("echo '=== This terminal is on the AMD Radeon Cloud instance ==='", 2.0),
    ("rocm-smi --showproductname", 6.0),
    ("source /persistent/env.sh && cd /persistent/Radeon-hackathon-2026-07/meshsmith", 2.0),
    ("python -c \"from meshsmith.device import device_banner; print(device_banner())\"", 12.0),
    ("echo '=== generating a print-ready asset on the Radeon GPU ==='", 2.0),
    ("python -m meshsmith.cli 'a low-poly fox figurine' --quality draft --seed 1234", 0.0),
]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--lab-url", required=True)
    ap.add_argument("--out", default="demo_recordings")
    ap.add_argument("--run-timeout-min", type=int, default=20)
    args = ap.parse_args()

    from playwright.sync_api import sync_playwright

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as p:
        b = p.chromium.launch()
        ctx = b.new_context(
            viewport={"width": 1920, "height": 1080},
            record_video_dir=str(out),
            record_video_size={"width": 1920, "height": 1080},
            ignore_https_errors=True,
        )
        page = ctx.new_page()
        page.set_default_timeout(90_000)

        page.goto(args.lab_url, wait_until="domcontentloaded")
        page.wait_for_timeout(12_000)  # JupyterLab is heavy

        # open a terminal: try the launcher tile, then the menu
        opened = False
        for how in ("tile", "menu"):
            try:
                if how == "tile":
                    page.get_by_text("Terminal", exact=True).first.click(timeout=15_000)
                else:
                    page.get_by_role("menuitem", name="File").click(timeout=10_000)
                    page.get_by_text("New", exact=True).first.click(timeout=10_000)
                    page.get_by_text("Terminal", exact=True).first.click(timeout=10_000)
                page.wait_for_timeout(6000)
                opened = True
                break
            except Exception as exc:
                print(f"terminal via {how} failed: {str(exc)[:80]}")
        if not opened:
            print("could not open a terminal")
            ctx.close(); b.close(); return

        page.wait_for_timeout(3000)
        page.mouse.click(960, 600)  # focus the terminal
        page.wait_for_timeout(1500)

        for cmd, pause in COMMANDS:
            page.keyboard.type(cmd, delay=38)
            page.wait_for_timeout(400)
            page.keyboard.press("Enter")
            if pause:
                page.wait_for_timeout(int(pause * 1000))

        # the generation is the long one — watch for the report line to appear
        print("waiting for the generation to finish...")
        deadline = time.time() + args.run_timeout_min * 60
        done = False
        while time.time() < deadline:
            try:
                body = page.inner_text("body")
                if "Printability:" in body or "Artifacts:" in body:
                    done = True
                    break
            except Exception:
                pass
            page.wait_for_timeout(4000)
        print("generation finished" if done else "WARNING: timed out")

        page.wait_for_timeout(4000)
        # show the report on camera
        for cmd in ["cat outputs/$(ls -t outputs | head -1)/report.md | head -20",
                    "ls -lh outputs/$(ls -t outputs | head -1)/"]:
            page.keyboard.type(cmd, delay=30)
            page.keyboard.press("Enter")
            page.wait_for_timeout(9000)

        video = page.video.path()
        ctx.close()
        b.close()
    print("recorded:", video)


if __name__ == "__main__":
    main()
