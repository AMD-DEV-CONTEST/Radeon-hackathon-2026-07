"""Benchmark: run a fixed prompt set through the full pipeline and emit the
markdown table used in the project profile / demo video.

    python scripts/benchmark.py --quality standard --out docs/benchmark.md
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from meshsmith.device import device_banner
from meshsmith.pipeline import MeshSmith

PROMPTS = [
    "a chess knight piece, ornate baroque style",
    "a cute robot mascot with round head",
    "a replacement drawer knob, fluted cylinder",
    "a low-poly fox figurine",
    "a Greek amphora vase with two handles",
]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--quality", default="standard")
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--out", default="docs/benchmark.md")
    parser.add_argument("--limit", type=int, default=len(PROMPTS))
    args = parser.parse_args()

    banner = device_banner()
    smith = MeshSmith(output_root="outputs/bench")

    rows = []
    for prompt in PROMPTS[: args.limit]:
        print(f"\n=== {prompt}")
        r = smith.run(prompt=prompt, preset=args.quality, seed=args.seed,
                      progress=lambda f, d: print(f"  [{int(f*100):3d}%] {d}"))
        t = {s["name"]: s["seconds"] for s in r["timings"]["stages"]}
        rows.append({
            "prompt": prompt,
            "total_s": r["timings"]["total_seconds"],
            "image_s": t.get("Text → image (SDXL-Turbo)", 0),
            "shape_s": next((v for k, v in t.items() if k.startswith("Image → 3D")), 0),
            "score": r["print"]["score"],
            "faces": r["cleanup"]["faces_after"],
        })

    lines = [
        f"# MeshSmith benchmark — {banner['gpu']} ({banner['backend']})",
        "",
        f"Preset: `{args.quality}` · seed {args.seed} · torch {banner['torch']}",
        "",
        "| Prompt | Image (s) | 3D shape (s) | Total (s) | Faces | Print score |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for r in rows:
        lines.append(
            f"| {r['prompt']} | {r['image_s']:.1f} | {r['shape_s']:.1f} "
            f"| {r['total_s']:.1f} | {r['faces']:,} | {r['score']}/100 |"
        )
    avg = sum(r["total_s"] for r in rows) / len(rows)
    lines += ["", f"**Average end-to-end: {avg:.1f}s per asset.**"]

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(lines), encoding="utf-8")
    print(f"\nWrote {out}")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
