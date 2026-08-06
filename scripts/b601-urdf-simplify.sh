#!/usr/bin/env bash
# Regenerate B601 browser LOD meshes from full assets/*.STL
# Tiers: assets_catalog (~80k), assets_preview (~300k stage), full assets unchanged
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ASSETS="$ROOT/apps/realtime/static/urdf/b601_rs/assets"
PREVIEW="$ROOT/apps/realtime/static/urdf/b601_rs/assets_preview"
CATALOG="$ROOT/apps/realtime/static/urdf/b601_rs/assets_catalog"
FULL_URDF="$ROOT/apps/realtime/static/urdf/b601_rs/b601_rs.urdf"

if ! python3 -c "import trimesh" 2>/dev/null; then
  echo "[b601-urdf-simplify] installing trimesh..."
  pip install trimesh -q
fi

python3 << PY
import pathlib
import trimesh

assets = pathlib.Path("$ASSETS")
preview = pathlib.Path("$PREVIEW")
catalog = pathlib.Path("$CATALOG")
full_urdf = pathlib.Path("$FULL_URDF")

def decimate_dir(out: pathlib.Path, ratio: float, min_faces: int, max_faces: int):
    out.mkdir(parents=True, exist_ok=True)
    total = 0
    for stl in sorted(assets.glob("*.STL")):
        mesh = trimesh.load(stl, force="mesh")
        n = len(mesh.faces)
        if n < min_faces * 2:
            simp = mesh
        else:
            target = max(min_faces, min(max_faces, int(n * ratio)))
            target = min(target, n - 1)
            simp = mesh.simplify_quadric_decimation(face_count=target)
        simp.export(out / stl.name)
        total += len(simp.faces)
        print(f"{out.name}/{stl.name}: {n} -> {len(simp.faces)} tris")
    return total

cat_total = decimate_dir(catalog, ratio=0.10, min_faces=800, max_faces=4000)
prev_total = decimate_dir(preview, ratio=0.50, min_faces=2500, max_faces=28000)
print(f"catalog TOTAL {cat_total}, preview TOTAL {prev_total}")

text = full_urdf.read_text()
(preview.parent / "b601_rs_preview.urdf").write_text(
    text.replace("assets/", "assets_preview/").replace('name="b601_rs"', 'name="b601_rs_preview"')
)
(preview.parent / "b601_rs_catalog.urdf").write_text(
    text.replace("assets/", "assets_catalog/").replace('name="b601_rs"', 'name="b601_rs_catalog"')
)
print("Wrote b601_rs_preview.urdf and b601_rs_catalog.urdf")
PY

echo "[b601-urdf-simplify] done."
