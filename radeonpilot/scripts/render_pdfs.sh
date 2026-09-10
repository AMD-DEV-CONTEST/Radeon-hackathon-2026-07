#!/usr/bin/env bash
# Render submission PDFs: Project Specification and Poster.
# Requires: pandoc and Google Chrome (headless). Run from the project root.
set -euo pipefail
cd "$(dirname "$0")/.."

CHROME="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
if [ ! -x "$CHROME" ]; then
  CHROME="$(command -v google-chrome || command -v chromium || true)"
fi
if [ -z "$CHROME" ]; then
  echo "Chrome/Chromium not found; cannot render PDFs" >&2
  exit 1
fi

CSS="$(mktemp /tmp/radeonpilot_spec_XXXX.css)"
cat > "$CSS" <<'EOF'
body { font-family: "Helvetica Neue", Arial, sans-serif; max-width: 180mm; margin: 0 auto; line-height: 1.55; color: #1a2233; }
h1 { border-bottom: 3px solid #ed1c24; padding-bottom: 4px; }
h2 { color: #0b5394; margin-top: 1.4em; }
pre { background: #f3f5f9; padding: 10px; border-radius: 6px; font-size: 9pt; }
code { background: #f3f5f9; padding: 1px 3px; border-radius: 3px; }
table { border-collapse: collapse; width: 100%; }
th, td { border: 1px solid #c8d2e0; padding: 5px 8px; text-align: left; }
th { background: #eef2f8; }
blockquote { border-left: 4px solid #ed1c24; margin-left: 0; padding-left: 12px; color: #4a5568; }
EOF

echo "Rendering docs/PROJECT_SPECIFICATION.pdf ..."
pandoc docs/PROJECT_SPECIFICATION.md -s --metadata title="RadeonPilot - Project Specification" \
  -c "$CSS" --embed-resources -o /tmp/radeonpilot_spec.html
"$CHROME" --headless --disable-gpu --no-sandbox --print-to-pdf=docs/PROJECT_SPECIFICATION.pdf \
  --no-pdf-header-footer "file:///tmp/radeonpilot_spec.html" >/dev/null 2>&1

echo "Rendering docs/POSTER.pdf ..."
"$CHROME" --headless --disable-gpu --no-sandbox --print-to-pdf=docs/POSTER.pdf \
  --no-pdf-header-footer "file://$(pwd)/docs/poster.html" >/dev/null 2>&1

echo "Rendering docs/assets/architecture.png ..."
"$CHROME" --headless --disable-gpu --no-sandbox \
  --screenshot=docs/assets/architecture.png --window-size=1560,900 --hide-scrollbars \
  "file://$(pwd)/docs/assets/architecture.svg" >/dev/null 2>&1

rm -f "$CSS" /tmp/radeonpilot_spec.html
ls -lh docs/PROJECT_SPECIFICATION.pdf docs/POSTER.pdf
