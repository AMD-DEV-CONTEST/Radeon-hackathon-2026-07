"""Session 6: inject recorded trajectory JSON into the demo3d HTML template,
producing a single self-contained file with zero fetch()/CORS dependency (works via
plain file:// double-click, per the brief's stated preference)."""
import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent
TEMPLATE = _ROOT / "demo3d_template.html"
DATA_DIR = _ROOT.parent.parent / "demo" / "interactive_3d"
OUT = _ROOT.parent.parent / "demo" / "interactive_3d" / "index.html"

ORDER = ["baseline_fail", "winner_succeed", "winner_apple_fail"]


def main() -> None:
    trajectories = {}
    for key in ORDER:
        path = DATA_DIR / f"{key}.json"
        trajectories[key] = json.loads(path.read_text())

    html = TEMPLATE.read_text()
    marker = 'const TRAJECTORIES = {"__PLACEHOLDER__": true};'
    assert marker in html, "template marker not found -- did demo3d_template.html change?"
    payload = "const TRAJECTORIES = " + json.dumps(trajectories, separators=(",", ":")) + ";"
    html = html.replace(marker, payload)

    OUT.write_text(html)
    print(f"wrote {OUT} ({OUT.stat().st_size / 1024:.0f} KB)")


if __name__ == "__main__":
    main()
