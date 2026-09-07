#!/usr/bin/env python3
"""Build demo/interactive_3d/index_artifact.html from index.html.

index.html uses ES modules with a CDN import map (Three.js + addons from
unpkg) -- fine for GitHub Pages / local file://, but Claude Artifact's CSP
does not execute `data:` URIs as ES module sources, and there is no network
access for a live CDN import map either. This script produces a fully
self-contained, CSP-safe variant by:

  1. Dropping the <script type="importmap"> block entirely.
  2. Inlining Three.js's UMD global build (sets window.THREE) and every
     addon module index.html imports, each hand-transformed from ES module
     syntax (import {...} from 'three'; export {...};) to a plain classic
     <script> that destructures off the THREE global and assigns its export
     to a global name -- no import/export statements anywhere, so no ES
     module resolution (and thus no CSP-blocked data: URI) is needed at all.
  3. Converting the app's own <script type="module"> to a classic <script>
     and stripping its `import` lines (THREE/OrbitControls/etc. are already
     globals by the time it runs).

Run from the repo root:
    uv run python scripts/build_artifact_demo.py
(requires network access to unpkg.com the first time, to fetch/cache the
Three.js build + addon sources under scripts/.artifact_vendor_cache/)
"""
import re
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEMO_DIR = ROOT / "demo" / "interactive_3d"
CACHE_DIR = Path(__file__).resolve().parent / ".artifact_vendor_cache"
CACHE_DIR.mkdir(exist_ok=True)

THREE_VERSION = "0.160.0"

# (unpkg path, cache filename, global name the app references)
ADDON_MODULES = [
    ("examples/jsm/controls/OrbitControls.js", "OrbitControls.js", "OrbitControls"),
    ("examples/jsm/geometries/RoundedBoxGeometry.js", "RoundedBoxGeometry.js", "RoundedBoxGeometry"),
    ("examples/jsm/environments/RoomEnvironment.js", "RoomEnvironment.js", "RoomEnvironment"),
]


def fetch(rel_path: str, cache_name: str) -> str:
    cache_path = CACHE_DIR / cache_name
    if not cache_path.exists():
        url = f"https://unpkg.com/three@{THREE_VERSION}/{rel_path}"
        with urllib.request.urlopen(url) as resp:
            cache_path.write_bytes(resp.read())
    return cache_path.read_text(encoding="utf-8")


def transform_addon_module(src: str, export_name: str) -> str:
    """Strip `import {...} from 'three';` -> destructure off global THREE, and
    replace `export { Name };` (or `export { Name, ... };`) with a global assignment.

    Wrapped in its own IIFE: classic <script> tags (unlike ES modules) all share one
    top-level lexical scope, so if two addons both destructure e.g. `Vector3` from THREE
    (OrbitControls and RoundedBoxGeometry both do), the second `const Vector3` throws a
    redeclaration error. An IIFE keeps each addon's internal names local; only the
    final `window.X = X` assignment needs to actually leak out."""
    src = re.sub(
        r"import\s*\{([^}]+)\}\s*from\s*['\"]three['\"];",
        lambda m: "const {" + m.group(1) + "} = THREE;",
        src,
        count=1,
    )
    src = re.sub(r"export\s*\{\s*" + re.escape(export_name) + r"\s*\};", f"window.{export_name} = {export_name};", src)
    assert "import " not in src, f"leftover import statement after transform ({export_name})"
    assert "export " not in src, f"leftover export statement after transform ({export_name})"
    assert f"window.{export_name} = {export_name};" in src, f"export-to-global replacement didn't match for {export_name}"
    return "(function(){\n" + src + "\n})();"


def main():
    three_src = fetch("build/three.min.js", "three.min.js")

    html = (DEMO_DIR / "index.html").read_text(encoding="utf-8")

    # 1. Drop the importmap block.
    html2 = re.sub(r'<script type="importmap">.*?</script>\s*', "", html, count=1, flags=re.DOTALL)
    assert html2 != html, "importmap block not found/removed"

    # 2. Build the classic-script blocks for Three.js + every addon the app imports.
    injected = "<script>\n" + three_src + "\n</script>\n"
    for rel_path, cache_name, export_name in ADDON_MODULES:
        addon_src = fetch(rel_path, cache_name)
        addon_src = transform_addon_module(addon_src, export_name)
        injected += "<script>\n" + addon_src + "\n</script>\n"

    # 3. Convert the app's own module script to classic and strip its import lines.
    #    Matches exactly the import block index.html currently has (in order); if that
    #    block changes, update this list to match.
    app_imports = [
        'import * as THREE from "three";',
        'import { OrbitControls } from "three/addons/controls/OrbitControls.js";',
        'import { RoundedBoxGeometry } from "three/addons/geometries/RoundedBoxGeometry.js";',
        'import { RoomEnvironment } from "three/addons/environments/RoomEnvironment.js";',
    ]
    marker_old = "<script type=\"module\">\n" + "\n".join(app_imports) + "\n"
    idx = html2.find(marker_old)
    assert idx != -1, "app script import header not found -- did index.html's import list change?"

    html2 = html2[:idx] + injected + "<script>\n" + html2[idx + len(marker_old):]
    assert '<script type="module">' not in html2
    assert "import * as THREE" not in html2
    assert 'from "three/addons' not in html2

    out_path = DEMO_DIR / "index_artifact.html"
    out_path.write_text(html2, encoding="utf-8")
    print(f"wrote {out_path} ({len(html2) / 1e6:.2f} MB)")


if __name__ == "__main__":
    main()
