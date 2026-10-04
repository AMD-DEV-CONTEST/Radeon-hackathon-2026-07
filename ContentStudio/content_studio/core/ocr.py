"""可选的 PaddleOCR 封装；任何失败都优雅降级，不影响主流程。"""
from __future__ import annotations

import logging
from collections.abc import Callable, Iterable

log = logging.getLogger(__name__)


def _is_line(obj) -> bool:
    # paddleocr 2.x 单行结构：[box, (text, score)]，其中 text 是字符串
    return (
        isinstance(obj, (list, tuple))
        and len(obj) == 2
        and isinstance(obj[1], (list, tuple))
        and len(obj[1]) == 2
        and isinstance(obj[1][0], str)
    )


def extract_text(
    image_paths: Iterable[str],
    initializer: Callable[[], object] | None = None,
) -> str:
    paths = list(image_paths)
    try:
        if initializer is not None:
            ocr = initializer()
        else:
            from paddleocr import PaddleOCR
            # 2.x 使用 use_angle_cls/show_log，3.7.0 会因 TypeError 拒绝这些 kwarg；
            # 先按 2.x 构造，失败则退回 3.x 最小构造 PaddleOCR(lang="ch")。
            try:
                ocr = PaddleOCR(use_angle_cls=True, lang="ch", show_log=False)
            except Exception:
                ocr = PaddleOCR(lang="ch")
    except Exception as e:
        log.warning("OCR 初始化失败，已禁用 OCR: %s", e)
        return ""

    lines: list[str] = []
    for p in paths:
        try:
            result = None
            if hasattr(ocr, "ocr"):
                result = ocr.ocr(str(p), cls=True)
            elif hasattr(ocr, "predict"):
                result = ocr.predict(str(p))
            for block in (result or []):
                # paddleocr 2.x: block 可能是单行 [box, (text, score)]
                if _is_line(block):
                    lines.append(block[1][0])
                # 也可能是多行 [[box, (text, score)], ...]
                elif isinstance(block, list):
                    for line in block:
                        if _is_line(line):
                            lines.append(line[1][0])
                # paddleocr 3.x: block 可能是 dict，含 rec_texts
                elif isinstance(block, dict):
                    lines.extend(block.get("rec_texts", []) or [])
        except Exception as e:
            log.warning("OCR 处理 %s 失败: %s", p, e)
    return "\n".join(lines)
