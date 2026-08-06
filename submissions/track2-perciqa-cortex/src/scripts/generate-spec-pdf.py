#!/usr/bin/env python3
"""Convert project-spec.md to a polished PDF for hackathon submission.

Usage:
    python scripts/generate-spec-pdf.py [--output docs/submission/project-spec.pdf]

Requires: pip install weasyprint
"""
import argparse
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SPEC_MD = REPO / "docs" / "submission" / "project-spec.md"
DEFAULT_OUTPUT = REPO / "docs" / "submission" / "project-spec.pdf"

HTML_TEMPLATE = """\
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<style>
  @page {{
    margin: 2cm 2.5cm;
    @bottom-right {{
      content: counter(page) " / " counter(pages);
      font-size: 9pt;
      color: #666;
      font-family: 'Helvetica Neue', Helvetica, Arial, sans-serif;
    }}
  }}
  body {{
    font-family: 'Helvetica Neue', Helvetica, Arial, sans-serif;
    font-size: 11pt;
    line-height: 1.6;
    color: #1a1a1a;
  }}
  h1 {{
    font-size: 20pt;
    color: #1a1a1a;
    border-bottom: 3px solid #ed1c24;
    padding-bottom: 8px;
    margin-top: 30px;
  }}
  h2 {{
    font-size: 16pt;
    color: #333;
    border-bottom: 1px solid #ddd;
    padding-bottom: 4px;
    margin-top: 24px;
  }}
  h3 {{ font-size: 13pt; color: #444; margin-top: 18px; }}
  h4 {{ font-size: 11pt; color: #555; }}
  table {{
    width: 100%;
    border-collapse: collapse;
    margin: 12px 0;
    font-size: 10pt;
  }}
  th, td {{
    border: 1px solid #ccc;
    padding: 6px 10px;
    text-align: left;
  }}
  th {{
    background: #f5f5f5;
    font-weight: 600;
  }}
  code {{
    background: #f4f4f4;
    padding: 1px 4px;
    border-radius: 3px;
    font-family: 'SF Mono', 'Monaco', 'Menlo', monospace;
    font-size: 9pt;
  }}
  pre {{
    background: #f8f8f8;
    border: 1px solid #e0e0e0;
    border-radius: 4px;
    padding: 10px 14px;
    overflow-x: auto;
    font-size: 9pt;
    line-height: 1.4;
  }}
  blockquote {{
    border-left: 3px solid #ed1c24;
    margin: 12px 0;
    padding: 6px 14px;
    background: #fef5f5;
  }}
  hr {{
    border: none;
    border-top: 1px solid #ddd;
    margin: 20px 0;
  }}
  .cover {{
    text-align: center;
    padding-top: 120px;
    page-break-after: always;
  }}
  .cover h1 {{
    font-size: 28pt;
    border: none;
    margin-bottom: 8px;
  }}
  .cover .subtitle {{
    font-size: 14pt;
    color: #666;
    margin-bottom: 40px;
  }}
  .cover .meta {{
    font-size: 10pt;
    color: #888;
  }}
  img {{
    max-width: 100%;
  }}
</style>
</head>
<body>

<div class="cover">
  <h1>Perciqa Cortex</h1>
  <div class="subtitle">Decentralized Agent Memory Fabric<br>with Cryptographic Provenance</div>
  <div class="meta">
    <p>AMD AI DevMaster Hackathon 2026 — Track 2</p>
    <p>Development &amp; Local Deployment of Private AI Agents</p>
  </div>
</div>

{content}

</body>
</html>
"""


def md_to_html(md_path: Path) -> str:
    """Convert markdown to HTML using Python's markdown library or pandoc."""
    try:
        import markdown

        extensions = ["extra", "tables", "fenced_code", "codehilite"]
        with open(md_path) as f:
            return markdown.markdown(f.read(), extensions=extensions)
    except ImportError:
        pass

    try:
        result = subprocess.run(
            ["pandoc", str(md_path), "-t", "html", "--mathjax"],
            capture_output=True, text=True, check=True,
        )
        return result.stdout
    except (subprocess.CalledProcessError, FileNotFoundError):
        pass

    print("ERROR: need either 'markdown' (pip install markdown) or 'pandoc'", file=sys.stderr)
    sys.exit(1)


def main() -> int:
    ap = argparse.ArgumentParser(description="Generate project-spec PDF")
    ap.add_argument("--output", default=str(DEFAULT_OUTPUT),
                    help=f"Output PDF path (default: {DEFAULT_OUTPUT})")
    ap.add_argument("--md", default=str(SPEC_MD),
                    help=f"Input markdown path (default: {SPEC_MD})")
    args = ap.parse_args()

    md_path = Path(args.md)
    out_path = Path(args.output)

    if not md_path.exists():
        print(f"ERROR: {md_path} not found", file=sys.stderr)
        return 1

    print(f"Reading {md_path}...")
    html_body = md_to_html(md_path)

    html = HTML_TEMPLATE.format(content=html_body)

    try:
        from weasyprint import HTML as WeasyPrintHTML

        print(f"Generating PDF → {out_path}...")
        WeasyPrintHTML(string=html).write_pdf(out_path)
        print(f"Done: {out_path} ({out_path.stat().st_size / 1024:.0f} KB)")
    except ImportError:
        print(
            "WARNING: weasyprint not installed. Saving HTML instead. "
            "Install with: pip install weasyprint",
            file=sys.stderr,
        )
        html_path = out_path.with_suffix(".html")
        html_path.write_text(html)
        print(f"Saved HTML → {html_path}")
        print("To convert to PDF: pip install weasyprint && python scripts/generate-spec-pdf.py")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
