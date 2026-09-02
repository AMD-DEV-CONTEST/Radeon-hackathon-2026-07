"""Contact sheet of every asset MeshSmith has generated: concept image, rendered
mesh, and its printability score. Demonstrates output diversity at a glance.

    python scripts/build_gallery.py --out assets/gallery.png
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PIL import Image, ImageDraw, ImageFont

from render_asset import render

CELL = 420
PAD = 14
LABEL_H = 54


def load_font(size: int):
    for name in ("segoeui.ttf", "DejaVuSans.ttf", "arial.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default()


def collect(runs_root: Path) -> list[dict]:
    entries = []
    for run in sorted(runs_root.glob("**/report.json")):
        try:
            data = json.loads(run.read_text(encoding="utf-8"))
        except Exception:
            continue
        glb = next((p for p in run.parent.glob("*.glb")), None)
        if glb is None:
            continue
        entries.append({
            "dir": run.parent,
            "glb": glb,
            "prompt": data.get("prompt") or "(image input)",
            "score": data.get("print", {}).get("score", 0),
            "preset": data.get("preset", "?"),
            "concept": run.parent / "concept.png",
        })
    # de-duplicate by prompt, keeping the highest-quality preset run
    rank = {"draft": 0, "standard": 1, "high": 2}
    best: dict[str, dict] = {}
    for e in entries:
        key = e["prompt"]
        if key not in best or rank.get(e["preset"], 0) >= rank.get(best[key]["preset"], 0):
            best[key] = e
    return list(best.values())


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--runs", default="outputs")
    parser.add_argument("--out", default="assets/gallery.png")
    parser.add_argument("--cols", type=int, default=3)
    args = parser.parse_args()

    import trimesh

    entries = collect(Path(args.runs))
    if not entries:
        sys.exit("no runs with report.json + .glb found")
    print(f"{len(entries)} assets")

    cols = min(args.cols, len(entries))
    rows = (len(entries) + cols - 1) // cols
    sheet = Image.new(
        "RGB",
        (cols * (CELL + PAD) + PAD, rows * (CELL + LABEL_H + PAD) + PAD),
        (250, 250, 252),
    )
    draw = ImageDraw.Draw(sheet)
    f_title = load_font(19)
    f_sub = load_font(16)

    for i, e in enumerate(entries):
        mesh = trimesh.load(e["glb"], force="mesh")
        shot = render(mesh, 35.0, size=CELL).convert("RGB")
        if e["concept"].exists():  # inset the concept image, bottom-left
            thumb = Image.open(e["concept"]).convert("RGB").resize((118, 118))
            shot.paste(thumb, (6, CELL - 124))
            ImageDraw.Draw(shot).rectangle(
                [6, CELL - 124, 6 + 118, CELL - 6], outline=(190, 190, 196), width=2)

        x = PAD + (i % cols) * (CELL + PAD)
        y = PAD + (i // cols) * (CELL + LABEL_H + PAD)
        sheet.paste(shot, (x, y))

        prompt = e["prompt"]
        if len(prompt) > 44:
            prompt = prompt[:41] + "…"
        draw.text((x + 4, y + CELL + 6), prompt, fill=(24, 26, 32), font=f_title)
        score = e["score"]
        color = (26, 140, 70) if score >= 85 else (200, 120, 0) if score >= 60 else (190, 40, 40)
        draw.text((x + 4, y + CELL + 30), f"printability {score}/100 · {e['preset']}",
                  fill=color, font=f_sub)
        print(f"  {e['prompt'][:50]} — {score}/100")

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(out)
    print(f"wrote {out} ({sheet.width}x{sheet.height})")


if __name__ == "__main__":
    main()
