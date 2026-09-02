"""多格式剧本/小说读取：把任意支持格式统一转成纯文本。

支持格式：.txt / .md / .docx / .epub / .pdf（按扩展名分派）。
不支持 .mobi / .azw3（Kindle 私有格式）；如需使用，请先用 Calibre 等工具
转成 .epub 再喂给本流水线。

设计要点：
- 各非 txt 分支把第三方库的 import 放进 try/except，缺库时抛出**清晰的中文
  RuntimeError**（提示安装哪个包），而不是让用户面对 ImportError。
- 未知扩展名不报错：回退按 UTF-8 文本读取（errors="ignore"）。
- 输出统一规整：strip、3+ 连续空行折叠为 2，最终保证为非空字符串
  （读不出任何文本时抛出清晰错误）。
- 通过 ``_LOADERS`` 扩展名注册表分派，新增格式只需登记一个函数。
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Callable

#: 对外公开的受支持扩展名集合（小写，含点）。
SUPPORTED = {".txt", ".md", ".docx", ".epub", ".pdf"}

# 折叠 3 个及以上连续换行（允许行间含空白）为两个换行。
_BLANK_LINES = re.compile(r"\n\s*\n(\s*\n)+")


def _read_txt(path: Path) -> str:
    """.txt / 未知格式：按 UTF-8 读取，无法解码的字节直接忽略。"""
    return path.read_text(encoding="utf-8", errors="ignore")


def _strip_markdown(text: str) -> str:
    """把基础 Markdown 语法转成纯文本（保持简单、稳健）。

    仅处理常见标记：标题 #、强调 */_、行内代码 `、图片/链接、引用 >、列表符号、
    水平分隔线。复杂表格/HTML 不特殊处理，按原文保留。
    """
    out: list[str] = []
    for line in text.splitlines():
        s = line
        s = re.sub(r"^\s{0,3}#{1,6}\s*", "", s)          # 标题
        s = re.sub(r"^\s{0,3}>\s?", "", s)                # 引用
        s = re.sub(r"^\s{0,3}([-*+]|\d+\.)\s+", "", s)    # 列表项符号
        if re.fullmatch(r"\s*([-*_])\s*(\1\s*){2,}", s):  # 水平分隔线 --- *** ___
            continue
        s = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", s)        # 图片
        s = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", s)    # 链接 -> 保留文字
        s = re.sub(r"(\*\*|__)(.+?)\1", r"\2", s)         # 粗体
        s = re.sub(r"(\*|_)(.+?)\1", r"\2", s)            # 斜体
        s = re.sub(r"`([^`]+)`", r"\1", s)                # 行内代码
        out.append(s)
    return "\n".join(out)


def _read_md(path: Path) -> str:
    """.md：先按文本读取，再剥离基础 Markdown 标记。"""
    return _strip_markdown(_read_txt(path))


def _read_docx(path: Path) -> str:
    """.docx：用 python-docx 读取，段落文本以换行拼接。"""
    try:
        import docx  # python-docx
    except ImportError as e:  # pragma: no cover - 环境已装库
        raise RuntimeError("读取 .docx 需要 python-docx，请 pip install python-docx") from e
    doc = docx.Document(str(path))
    return "\n".join(p.text for p in doc.paragraphs)


def _read_epub(path: Path) -> str:
    """.epub：遍历文档项，BeautifulSoup 取纯文本，按书脊顺序拼接。"""
    try:
        import ebooklib
        from ebooklib import epub
    except ImportError as e:  # pragma: no cover - 环境已装库
        raise RuntimeError("读取 .epub 需要 ebooklib，请 pip install ebooklib") from e
    try:
        from bs4 import BeautifulSoup
    except ImportError as e:  # pragma: no cover - 环境已装库
        raise RuntimeError("读取 .epub 需要 beautifulsoup4，请 pip install beautifulsoup4") from e

    book = epub.read_epub(str(path))
    parts: list[str] = []
    for item in book.get_items_of_type(ebooklib.ITEM_DOCUMENT):
        soup = BeautifulSoup(item.get_content(), "html.parser")
        txt = soup.get_text("\n").strip()
        if txt:
            parts.append(txt)
    return "\n\n".join(parts)


def _read_pdf(path: Path) -> str:
    """.pdf：用 pypdf 逐页抽取文本后拼接。"""
    try:
        from pypdf import PdfReader
    except ImportError as e:  # pragma: no cover - 环境已装库
        raise RuntimeError("读取 .pdf 需要 pypdf，请 pip install pypdf") from e
    reader = PdfReader(str(path))
    pages = [(page.extract_text() or "") for page in reader.pages]
    return "\n".join(pages)


#: 扩展名 -> 读取函数 注册表（便于扩展新格式）。
_LOADERS: dict[str, Callable[[Path], str]] = {
    ".txt": _read_txt,
    ".md": _read_md,
    ".docx": _read_docx,
    ".epub": _read_epub,
    ".pdf": _read_pdf,
}


def _normalize(text: str) -> str:
    """统一规整：换行符归一、去首尾空白、折叠多余空行。"""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = _BLANK_LINES.sub("\n\n", text)
    return text.strip()


def load_text(path: str | Path) -> str:
    """读取小说/剧本文件并返回纯文本，按扩展名自动分派。

    支持 .txt/.md/.docx/.epub/.pdf；未知扩展名回退为 UTF-8 文本读取。
    读不出任何文本时抛出清晰的 RuntimeError。
    """
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"输入文件不存在: {p}")

    ext = p.suffix.lower()
    loader = _LOADERS.get(ext, _read_txt)  # 未知扩展名 -> 文本读取，不崩
    text = _normalize(loader(p))
    if not text:
        raise RuntimeError(f"未能从文件中读取到任何文本: {p}（文件可能为空、损坏或为扫描版 PDF）")
    return text
