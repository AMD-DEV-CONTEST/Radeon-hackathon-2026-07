"""Local Markdown-to-HTML export."""

from __future__ import annotations

from html import escape
from pathlib import Path


class HtmlExporter:
    def export(self, markdown_text: str, target: Path) -> Path:
        destination = target.resolve()
        destination.parent.mkdir(parents=True, exist_ok=True)
        try:
            import markdown  # type: ignore[import-untyped]

            body = markdown.markdown(
                markdown_text,
                extensions=["tables", "fenced_code"],
            )
        except ImportError:
            body = f"<pre>{escape(markdown_text)}</pre>"
        document = (
            '<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width,initial-scale=1">'
            "<title>BuildGuard-Radeon Report</title>"
            "<style>body{font-family:sans-serif;max-width:1000px;margin:2rem auto;"
            "padding:0 1rem;line-height:1.65}code{background:#eee;padding:.1rem .3rem}"
            "blockquote{border-left:4px solid #d97706;padding-left:1rem;color:#555}</style>"
            f"</head><body>{body}</body></html>"
        )
        temporary = destination.with_name(f".{destination.name}.tmp")
        temporary.write_text(document, encoding="utf-8")
        temporary.replace(destination)
        return destination
