#!/usr/bin/env bash
# Render the submission documents to PDF.
#
#   bash scripts/make-pdfs.sh
#
# Track 2 does not mandate PDF (only Track 1 does), but several entries submit
# them and a reviewer opening a PDF beats one reading raw markdown.
#
# Needs: pandoc, weasyprint, and pango (brew install pango).
set -euo pipefail

cd "$(dirname "$0")/.."

# weasyprint finds pango through the homebrew lib path, not the system one.
export DYLD_FALLBACK_LIBRARY_PATH="/opt/homebrew/lib:${DYLD_FALLBACK_LIBRARY_PATH:-}"

command -v pandoc >/dev/null || { echo "FAILED: pandoc missing. brew install pandoc" >&2; exit 1; }
command -v weasyprint >/dev/null || { echo "FAILED: weasyprint missing. pip install weasyprint" >&2; exit 1; }

OUT="${OUT:-dist-pdf}"
mkdir -p "$OUT"

render() { # source title output
  local src="$1" title="$2" out="$3"
  echo "==> $out"
  # Two steps on purpose. Letting pandoc drive weasyprint fails on macOS,
  # because SIP strips DYLD_* from spawned processes so weasyprint cannot find
  # homebrew's pango. Invoking weasyprint directly keeps the library path.
  # Building the HTML shell by hand rather than using --standalone: pandoc's
  # template renders a title block, which duplicates the document's own H1.
  {
    printf '<!doctype html><html><head><meta charset="utf-8">'
    printf '<title>%s</title>' "$title"
    printf '<style>'
    cat scripts/pdf.css
    printf '</style></head><body>'
    pandoc "$src" --from=gfm --to=html
    printf '</body></html>'
  } > "$OUT/${out%.pdf}.html"
  # GLib prints harmless warnings here; the file on disk is the real check.
  weasyprint "$OUT/${out%.pdf}.html" "$OUT/$out" 2>/dev/null || true
  [ -s "$OUT/$out" ] || { echo "FAILED: $out was not produced" >&2; exit 1; }
  rm -f "$OUT/${out%.pdf}.html"
}



render docs/spec.md          "Vulcan, Project Specification (Track 2, Private AI Agents)" spec-document.pdf
render docs/deck.md          "Vulcan, Supplementary Slides"                               poster.pdf
render docs/radeon-deploy.md "Vulcan, Radeon Deployment Runbook"                          radeon-deploy.pdf

echo
ls -lh "$OUT"
