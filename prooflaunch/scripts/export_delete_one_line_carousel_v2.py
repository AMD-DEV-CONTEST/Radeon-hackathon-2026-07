from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import tempfile
from pathlib import Path

from PIL import Image

from prooflaunch_remix.files import atomic_write_text, sha256_file
from prooflaunch_remix.visual_release_gate import seal


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "artifacts/gtm-last-mile-pk-v1/platform-native-challengers-v17/b2b-delete-one-line-receipt.json"
EXPERIENCE = ROOT / "artifacts/gtm-last-mile-pk-v1/delete-one-line-experience-v1/receipt.json"
OUTPUT = ROOT / "artifacts/gtm-last-mile-pk-v1/delete-one-line-carousel-v2"
CHROME = Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")


SLIDES = [
    {
        "id": "01",
        "theme": "paper",
        "kicker": "THE ZERO-BUDGET LAUNCH IS THE PRODUCT DEMO",
        "headline": "WE DELETED<br>THE SENTENCE<br>WE NEEDED MOST.",
        "body": "Not because ambition is dangerous. Because a result without a witness is still a wish.",
        "folio": "01 / THE SACRIFICE",
    },
    {
        "id": "02",
        "theme": "acid",
        "kicker": "THE LINE WE WANTED BUYERS TO REMEMBER",
        "headline": "“AN AI GTM<br>EMPLOYEE THAT<br>MAKES ANY BRAND<br>GO VIRAL.”",
        "body": "Memorable? Yes. Observed? No.",
        "folio": "02 / THE CLAIM",
        "strike": True,
    },
    {
        "id": "03",
        "theme": "ink",
        "kicker": "WE CALLED FIVE WITNESSES",
        "headline": "NONE<br>SHOWED UP.",
        "body": "OBSERVATION — EMPTY<br>SOURCE — EMPTY<br>POPULATION — EMPTY<br>PERIOD — EMPTY<br>LIMITATION — EMPTY",
        "folio": "03 / THE DOCKET",
        "docket": True,
    },
    {
        "id": "04",
        "theme": "red",
        "kicker": "LOCAL VERDICT",
        "headline": "NO<br>WITNESS.",
        "body": "DELETE FROM PUBLIC PROOF. Keep the ambition. Keep the hypothesis. Stop presenting either as an observed result.",
        "folio": "04 / THE VERDICT",
    },
    {
        "id": "05",
        "theme": "paper",
        "kicker": "SAVE THIS TEST",
        "headline": "AFTER EVERY<br>OUTCOME CLAIM,<br>ASK:",
        "body": "ACCORDING TO WHAT?\n\nIf the answer is a model output, an internal opinion, or a future plan: label the line HYPOTHESIS—or delete it.",
        "folio": "05 / RUN IT YOURSELF",
        "cta": "PUT ONE LINE ON TRIAL →",
    },
]


def page(slide: dict[str, object]) -> str:
    theme = str(slide["theme"])
    body_class = "docket-copy" if slide.get("docket") else ""
    headline_class = "strike" if slide.get("strike") else ""
    cta = f'<div class="cta">{slide["cta"]}</div>' if slide.get("cta") else ""
    return f'''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=1080,initial-scale=1"><style>
:root{{--paper:#f2eee4;--ink:#090a08;--acid:#dfff2d;--red:#ff4e38}}*{{box-sizing:border-box}}html,body{{margin:0;width:1080px;height:1350px;overflow:hidden}}body{{font-family:Arial,Helvetica,sans-serif;background:var(--paper);color:var(--ink)}}main{{height:1350px;padding:62px;display:flex;flex-direction:column;border:4px solid var(--ink);position:relative}}body.acid main{{background:var(--acid)}}body.ink main{{background:var(--ink);color:var(--paper);border-color:var(--paper)}}body.red main{{background:var(--red)}}.top{{display:flex;align-items:flex-start;justify-content:space-between;gap:30px;border-bottom:3px solid currentColor;padding-bottom:22px}}.brand,.kicker,.folio{{font:900 18px/1.08 ui-monospace,SFMono-Regular,Menlo,monospace;letter-spacing:.08em}}.kicker{{text-align:right;max-width:560px}}h1{{font-size:112px;line-height:.83;letter-spacing:-.075em;margin:76px 0 42px;max-width:960px}}h1.strike{{font-size:94px;line-height:.9;position:relative}}h1.strike:after{{content:"";position:absolute;left:-22px;right:-18px;top:49%;height:24px;background:var(--red);transform:rotate(-3deg)}}.body{{font-size:34px;line-height:1.16;font-weight:750;max-width:870px;white-space:pre-line}}.docket-copy{{font:900 31px/1.48 ui-monospace,SFMono-Regular,monospace;letter-spacing:.02em;border:3px solid currentColor;padding:24px 30px}}.cta{{margin-top:34px;display:inline-block;align-self:flex-start;background:var(--ink);color:var(--paper);padding:18px 24px;font:900 24px/1 ui-monospace,monospace;transform:rotate(-1deg)}}.bottom{{margin-top:auto;display:flex;justify-content:space-between;align-items:flex-end;border-top:3px solid currentColor;padding-top:24px}}.rule{{font:800 17px/1.3 ui-monospace,monospace;max-width:560px}}.folio{{text-align:right}}body.ink .cta{{background:var(--acid);color:var(--ink)}}
</style></head><body class="{theme}"><main><div class="top"><div class="brand">PROOFLAUNCH<br>CLAIM TRIAL</div><div class="kicker">{slide['kicker']}</div></div><h1 class="{headline_class}">{slide['headline']}</h1><div class="body {body_class}">{slide['body']}</div>{cta}<div class="bottom"><div class="rule">DELETE THE CLAIM · KEEP THE HYPOTHESIS · EARN THE WITNESS</div><div class="folio">{slide['folio']}</div></div></main></body></html>'''


def render(html_path: Path, png_path: Path) -> None:
    png_path.unlink(missing_ok=True)
    with tempfile.TemporaryDirectory(
        prefix=f"prooflaunch-carousel-{html_path.stem}-",
        dir="/private/tmp",
    ) as profile:
        command = [
            str(CHROME), "--headless=new", "--disable-gpu", "--hide-scrollbars",
            f"--user-data-dir={profile}", "--window-size=1080,1350", "--force-device-scale-factor=1",
            "--virtual-time-budget=1000", f"--screenshot={png_path}", html_path.as_uri(),
        ]
        try:
            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                check=False,
                timeout=8,
            )
        except subprocess.TimeoutExpired as error:
            if png_path.is_file():
                return
            raise RuntimeError(
                f"Chrome render timed out before writing {png_path.name}"
            ) from error
    if result.returncode != 0 or not png_path.is_file():
        raise RuntimeError(f"Chrome render failed for {html_path.name}: {result.stderr[-2000:]}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--render", action="store_true")
    args = parser.parse_args()
    source = json.loads(SOURCE.read_text(encoding="utf-8"))
    experience = json.loads(EXPERIENCE.read_text(encoding="utf-8"))
    if source.get("accepted_surface_count") != 13 or experience.get("production_effect_observed") is not False:
        raise SystemExit("carousel sources are incomplete or overclaim effect")
    OUTPUT.mkdir(parents=True, exist_ok=True)
    files = []
    for slide in SLIDES:
        stem = f"slide-{slide['id']}"
        html_path = OUTPUT / f"{stem}.html"
        png_path = OUTPUT / f"{stem}-1080x1350.png"
        atomic_write_text(html_path, page(slide))
        if args.render:
            render(html_path, png_path)
        if not png_path.is_file():
            raise SystemExit(f"missing rendered slide: {png_path}")
        with Image.open(png_path) as image:
            if image.size != (1080, 1350):
                raise SystemExit(f"dimension drift for {png_path}: {image.size}")
            rgb = image.convert("RGB")
            near_white = sum(
                1 for red, green, blue in rgb.get_flattened_data()
                if red >= 250 and green >= 250 and blue >= 250
            )
            near_white_ratio = near_white / (image.width * image.height)
            if near_white_ratio >= 0.90:
                raise SystemExit(
                    f"render failure signature for {png_path}: "
                    f"near_white_ratio={near_white_ratio:.4f}"
                )
        files.append({
            "slide_id": slide["id"],
            "html": {"path": html_path.name, "sha256": sha256_file(html_path), "bytes": html_path.stat().st_size},
            "png": {"path": png_path.name, "sha256": sha256_file(png_path), "bytes": png_path.stat().st_size, "width": 1080, "height": 1350, "near_white_ratio": round(near_white_ratio, 6)},
        })
    payload = seal({
        "schema": "ProofLaunchDeleteOneLineCarouselReceiptV2",
        "source_platform_receipt_sha256": source["content_sha256"],
        "source_experience_receipt_sha256": experience["content_sha256"],
        "slide_count": 5,
        "files": files,
        "render_method": "deterministic_html_css_headless_chrome",
        "generation_model_used": False,
        "post_editing_performed": False,
        "exact_visible_copy_preserved": True,
        "qualified_human_review_count": 0,
        "external_publish_executed": False,
        "production_effect_observed": False,
        "truth_boundary": "This receipt proves five deterministic 1080x1350 carousel candidates. It proves no human preference, direct publishability, organic breakout, conversion, revenue, 4A quality or named-product superiority."
    })
    atomic_write_text(OUTPUT / "receipt.json", json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"output": str(OUTPUT), "slide_count": 5, "content_sha256": payload["content_sha256"]}, sort_keys=True))


if __name__ == "__main__":
    main()
