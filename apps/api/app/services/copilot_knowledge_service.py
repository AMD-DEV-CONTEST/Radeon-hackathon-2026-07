"""Load public site knowledge for Copilot (no secrets)."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

_DATA = Path(__file__).resolve().parent.parent / "data" / "copilot_site_knowledge.md"
_MAX_CHARS = 12_000


@lru_cache(maxsize=1)
def load_site_knowledge() -> str:
    if not _DATA.is_file():
        return ""
    text = _DATA.read_text(encoding="utf-8").strip()
    if len(text) > _MAX_CHARS:
        text = text[:_MAX_CHARS] + "\n\n[…知识库已截断…]"
    return text


def page_knowledge_snippet(page: str) -> str:
    """Short hint for fallback / page context."""
    if "/setup" in page:
        return (
            "Setup：在本机终端安装 Local Agent → 信任 https://localhost:8002 → 本页重新检测变绿 → "
            "点「选择机器人」或顶部 Robots → 进入向导。"
        )
    if "/robots/so101" in page:
        return "SO-101 向导：左侧四步 — 连接、遥操作、录制、训练推理。"
    if "/robots" in page:
        return "Robots：有真机且 Agent 已连接时，点 SO-101「进入向导」。没硬件用 Reachy 虚拟模式。"
    if "/training" in page:
        return "Training：需登录；本地训练需 Agent + 数据集。"
    return ""
