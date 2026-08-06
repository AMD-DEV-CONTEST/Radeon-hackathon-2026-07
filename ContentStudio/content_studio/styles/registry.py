"""风格预设注册表 + workflow 加载。"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

WORKFLOWS_DIR = Path(__file__).resolve().parent / "workflows"


@dataclass
class StylePreset:
    id: str
    name: str
    workflow_style: str   # 文件名, 如 "anime.json"     风格迁移
    workflow_t2i: str     # 文件名, 如 "anime_t2i.json"  文生图
    llm_tone: str         # 喂给 LLM 的文风指令
    visual_keywords: str  # 拼进文生图正向提示的视觉关键词


_BUILTIN: list[StylePreset] = [
    StylePreset(
        id="anime", name="动漫风",
        workflow_style="anime.json", workflow_t2i="anime_t2i.json",
        llm_tone="活泼、有二次元感、多用感叹和短句",
        visual_keywords="anime style, vibrant colors, cel shading, detailed",
    ),
    StylePreset(
        id="cyberpunk", name="赛博朋克",
        workflow_style="cyberpunk.json", workflow_t2i="cyberpunk_t2i.json",
        llm_tone="酷炫、未来感、节奏紧凑",
        visual_keywords="cyberpunk, neon lights, futuristic, blade runner style",
    ),
    StylePreset(
        id="watercolor", name="水彩",
        workflow_style="watercolor.json", workflow_t2i="anime_t2i.json",
        llm_tone="柔和、诗意、画面感强",
        visual_keywords="watercolor painting, soft wash, delicate, paper texture",
    ),
    StylePreset(
        id="retro", name="复古",
        workflow_style="retro.json", workflow_t2i="anime_t2i.json",
        llm_tone="怀旧、温情、有年代感",
        visual_keywords="retro vintage, film grain, faded colors, 80s photography",
    ),
    StylePreset(
        id="minimal", name="极简",
        workflow_style="minimal.json", workflow_t2i="anime_t2i.json",
        llm_tone="简洁、克制、留白",
        visual_keywords="minimalist, clean, simple, negative space, flat design",
    ),
    StylePreset(
        id="oil", name="油画",
        workflow_style="oil.json", workflow_t2i="anime_t2i.json",
        llm_tone="厚重、艺术感、细腻",
        visual_keywords="oil painting, thick brush strokes, classical art, rich texture",
    ),
    StylePreset(
        id="ink", name="国风水墨",
        workflow_style="ink.json", workflow_t2i="anime_t2i.json",
        llm_tone="古雅、有意境、含蓄",
        visual_keywords="chinese ink painting, sumi-e, monochrome, brush, traditional",
    ),
    StylePreset(
        id="pixel", name="像素",
        workflow_style="pixel.json", workflow_t2i="anime_t2i.json",
        llm_tone="俏皮、有复古游戏感",
        visual_keywords="pixel art, 8-bit, retro game, blocky pixels",
    ),
]

# 「无」：用原图、不走 ComfyUI。t2i(文生图)已从管线移除，workflow_t2i 字段保留但休眠。
NONE_ID = "none"


def list_presets() -> list[StylePreset]:
    return list(_BUILTIN)


def get_preset(style_id: str) -> StylePreset:
    for p in _BUILTIN:
        if p.id == style_id:
            return p
    raise ValueError(f"未知风格: {style_id}")


def resolve_style(style_id: str) -> StylePreset | None:
    """「无」返回 None（用原图，不走 ComfyUI）；其它解析为预设。"""
    if style_id == NONE_ID:
        return None
    return get_preset(style_id)


def preset_options() -> list[dict]:
    """UI 下拉用：无 + 全部预设，{id, name}。"""
    return [{"id": NONE_ID, "name": "无"}] + [{"id": p.id, "name": p.name} for p in _BUILTIN]


def load_workflow(filename: str) -> dict:
    path = WORKFLOWS_DIR / filename
    return json.loads(path.read_text(encoding="utf-8"))
