from __future__ import annotations

import argparse
import json
import subprocess
import tempfile
from pathlib import Path

from PIL import Image

from prooflaunch_remix.files import atomic_write_text, sha256_file
from prooflaunch_remix.visual_release_gate import seal


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "artifacts/gtm-last-mile-pk-v1/gtm-breakout-operator-v1/case-system-v2.json"
OUTPUT = ROOT / "artifacts/gtm-last-mile-pk-v1/keep-unpostable-carousel-v1"
CHROME = Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")


SLIDES = (
    {
        "id": "01",
        "theme": "linen",
        "kicker": "A PRIVATE-MEMORY EXPERIMENT",
        "headline": "DO NOT<br>POST THIS.",
        "body": "Some moments lose value the moment they become content.",
        "folio": "01 / BREAK THE FEED REFLEX",
        "motif": "ring",
    },
    {
        "id": "02",
        "theme": "blue",
        "kicker": "TODAY'S ENTIRE ASSIGNMENT",
        "headline": "KEEP ONE<br>USELESS<br>DETAIL.",
        "body": "A texture. A sound. A sentence. A color. A place.\n\nUseless to the feed. Useful to you.",
        "folio": "02 / LOWER THE BURDEN",
        "motif": "marks",
    },
    {
        "id": "03",
        "theme": "ink",
        "kicker": "PRIVACY IS PART OF THE PAYOFF",
        "headline": "HIDE THE<br>PAYOFF.",
        "body": "On day seven, the memory stays face-down until its owner chooses to look. A weekly artifact is not a reveal mechanic.",
        "folio": "03 / REMOVE THE AUDIENCE",
        "motif": "card",
    },
    {
        "id": "04",
        "theme": "coral",
        "kicker": "THE RITUAL FAILS IF IT CREATES HOMEWORK",
        "headline": "REMOVE THE<br>PRESSURE.",
        "body": "NO STREAK\nNO AUDIENCE\nNO POLISHING\nNO CATCH-UP QUEST",
        "folio": "04 / PROTECT THE RITUAL",
        "motif": "checklist",
    },
    {
        "id": "05",
        "theme": "yellow",
        "kicker": "THE ONLY RETENTION QUESTION THAT COUNTS",
        "headline": "DID IT EARN<br>ANOTHER<br>WEEK?",
        "body": "KEEP · EDIT · EXPORT · DELETE\n\nTry seven private days. If you respond, reply only KEEP—not the memory.",
        "folio": "05 / LET THE OWNER DECIDE",
        "motif": "decision",
    },
)


def motif_html(name: str) -> str:
    if name == "ring":
        return '<div class="coffee-ring"></div><div class="tiny-note">TUE / THE TRAIN ARRIVED EARLY.</div>'
    if name == "marks":
        return '<div class="mark-grid"><span>TEXTURE</span><span>SOUND</span><span>SENTENCE</span><span>COLOR</span><span>PLACE</span></div>'
    if name == "card":
        return '<div class="private-card"><i>DAY 07</i><b>PRIVATE MEMORY</b><span>OWNER CONTROLLED</span></div>'
    if name == "checklist":
        return '<div class="pressure-grid"><span>× STREAK</span><span>× AUDIENCE</span><span>× POLISH</span><span>× CATCH-UP</span></div>'
    return '<div class="decision-row"><span>KEEP</span><span>EDIT</span><span>EXPORT</span><span>DELETE</span></div>'


def page(slide: dict[str, str]) -> str:
    return f'''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=1080,initial-scale=1"><style>
:root{{--paper:#eee9de;--ink:#0b0b0a;--blue:#345cff;--acid:#dcff32;--coral:#ff6048;--yellow:#ffd83d}}*{{box-sizing:border-box}}html,body{{margin:0;width:1080px;height:1350px;overflow:hidden}}body{{font-family:Arial,Helvetica,sans-serif;background:var(--paper);color:var(--ink)}}main{{position:relative;display:flex;flex-direction:column;width:100%;height:100%;padding:58px;border:4px solid currentColor;overflow:hidden}}body.blue main{{background:var(--blue);color:#fff}}body.ink main{{background:var(--ink);color:var(--paper);border-color:var(--paper)}}body.coral main{{background:var(--coral)}}body.yellow main{{background:var(--yellow)}}header{{display:flex;justify-content:space-between;gap:28px;padding-bottom:20px;border-bottom:3px solid currentColor}}.brand,.kicker,.folio,.boundary{{font:900 17px/1.15 ui-monospace,SFMono-Regular,Menlo,monospace;letter-spacing:.09em}}.kicker{{max-width:560px;text-align:right}}h1{{position:relative;z-index:2;max-width:970px;margin:62px 0 30px;font-size:106px;line-height:.82;letter-spacing:-.075em}}.body{{position:relative;z-index:2;max-width:865px;white-space:pre-line;font-size:31px;font-weight:750;line-height:1.16}}.motif{{position:relative;z-index:1;flex:1;min-height:300px}}footer{{position:relative;z-index:2;display:flex;justify-content:space-between;align-items:flex-end;gap:24px;padding-top:22px;border-top:3px solid currentColor}}.boundary{{max-width:610px;font-size:13px;line-height:1.35}}.folio{{text-align:right}}.coffee-ring{{position:absolute;right:30px;bottom:30px;width:320px;height:320px;border:28px solid rgba(123,73,35,.26);border-radius:50%;box-shadow:inset 0 0 0 5px rgba(123,73,35,.12);transform:rotate(-8deg)}}.tiny-note{{position:absolute;left:24px;bottom:100px;width:440px;padding:30px;background:#fff9c9;border:3px solid var(--ink);box-shadow:14px 14px 0 var(--ink);transform:rotate(-2deg);font:900 25px/1.2 ui-monospace,monospace}}.mark-grid{{position:absolute;left:0;right:0;bottom:54px;display:grid;grid-template-columns:repeat(2,1fr);gap:12px}}.mark-grid span{{padding:20px;border:3px solid currentColor;font:900 23px ui-monospace,monospace}}.mark-grid span:last-child{{grid-column:1/-1;background:var(--acid);color:var(--ink)}}.private-card{{position:absolute;left:160px;right:80px;bottom:34px;height:330px;padding:34px;background:linear-gradient(145deg,#c9c2b5,#f4f0e7);border:4px solid var(--paper);color:var(--ink);box-shadow:26px 26px 0 var(--blue);transform:rotate(-4deg);filter:blur(5px);display:flex;flex-direction:column;justify-content:space-between}}.private-card i,.private-card span{{font:900 20px ui-monospace,monospace}}.private-card b{{font-size:56px;letter-spacing:-.05em}}.pressure-grid{{position:absolute;left:0;right:0;bottom:38px;display:grid;grid-template-columns:1fr 1fr;gap:12px}}.pressure-grid span{{padding:28px;border:4px solid currentColor;background:rgba(255,255,255,.28);font:900 29px ui-monospace,monospace}}.decision-row{{position:absolute;left:0;right:0;bottom:45px;display:grid;grid-template-columns:repeat(4,1fr);gap:8px}}.decision-row span{{padding:22px 4px;background:var(--ink);color:var(--paper);text-align:center;font:900 20px ui-monospace,monospace}}body.blue .boundary,body.ink .boundary{{color:inherit}}
</style></head><body class="{slide['theme']}"><main><header><div class="brand">LOOPNOTE<br>PRIVATE / 07</div><div class="kicker">{slide['kicker']}</div></header><h1>{slide['headline']}</h1><div class="body">{slide['body']}</div><div class="motif">{motif_html(slide['motif'])}</div><footer><div class="boundary">SYNTHETIC PRODUCT CONCEPT · NO USER RESULT, RETENTION OR MARKET EFFECT EXISTS</div><div class="folio">{slide['folio']}</div></footer></main></body></html>'''


def render(html_path: Path, png_path: Path) -> None:
    png_path.unlink(missing_ok=True)
    with tempfile.TemporaryDirectory(prefix=f"keep-unpostable-{html_path.stem}-", dir="/private/tmp") as profile:
        try:
            result = subprocess.run(
                [
                    str(CHROME),
                    "--headless=new",
                    "--disable-gpu",
                    "--hide-scrollbars",
                    f"--user-data-dir={profile}",
                    "--window-size=1080,1350",
                    "--force-device-scale-factor=1",
                    "--virtual-time-budget=1000",
                    f"--screenshot={png_path}",
                    html_path.as_uri(),
                ],
                capture_output=True,
                text=True,
                check=False,
                timeout=10,
            )
        except subprocess.TimeoutExpired as error:
            if png_path.is_file():
                return
            raise RuntimeError(f"Chrome timed out before writing {png_path.name}") from error
    if result.returncode != 0 or not png_path.is_file():
        raise RuntimeError(f"Chrome render failed for {html_path.name}: {result.stderr[-2000:]}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--render", action="store_true")
    args = parser.parse_args()
    source = json.loads(SOURCE.read_text(encoding="utf-8"))
    activation = source["cases"]["b2c"]["activation_wave"]
    instagram = next(route for route in activation if route["id"] == "b2c-instagram-secondary")
    if instagram["external_execution"] or not instagram["human_release_required"]:
        raise SystemExit("B2C release truth boundary drifted")

    OUTPUT.mkdir(parents=True, exist_ok=True)
    files = []
    for slide in SLIDES:
        html_path = OUTPUT / f"slide-{slide['id']}.html"
        png_path = OUTPUT / f"slide-{slide['id']}-1080x1350.png"
        atomic_write_text(html_path, page(slide))
        if args.render and not png_path.is_file():
            render(html_path, png_path)
        if not png_path.is_file():
            raise SystemExit(f"missing rendered slide: {png_path}")
        with Image.open(png_path) as image:
            if image.size != (1080, 1350):
                raise SystemExit(f"dimension drift: {png_path} {image.size}")
            rgb = image.convert("RGB")
            near_white = sum(
                1 for red, green, blue in rgb.get_flattened_data()
                if red >= 250 and green >= 250 and blue >= 250
            ) / (image.width * image.height)
            if near_white >= .90:
                raise SystemExit(f"blank-render signature: {png_path} {near_white:.4f}")
        files.append(
            {
                "slide_id": slide["id"],
                "html": {"path": html_path.name, "sha256": sha256_file(html_path), "bytes": html_path.stat().st_size},
                "png": {
                    "path": png_path.name,
                    "sha256": sha256_file(png_path),
                    "bytes": png_path.stat().st_size,
                    "width": 1080,
                    "height": 1350,
                    "near_white_ratio": round(near_white, 6),
                },
            }
        )

    receipt = seal(
        {
            "schema": "ProofLaunchKeepUnpostableCarouselReceiptV1",
            "creative_platform": "Keep the Unpostable",
            "source_case_system_sha256": source["content_sha256"],
            "source_activation_route": instagram["id"],
            "platform": "instagram",
            "slide_count": 5,
            "render_method": "deterministic_html_css_headless_chrome",
            "files": files,
            "first_frame_hook": "DO NOT POST THIS.",
            "participation_rule": "Reply only KEEP—not the private memory.",
            "human_release_required": True,
            "human_visual_review_status": "pending",
            "external_publish_executed": False,
            "human_preference_observed": False,
            "organic_breakout_observed": False,
            "conversion_observed": False,
            "truth_boundary": (
                "This receipt proves five deterministic 1080x1350 creative candidates with a bound synthetic-product disclosure. "
                "It proves no direct publishability, human preference, organic breakout, conversion, retention, 4A quality or named-product superiority."
            ),
        }
    )
    atomic_write_text(OUTPUT / "receipt.json", json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"output": str(OUTPUT), "slide_count": len(files), "content_sha256": receipt["content_sha256"]}, sort_keys=True))


if __name__ == "__main__":
    main()
