#!/usr/bin/env python
"""Convert PROJECT_PROFILE.md to a styled PDF via Chrome headless."""
import markdown
import pathlib
import subprocess
import sys

SRC = pathlib.Path(__file__).parent / "PROJECT_PROFILE.md"
HTML_TMP = pathlib.Path(__file__).parent / "_profile_tmp.html"
OUT = pathlib.Path(__file__).parent / "Qingxi_Rift_Character_Workshop_Project_Profile.pdf"
CHROME = r"C:\Program Files\Google\Chrome\Application\chrome.exe"

CSS = """
body { font-family: 'Segoe UI', Arial, sans-serif; margin: 40px; color: #1a1a2e; font-size: 11pt; line-height: 1.5; }
h1 { color: #0f3460; border-bottom: 3px solid #e94560; padding-bottom: 8px; font-size: 22pt; }
h2 { color: #0f3460; margin-top: 24px; font-size: 15pt; }
h3 { color: #533483; font-size: 12pt; }
table { border-collapse: collapse; width: 100%; margin: 12px 0; }
th, td { border: 1px solid #bbb; padding: 6px 10px; text-align: left; font-size: 10pt; }
th { background: #f2f2f2; }
code { background: #f5f5f5; padding: 1px 4px; border-radius: 3px; font-size: 9.5pt; }
pre { background: #f5f5f5; padding: 10px; border-radius: 4px; overflow-x: auto; font-size: 9pt; }
blockquote { border-left: 3px solid #e94560; margin-left: 0; padding-left: 12px; color: #555; }
"""


def main() -> int:
    md_text = SRC.read_text(encoding="utf-8")
    html_body = markdown.markdown(
        md_text, extensions=["tables", "fenced_code", "sane_lists"]
    )
    html = f"<!DOCTYPE html><html><head><meta charset='utf-8'><style>{CSS}</style></head><body>{html_body}</body></html>"
    HTML_TMP.write_text(html, encoding="utf-8")

    cmd = [
        CHROME,
        "--headless",
        "--disable-gpu",
        "--no-sandbox",
        "--print-to-pdf=" + str(OUT),
        "--print-to-pdf-no-header",
        str(HTML_TMP.resolve()),
    ]
    subprocess.run(cmd, check=True, capture_output=True, timeout=120)
    print("PDF written:", OUT, OUT.stat().st_size, "bytes")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
