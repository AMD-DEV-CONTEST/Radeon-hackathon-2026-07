import json
from typing import Any

from agents.base import Plan
from agents.styles import STYLE_MAP
from agents.llm_client import llm_client


SYSTEM_PROMPT = """You are a helpful assistant inside a 3D-printable model generation app.
The user is chatting with the AI Director. Parse the user's intent and return a structured action.

Possible action types:
- "update_style": change the selected style. Provide new style_id.
- "update_params": adjust postprocess parameters (e.g., base_thickness_mm, relief_height_mm, target_height_mm, wall_thickness_mm).
- "regenerate": restart the whole pipeline with the current plan.
- "regenerate_step": regenerate a specific step. Provide step_id (one of: s2, s3, s4, s5, s6).
- "general": just respond conversationally, no action needed.

Available style IDs:
{style_ids}

Respond ONLY in valid JSON with this schema:
{{
  "action": "update_style|update_params|regenerate|regenerate_step|general",
  "params": {{}},
  "response": "a friendly Chinese reply to the user"
}}
"""


def _fallback_parse(message: str, plan: Plan | None) -> dict[str, Any]:
    text = message.lower()
    text_no_space = text.replace(" ", "")

    style_keywords = {
        "relief_embossed": ["浮雕", "relief", "纪念币", "medal", "奖牌"],
        "relief_lithophane": ["lithophane", "透光", "透光浮雕"],
        "relief_coin": ["硬币", "coin"],
        "relief_silhouette": ["剪影", "silhouette"],
        "cartoon_3d": ["卡通", "cartoon", "q版", "chibi"],
        "lowpoly_3d": ["低多边形", "lowpoly", "low poly", "低面"],
        "voxel_3d": ["体素", "voxel", "像素", "minecraft"],
        "clay_3d": ["粘土", "clay", "陶土"],
        "sketch_3d": ["素描", "sketch", "线稿"],
    }

    # Style switching
    for sid, style in STYLE_MAP.items():
        if style.name in message or sid in text:
            return {
                "action": "update_style",
                "params": {"style_id": sid},
                "response": f"好的，已切换到风格：{style.name}。我会用它的风格重新生成。",
            }
        keywords = style_keywords.get(sid, [])
        if any(k in text or k.replace(" ", "") in text_no_space for k in keywords):
            return {
                "action": "update_style",
                "params": {"style_id": sid},
                "response": f"好的，已切换到风格：{style.name}。我会用它的风格重新生成。",
            }

    # Param adjustments (crude rule matching)
    params = {}
    if "厚" in message or "加厚" in message or "thicker" in text:
        params["base_thickness_mm"] = 5.0
    if "高" in message or "height" in text:
        params["relief_height_mm"] = 5.0
    if "薄" in message or "thin" in text:
        params["base_thickness_mm"] = 1.5

    if params:
        return {
            "action": "update_params",
            "params": params,
            "response": f"已调整参数：{params}。",
        }

    if "重新生成" in message or "regenerate" in text or "再来" in message:
        return {"action": "regenerate", "params": {}, "response": "好的，正在重新生成。"}

    return {
        "action": "general",
        "params": {},
        "response": "收到，我会记住你的需求。你可以在左侧上传照片并点击生成。",
    }


def parse_chat_message(message: str, plan: Plan | None = None) -> dict[str, Any]:
    style_ids = ", ".join(STYLE_MAP.keys())
    system = SYSTEM_PROMPT.format(style_ids=style_ids)

    fallback = _fallback_parse(message, plan)

    result = llm_client.chat_json(
        system=system,
        user=message,
        schema={
            "type": "object",
            "properties": {
                "action": {"type": "string", "enum": ["update_style", "update_params", "regenerate", "regenerate_step", "general"]},
                "params": {"type": "object"},
                "response": {"type": "string"},
            },
            "required": ["action", "params", "response"],
        },
        fallback=fallback,
    )

    # Ensure fallback fields exist if LLM malforms
    data = fallback.copy()
    data.update(result)
    return data
