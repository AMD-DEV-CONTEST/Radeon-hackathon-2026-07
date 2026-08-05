"""Render docs/project-profile.md and docs/poster.html to PDF.
Uses Microsoft Edge headless on Windows, chromium/google-chrome on Linux.

    python scripts/build_pdfs.py
"""
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs"

PROFILE_CSS = """
body { font-family: 'Segoe UI', Arial, sans-serif; color: #1a1c22; max-width: 900px;
       margin: 0 auto; padding: 28px 36px; line-height: 1.5; font-size: 13.5px; }
h1 { color: #ED1C24; border-bottom: 3px solid #ED1C24; padding-bottom: 8px; }
h2 { color: #b3151b; margin-top: 26px; }
table { border-collapse: collapse; width: 100%; margin: 10px 0; }
th, td { border: 1px solid #d6d6dc; padding: 6px 9px; text-align: left; font-size: 12.5px; }
th { background: #f6f6f8; }
code, pre { font-family: Consolas, monospace; background: #f4f4f6; }
img { max-width: 100%; border: 1px solid #e0e0e6; border-radius: 6px; }
pre { padding: 10px; border-radius: 6px; font-size: 10.5px; line-height: 1.35; overflow: hidden; }
strong { color: #111; }
"""


def find_browser() -> list[str]:
    candidates = [
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
        shutil.which("msedge"), shutil.which("google-chrome"),
        shutil.which("chromium"), shutil.which("chromium-browser"),
    ]
    for c in candidates:
        if c and Path(c).exists():
            return [c]
    sys.exit("no Edge/Chrome/Chromium found for PDF rendering")


def html_to_pdf(browser: list[str], html: Path, pdf: Path):
    import tempfile

    with tempfile.TemporaryDirectory() as profile:
        subprocess.run(
            browser + [
                "--headless=new", "--disable-gpu", "--no-first-run",
                f"--user-data-dir={profile}", "--no-pdf-header-footer",
                "--virtual-time-budget=8000",
                f"--print-to-pdf={pdf}", html.resolve().as_uri(),
            ],
            check=True, timeout=120,
        )
    print(f"wrote {pdf} ({pdf.stat().st_size // 1024} KB, {page_count(pdf)} page(s))")


def page_count(pdf: Path) -> int:
    """Count pages without a PDF library — /Type /Page objects in the raw file."""
    import re

    data = pdf.read_bytes()
    return len(re.findall(rb"/Type\s*/Page[^s]", data)) or 1


def markdown_to_html(md_path: Path) -> Path:
    import markdown

    text = md_path.read_text(encoding="utf-8")
    bench = DOCS / "benchmark.md"
    if "<!-- BENCHMARK_TABLE -->" in text and bench.exists():
        injected = bench.read_text(encoding="utf-8").replace("# ", "#### ", 1)
        text = text.replace("<!-- BENCHMARK_TABLE -->", injected)
    body = markdown.markdown(
        text,
        extensions=["tables", "fenced_code"],
    )
    html_path = md_path.with_suffix(".build.html")
    html_path.write_text(
        f"<!doctype html><html><head><meta charset='utf-8'>"
        f"<style>{PROFILE_CSS}</style></head><body>{body}</body></html>",
        encoding="utf-8",
    )
    return html_path


def main():
    browser = find_browser()
    profile_html = markdown_to_html(DOCS / "project-profile.md")
    html_to_pdf(browser, profile_html, DOCS / "project-profile.pdf")
    profile_html.unlink()
    poster = DOCS / "poster.pdf"
    html_to_pdf(browser, DOCS / "poster.html", poster)
    if page_count(poster) != 1:
        sys.exit(f"ERROR: poster must be a single page, got {page_count(poster)} — "
                 "content overflows the 420x297mm canvas")


if __name__ == "__main__":
    main()
