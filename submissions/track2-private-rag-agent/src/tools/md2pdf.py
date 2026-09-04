# -*- coding: utf-8 -*-
"""轻量 Markdown → PDF 转换器（reportlab，支持中文）。

为提交材料把英文/中文 Markdown 转成排版干净的 PDF。
支持的语法：标题(#/##/###/####)、正文、无序/有序列表、表格、代码块、
粗体、行内代码、分隔线、引用块。其余语法按纯文本处理。
用法：python tools/md2pdf.py in.md out.pdf
"""
import os
import re
import sys

from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.lib import colors
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (SimpleDocTemplate, Paragraph, Spacer, Table,
                                TableStyle, Preformatted, HRFlowable)

# 中文字体（Windows）
_FONT_CANDIDATES = [
    ("C:/Windows/Fonts/msyh.ttc", "msyh"),
    ("C:/Windows/Fonts/msyh.ttf", "msyh"),
    ("C:/Windows/Fonts/simhei.ttf", "simhei"),
    ("C:/Windows/Fonts/simsun.ttc", "simsun"),
]
_BOLD_CANDIDATES = [
    ("C:/Windows/Fonts/msyhbd.ttc", "msyhbd"),
    ("C:/Windows/Fonts/simhei.ttf", "simhei"),
]

FONT = "Helvetica"
FONT_BOLD = "Helvetica-Bold"
FONT_MONO = "Courier"

# 代码块字体：Courier(WinAnsi) 缺 box-drawing 字符（架构图 │┌─ 等会渲染成 ■）。
# Consolas 等宽且覆盖 U+2500 段，优先使用；无则退回 Courier。
for _p in ("C:/Windows/Fonts/consola.ttf", "C:/Windows/Fonts/Consolas.ttf",
           "C:/Program Files/Microsoft Office/root/vfs/Windows/Fonts/consola.ttf"):
    if os.path.exists(_p):
        try:
            pdfmetrics.registerFont(TTFont("consolas", _p))
            FONT_MONO = "consolas"
        except Exception:
            pass
        break

for path, name in _FONT_CANDIDATES:
    if os.path.exists(path):
        pdfmetrics.registerFont(TTFont(name, path))
        FONT = name
        break
for path, name in _BOLD_CANDIDATES:
    if os.path.exists(path):
        pdfmetrics.registerFont(TTFont(name, path))
        FONT_BOLD = name
        break

# 主风格
S = {
    "h1": ParagraphStyle("h1", fontName=FONT_BOLD, fontSize=19, leading=24,
                         textColor=colors.HexColor("#B0131B"), spaceBefore=14, spaceAfter=8),
    "h2": ParagraphStyle("h2", fontName=FONT_BOLD, fontSize=15, leading=20,
                         textColor=colors.HexColor("#B0131B"), spaceBefore=12, spaceAfter=6),
    "h3": ParagraphStyle("h3", fontName=FONT_BOLD, fontSize=12.5, leading=17,
                         textColor=colors.HexColor("#22272E"), spaceBefore=9, spaceAfter=4),
    "h4": ParagraphStyle("h4", fontName=FONT_BOLD, fontSize=11, leading=15,
                         spaceBefore=7, spaceAfter=3),
    "body": ParagraphStyle("body", fontName=FONT, fontSize=10, leading=15,
                           textColor=colors.HexColor("#1F2328"), spaceAfter=5),
    "bullet": ParagraphStyle("bullet", fontName=FONT, fontSize=10, leading=15,
                             leftIndent=14, bulletIndent=4, spaceAfter=3),
    "code": ParagraphStyle("code", fontName=FONT_MONO, fontSize=8, leading=11,
                           textColor=colors.HexColor("#24292E")),
    "quote": ParagraphStyle("quote", fontName=FONT, fontSize=10, leading=15,
                            leftIndent=12, textColor=colors.HexColor("#57606A"),
                            spaceAfter=5),
}

_INLINE_RE = re.compile(r"(`[^`]+`|\*\*[^*]+\*\*|\*[^*]+\*)")
_CODE_RE = re.compile(r"```(\w+)?\s*\n(.*?)```", re.S)


def _escape(text: str) -> str:
    return (text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


def _inline(text: str) -> str:
    """转义 + 渲染行内粗体/行内代码为 reportlab 可用的 <b>/<font> 标签。"""
    out = []

    def repl(m):
        t = m.group(0)
        if t.startswith("`"):
            return f'<font face="{FONT_MONO}" size="8">{_escape(t[1:-1])}</font>'
        if t.startswith("**"):
            return f"<b>{_escape(t[2:-2])}</b>"
        return f"<i>{_escape(t[1:-1])}</i>"

    # 先分段处理行内标记
    pos = 0
    for m in _INLINE_RE.finditer(text):
        out.append(_escape(text[pos:m.start()]))
        out.append(repl(m))
        pos = m.end()
    out.append(_escape(text[pos:]))
    return "".join(out)


def _parse_table(block: str) -> Table:
    rows = []
    for line in block.strip().splitlines():
        line = line.strip().strip("|")
        if re.match(r"^[\s:|-]+$", line):   # 分隔行
            continue
        cells = [c.strip() for c in line.split("|")]
        rows.append([Paragraph(_inline(c), S["body"]) for c in cells])
    if not rows:
        return None
    col_w = [min(45 * mm, 175 * mm / max(len(rows[0]), 1))] * max(len(rows[0]), 1)
    t = Table(rows, colWidths=col_w, repeatRows=1)
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#F6F8FA")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.HexColor("#B0131B")),
        ("FONTNAME", (0, 0), (-1, -1), FONT),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#D0D7DE")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    return t


def md_to_pdf(md_text: str, out_pdf: str):
    doc = SimpleDocTemplate(out_pdf, pagesize=A4,
                            leftMargin=20 * mm, rightMargin=20 * mm,
                            topMargin=18 * mm, bottomMargin=18 * mm,
                            title="Private RAG Agent",
                            author="Private RAG Agent Team")
    story = []

    # 按代码块切分。注意 re.split 会插入捕获组：
    # parts = [text, lang, code, text, lang, code, ...]，lang 组在无语言标注时为 None
    parts = _CODE_RE.split(md_text)
    for i in range(0, len(parts), 3):
        body = parts[i]
        if i + 2 < len(parts):
            code = parts[i + 2].strip("\n")
            story.append(Preformatted(code, S["code"]))
            story.append(Spacer(1, 4))

        lines = body.splitlines()
        para = []
        in_list = False
        list_type = None  # '-' or '1.' or '>'

        def flush_para():
            nonlocal para
            if para:
                text = " ".join(para).strip()
                if text:
                    story.append(Paragraph(_inline(text), S["body"]))
                para = []

        def flush_list():
            nonlocal in_list
            in_list = False

        for line in lines:
            line = line.rstrip()
            if not line.strip():
                flush_para()
                flush_list()
                continue
            if line.startswith("```"):
                continue
            h = re.match(r"^(#{1,6})\s+(.*)$", line)
            if h:
                flush_para(); flush_list()
                level = len(h.group(1))
                story.append(Paragraph(_inline(h.group(2)), S[f"h{min(level, 4)}"]))
                continue
            if line.strip() == "---" or line.strip() == "***":
                flush_para(); flush_list()
                story.append(HRFlowable(width="100%", thickness=0.6,
                                        color=colors.HexColor("#D0D7DE"),
                                        spaceBefore=4, spaceAfter=4))
                continue
            if line.startswith("|"):
                flush_para(); flush_list()
                tbl = _parse_table("\n".join(
                    x for x in lines[lines.index(line):]
                    if x.strip() and (x.startswith("|") or re.match(r"^[\s:|-]+$", x))))
                story.append(tbl)
                # 跳过该表格剩余行
                while lines and (lines[0].startswith("|") or re.match(r"^[\s:|-]+$", lines[0].strip())):
                    lines.pop(0)
                continue
            m = re.match(r"^(\s*)[-*+]\s+(.*)$", line)
            if m:
                flush_para()
                story.append(Paragraph(_inline(m.group(2)), S["bullet"],
                                       bulletText="•"))
                in_list = True
                continue
            m = re.match(r"^(\s*)\d+[.)]\s+(.*)$", line)
            if m:
                flush_para()
                story.append(Paragraph(_inline(m.group(2)), S["bullet"],
                                       bulletText="·"))
                in_list = True
                continue
            if line.startswith(">"):
                flush_para(); flush_list()
                story.append(Paragraph(_inline(line.lstrip("> ")), S["quote"]))
                continue
            para.append(line)

        flush_para()
        flush_list()

    # 注意：reportlab 5.x 的 build() 会清空传入的 story 列表，计数需在 build 前取
    n = len(story)
    doc.build(story)
    return n


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print(__doc__)
        sys.exit(1)
    src, dst = sys.argv[1], sys.argv[2]
    text = open(src, encoding="utf-8").read()
    n = md_to_pdf(text, dst)
    print(f"OK: {src} -> {dst} ({n} flowables)")
