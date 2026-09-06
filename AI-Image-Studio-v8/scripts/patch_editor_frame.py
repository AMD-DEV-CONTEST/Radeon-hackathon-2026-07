"""Workaround for a Gradio 6.17.3 upstream issue (ImageEditor dark frame).

Gradio 6.17.3 serves <gradio-app> without a theme_mode attribute, so the
ImageEditor's Pixi stage falls back to `theme_mode || "dark"` and clears its
canvas with #27272a — a charcoal frame that clashes with the light theme.
The color is a WebGL clear color, unreachable from CSS, and the frontend
module registers the custom element before any head-injected script can
intercept it (verified with Playwright), so we patch the built chunk
server-side: flip the fallback from "dark" to "light".

Idempotent by design — run on every start (start.sh does), and re-run after
any gradio reinstall/upgrade.
"""

import glob
import os
import sys

import gradio

OLD = 'this.theme_mode=t.theme_mode||"dark"'
NEW = 'this.theme_mode=t.theme_mode||"light"'


def main() -> int:
    assets = os.path.join(
        os.path.dirname(gradio.__file__), "templates", "frontend", "assets"
    )
    chunks = glob.glob(os.path.join(assets, "Index-*.js"))
    for path in chunks:
        with open(path, encoding="utf-8") as f:
            src = f.read()
        if OLD not in src:
            continue
        with open(path, "w", encoding="utf-8") as f:
            f.write(src.replace(OLD, NEW))
        print(f"[patch] ImageEditor frame -> light: {os.path.basename(path)}")
        return 0
    already = any(
        NEW in open(p, encoding="utf-8").read() for p in chunks
    )
    if already:
        print("[patch] already applied, nothing to do")
        return 0
    print("[patch] WARNING: marker not found (gradio changed?) — "
          "editor frame may stay dark", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
