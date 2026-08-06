# -*- coding: utf-8 -*-
"""
underwriting/tools/pdf_loader.py — PDF 文档加载工具

为核保 Agent 提供 PDF 文件读取能力，对齐用户需求：
  「先用 python 组件读取，不能读取再转图片，然后使用大模型一张张读取」

策略：
1. ``extract_pdf_text`` 优先用 PyMuPDF 提取文本层（文本型 PDF，如系统导出的化验单）。
   提取到的文本交由 ``report_extract_tool._extract_from_text`` 走纯文本模型调用，
   无需视觉编码，更省更快。
2. 文本层为空或过短（扫描件 / 图片型 PDF）→ ``pdf_to_images_b64`` 把每页渲染为
   PNG base64，交由 ``report_extract_tool._extract_from_image_b64`` 逐页多模态识别，
   最后 ``_merge_page_reports`` 合并。

库选型：仅依赖 PyMuPDF（``import fitz``），单一依赖同时覆盖文本提取与页面渲染，
无需 poppler / pdf2image / pytesseract 等外部二进制链路。

设计要点：
- 全部函数**不抛异常**：失败返回空串 / 空列表，由调用方决策回退，避免影响整批处理。
- ``import fitz`` 在函数内部进行（非模块顶层），缺失时返回明确空结果，
  不阻断整个模块导入与其他格式（图片）的处理。
- 页面渲染走内存 base64（``pixmap.tobytes("png")``），不写临时图片文件，无需清理。
- DPI / MAX_PAGES 优先读 ``underwriting.config`` 的 ``PDF_IMAGE_DPI`` /
  ``PDF_MAX_PAGES``（集中配置原则），未配置则用本模块常量兜底。

为后续「文档加载组件」（支持更多格式）预留扩展位：本模块仅处理 PDF，
后续可新增 ``docx_loader.py`` / ``txt_loader.py`` 等同构模块，
再由 ``report_extract_tool`` 按扩展名分发。
"""

import os
import base64

# underwriting/__init__.py 已将项目根注入 sys.path；
# 尝试读取 underwriting.config 的 PDF 参数（集中配置），缺失时用模块常量兜底。
try:
    from underwriting import config as cfg
    _DEFAULT_DPI = int(getattr(cfg, "PDF_IMAGE_DPI", 150))
    _DEFAULT_MAX_PAGES = int(getattr(cfg, "PDF_MAX_PAGES", 20))
except Exception:  # pragma: no cover — config 不可用时仍可用模块常量
    cfg = None
    _DEFAULT_DPI = 150
    _DEFAULT_MAX_PAGES = 20


def is_pdf(path: str) -> bool:
    """按扩展名判定是否 PDF（小写比较 ``.pdf``）。

    不读取文件头，仅做轻量判定；调用方已确保路径存在时再调用。
    """
    if not path:
        return False
    return path.lower().endswith(".pdf")


def extract_pdf_text(pdf_path: str) -> str:
    """用 PyMuPDF 提取全 PDF 文本，逐页拼接（页间用 ``\\n\\n`` 分隔）。

    返回拼接后的纯文本；任一页提取失败则该页贡献空串。

    失败场景（均返回空串，由调用方走图片回退）：
    - PyMuPDF 未安装（``import fitz`` 失败）
    - 文件不存在 / 损坏 / 加密打不开
    - 0 页文档
    """
    try:
        import fitz  # PyMuPDF
    except Exception:
        # PyMuPDF 未安装：返回空串，由调用方回退或报错
        return ""

    try:
        doc = fitz.open(pdf_path)
    except Exception:
        return ""

    try:
        parts = []
        for page in doc:
            try:
                parts.append(page.get_text() or "")
            except Exception:
                parts.append("")
        return "\n\n".join(parts)
    finally:
        try:
            doc.close()
        except Exception:
            pass


def pdf_to_images_b64(pdf_path: str, dpi: int = None, max_pages: int = None) -> list:
    """用 PyMuPDF 把每页渲染为 PNG，返回 base64 字符串列表（不写磁盘）。

    参数：
        pdf_path   PDF 文件路径
        dpi        渲染 DPI（默认读 ``cfg.PDF_IMAGE_DPI``，再兜底 150）；
                   150 对医学报告文本清晰度与视觉编码耗时是较均衡的选择。
        max_pages  最大处理页数（默认读 ``cfg.PDF_MAX_PAGES``，再兜底 20）；
                   超出截断，避免超长 PDF 压垮本地 VLM。

    失败场景（均返回空列表，由调用方报错）：
    - PyMuPDF 未安装
    - 文件不存在 / 损坏 / 加密打不开
    - 0 页文档
    """
    try:
        import fitz  # PyMuPDF
    except Exception:
        return []

    if dpi is None:
        dpi = _DEFAULT_DPI
    if max_pages is None:
        max_pages = _DEFAULT_MAX_PAGES

    try:
        doc = fitz.open(pdf_path)
    except Exception:
        return []

    try:
        # PyMuPDF 的 zoom 因子：dpi / 72（72 是 PDF 默认 DPI）
        zoom = float(dpi) / 72.0
        matrix = fitz.Matrix(zoom, zoom)

        out = []
        page_count = doc.page_count
        limit = min(page_count, max_pages)
        for i in range(limit):
            try:
                page = doc.load_page(i)
                pix = page.get_pixmap(matrix=matrix)
                png_bytes = pix.tobytes("png")
                out.append(base64.b64encode(png_bytes).decode("utf-8"))
            except Exception:
                # 单页渲染失败：跳过该页，继续后续页
                continue
        return out
    finally:
        try:
            doc.close()
        except Exception:
            pass
