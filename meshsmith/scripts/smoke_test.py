"""Model-free smoke test: exercises cleanup, decimation, UV unwrap, print
analysis and export on synthetic geometry. Runs anywhere in a few seconds.

    python scripts/smoke_test.py
"""
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np
import trimesh

from meshsmith import meshfix, printcheck, exporter
from meshsmith.device import device_banner


def make_dirty_mesh() -> trimesh.Trimesh:
    """A torus with a floater cube and duplicated faces — a mini obstacle course."""
    torus = trimesh.creation.torus(major_radius=1.0, minor_radius=0.35)
    floater = trimesh.creation.box(extents=[0.05, 0.05, 0.05])
    floater.apply_translation([3, 3, 3])
    mesh = trimesh.util.concatenate([torus, floater])
    mesh = trimesh.Trimesh(
        vertices=mesh.vertices,
        faces=np.vstack([mesh.faces, mesh.faces[:25]]),  # duplicate some faces
        process=False,
    )
    return mesh


def main():
    print("Device:", device_banner())
    mesh = make_dirty_mesh()

    cleaned, rep = meshfix.clean(mesh)
    assert rep.components_removed >= 1, "floater should be removed"
    assert cleaned.is_watertight, "torus should be watertight after cleanup"
    print(f"clean OK: faces {rep.faces_before} -> {rep.faces_after}, "
          f"floaters removed {rep.components_removed}")

    small = meshfix.decimate(cleaned, target_faces=800)
    assert len(small.faces) <= 1000, f"decimation failed: {len(small.faces)} faces"
    print(f"decimate OK: {len(cleaned.faces)} -> {len(small.faces)} faces")

    # regression guard: the print path decimates, and a non-watertight STL is
    # useless to a slicer. Decimation must not silently destroy watertightness.
    dense = trimesh.creation.icosphere(subdivisions=6)
    assert dense.is_watertight
    reduced = meshfix.decimate(dense, target_faces=20_000)
    if not reduced.is_watertight:
        reduced, _ = meshfix.clean(reduced)
    assert reduced.is_watertight, "decimation broke watertightness and repair did not restore it"
    print(f"print-path watertight OK: {len(dense.faces)} -> {len(reduced.faces)} faces, still sealed")

    unwrapped = meshfix.unwrap_uvs(small)
    assert unwrapped is not None and unwrapped.visual.uv is not None, "UV unwrap failed"
    print(f"uv OK: {len(unwrapped.visual.uv)} uv coords")

    z_up = printcheck.to_z_up(cleaned)
    oriented, report = printcheck.analyze(z_up, height_mm=60.0)
    assert 0 <= report.score <= 100
    # auto-orientation only rotates the part, so its physical size is preserved:
    # the scaled-to-60mm object keeps its diagonal no matter which face it lands on
    scaled_ref = printcheck.scale_to_height(z_up, 60.0)
    diag = lambda m: float(np.linalg.norm(m.extents))
    assert abs(diag(oriented) - diag(scaled_ref)) < 0.5, (
        f"orientation changed the part's size: {oriented.extents} vs {scaled_ref.extents}")
    assert oriented.bounds[0][2] > -1e-6, "part must sit on the bed at z=0"
    print(f"printcheck OK: score {report.score}/100 ({report.verdict}), "
          f"support saved {report.orientation['support_saved_pct']}%, "
          f"stands {report.print_height_mm} mm on the bed")

    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        exporter.export_glb(exporter.apply_material(unwrapped, "metal"), td / "t.glb")
        exporter.export_stl(oriented, td / "t.stl")
        assert (td / "t.glb").stat().st_size > 1000
        assert (td / "t.stl").stat().st_size > 1000
        reload = trimesh.load(td / "t.stl")
        assert len(reload.faces) > 0
        print("export OK: glb + stl round-trip")

    print("\nSMOKE TEST PASSED")


if __name__ == "__main__":
    main()
