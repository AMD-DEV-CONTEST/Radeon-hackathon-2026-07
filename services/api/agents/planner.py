import json
from typing import Any

from agents.base import Plan, SkillStep
from agents.styles import list_styles, StyleTemplate
from agents.llm_client import llm_client


SYSTEM_PROMPT = """You are a 3D production planning agent for a web app that turns one or more photos into 3D-printable models.
Your job is to read the user's request and pick the best style and execution plan.

Available styles (pick one):
{styles}

Rules:
1. Choose the single best style_id based on the user's intent.
2. Choose output_mode: "fullcolor_3d" for full-color 3D models, "relief_2d5" for 2.5D reliefs.
3. If the user asks for 2.5D, a medallion, a coin, a fridge magnet, lithophane, or relief, prefer relief_2d5 styles.
4. Write a short reasoning string in the same language as the user.
5. Return strictly valid JSON matching the required schema.

Required JSON schema:
{{
  "goal": "short description of the user's intent",
  "style_id": "one of the style ids above",
  "output_mode": "fullcolor_3d" or "relief_2d5",
  "user_prompt": "a concise, model-generation-ready prompt that combines the reference image, subject, and chosen style",
  "postprocess_params": {{}},
  "steps": [
    {{"id": "step_1", "skill": "analyze_reference", "description": "...", "params": {{}}, "depends_on": []}},
    ...
  ],
  "reasoning": "..."
}}

Step skills you may use (in order, depends_on as previous step id):
- analyze_reference
- style_transfer_image
- generate_multiview (only for fullcolor_3d)
- generate_3d (only for fullcolor_3d)
- generate_depth_map (only for relief_2d5)
- generate_relief_mesh (only for relief_2d5)
- postprocess_mesh
- export_model
"""


def _build_styles_block() -> str:
    lines = []
    for s in list_styles():
        lines.append(
            f"- id={s.id} | category={s.category} | output_mode={s.output_mode} | name={s.name} | {s.description}"
        )
    return "\n".join(lines)


def _fallback_plan(user_input: str) -> Plan:
    """Deterministic fallback when no LLM key or LLM fails."""
    from agents.styles import STYLE_MAP

    text = (user_input or "").lower()
    text_no_space = text.replace(" ", "")

    # Keyword -> style_id matching (no-space tolerant)
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

    style = STYLE_MAP.get("realistic_3d", list_styles()[0])
    for sid, keywords in style_keywords.items():
        if any(k in text or k.replace(" ", "") in text_no_space for k in keywords):
            style = STYLE_MAP.get(sid, style)
            break

    steps = [
        SkillStep(id="s1", skill="analyze_reference", description="分析上传照片内容"),
        SkillStep(id="s2", skill="style_transfer_image", description=f"应用风格：{style.name}"),
    ]

    if style.output_mode == "fullcolor_3d":
        steps.append(SkillStep(id="s3", skill="generate_multiview", description="合成多视角图"))
        steps.append(SkillStep(id="s4", skill="generate_3d", description="生成 3D 网格"))
    else:
        steps.append(SkillStep(id="s3", skill="generate_depth_map", description="生成深度/高度图"))
        steps.append(SkillStep(id="s4", skill="generate_relief_mesh", description="生成 2.5D 网格"))

    steps.extend(
        [
            SkillStep(id="s5", skill="postprocess_mesh", description="打印检查与修复"),
            SkillStep(id="s6", skill="export_model", description="导出可打印文件"),
        ]
    )

    # Add linear dependencies
    for i in range(1, len(steps)):
        steps[i].depends_on = [steps[i - 1].id]

    return Plan(
        goal=user_input,
        style_id=style.id,
        output_mode=style.output_mode,
        user_prompt=f"{user_input}, {style.style_prompt}",
        postprocess_params=style.postprocess_params,
        steps=steps,
        reasoning="未检测到 LLM key，使用默认规则选择风格与计划。",
    )


def plan_from_request(user_input: str) -> Plan:
    """Generate a Plan from a user's natural language request."""
    styles_block = _build_styles_block()
    system = SYSTEM_PROMPT.format(styles=styles_block)

    fallback = _fallback_plan(user_input)
    fallback_json = json.loads(fallback.model_dump_json())

    result = llm_client.chat_json(
        system=system,
        user=user_input,
        schema={
            "type": "object",
            "properties": {
                "goal": {"type": "string"},
                "style_id": {"type": "string"},
                "output_mode": {"type": "string", "enum": ["fullcolor_3d", "relief_2d5"]},
                "user_prompt": {"type": "string"},
                "postprocess_params": {"type": "object"},
                "steps": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "id": {"type": "string"},
                            "skill": {"type": "string"},
                            "description": {"type": "string"},
                            "params": {"type": "object"},
                            "depends_on": {"type": "array", "items": {"type": "string"}},
                        },
                        "required": ["id", "skill", "description"],
                    },
                },
                "reasoning": {"type": "string"},
            },
            "required": ["goal", "style_id", "output_mode", "user_prompt", "steps", "reasoning"],
        },
        fallback=fallback_json,
    )

    # Merge fallback defaults for safety if LLM misses fields
    plan_data = fallback_json.copy()
    plan_data.update(result)
    return Plan(**plan_data)
