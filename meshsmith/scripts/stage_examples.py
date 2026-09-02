"""Copy a curated set of real generated artifacts into assets/examples/ so the
repository ships inspectable output (GLB + printability reports), not just
screenshots. outputs/ itself is gitignored because full runs are large.

    python scripts/stage_examples.py
"""
import argparse
import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEST = ROOT / "assets" / "examples"
MAX_MB = 6.0  # keep the repo light; bigger artifacts stay regenerable


def newest_run_for(runs: Path, needle: str) -> Path | None:
    hits = sorted((p.parent for p in runs.glob("**/report.json") if needle in p.parent.name),
                  key=lambda d: d.name, reverse=True)
    return hits[0] if hits else None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", default="outputs")
    ap.add_argument("--pick", nargs="*", default=["fox", "amphora", "knob"],
                    help="substrings of run dir names to stage")
    args = ap.parse_args()

    runs = ROOT / args.runs
    DEST.mkdir(parents=True, exist_ok=True)
    staged = []

    for needle in args.pick:
        run = newest_run_for(runs, needle)
        if run is None:
            print(f"  ! no run found for '{needle}'")
            continue
        data = json.loads((run / "report.json").read_text(encoding="utf-8"))
        for src in list(run.glob("*.glb")) + [run / "report.md", run / "report.json"]:
            if not src.exists():
                continue
            size_mb = src.stat().st_size / 1024**2
            if size_mb > MAX_MB:
                print(f"  - skip {src.name} ({size_mb:.1f} MB > {MAX_MB} MB cap)")
                continue
            dst = DEST / f"{needle}_{src.name}"
            shutil.copy2(src, dst)
            staged.append((dst.name, size_mb))
        print(f"  staged {needle}: score {data['print']['score']}/100, "
              f"{data.get('print_faces', '?')} faces in STL")

    manifest = DEST / "README.md"
    lines = [
        "# Example outputs",
        "",
        "Real artifacts from actual MeshSmith runs — not mockups. Open the `.glb` in any",
        "glTF viewer (or drag onto https://gltf-viewer.donmccurdy.com). Each `report.md`",
        "is the printability analysis MeshSmith generated for that same mesh.",
        "",
        "Print STLs are not committed (tens of MB); regenerate any of these with:",
        "",
        "```bash",
        "python -m meshsmith.cli \"a low-poly fox figurine\" --quality draft --seed 1234",
        "```",
        "",
        "| File | Size |",
        "|---|---:|",
    ]
    for name, mb in sorted(staged):
        lines.append(f"| `{name}` | {mb:.1f} MB |")
    manifest.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"\nstaged {len(staged)} files -> {DEST}")


if __name__ == "__main__":
    sys.exit(main())
