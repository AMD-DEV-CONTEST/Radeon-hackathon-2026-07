from typing import Any, Callable
from pydantic import BaseModel


class SkillDefinition(BaseModel):
    name: str
    description: str
    input_schema: dict[str, Any] = {}
    output_schema: dict[str, Any] = {}


SkillFunc = Callable[..., Any]

_REGISTRY: dict[str, tuple[SkillFunc, SkillDefinition]] = {}


SKILL_DEFINITIONS = [
    SkillDefinition(
        name="analyze_reference",
        description="分析参考照片的内容与构图，提取主体与风格建议",
    ),
    SkillDefinition(
        name="style_transfer_image",
        description="根据选定的风格模板对参考图进行风格化",
    ),
    SkillDefinition(
        name="generate_multiview",
        description="从单张图生成多视角一致性图片（前/侧/后/顶）",
    ),
    SkillDefinition(
        name="generate_3d",
        description="调用云端 3D API 生成全彩 3D 网格",
    ),
    SkillDefinition(
        name="generate_depth_map",
        description="从照片生成深度/高度图，用于 2.5D 浮雕",
    ),
    SkillDefinition(
        name="generate_relief_mesh",
        description="从高度图生成 2.5D 可打印网格",
    ),
    SkillDefinition(
        name="postprocess_mesh",
        description="网格修复、壁厚/悬空检查、减面、展 UV",
    ),
    SkillDefinition(
        name="export_model",
        description="导出最终可打印文件（GLB/OBJ/3MF/STL）",
    ),
]


def register(name: str, func: SkillFunc, definition: SkillDefinition | None = None):
    if definition is None:
        definition = next((d for d in SKILL_DEFINITIONS if d.name == name), SkillDefinition(name=name, description=""))
    _REGISTRY[name] = (func, definition)


def get_skill(name: str) -> SkillFunc:
    if name not in _REGISTRY:
        raise ValueError(f"Unknown skill: {name}")
    return _REGISTRY[name][0]


def list_skills() -> list[SkillDefinition]:
    return [d for _, d in _REGISTRY.values()]


# Placeholder skill implementations will be wired to real pipeline functions in director.py

def _analyze_reference_stub(**kwargs) -> dict:
    return {"subject": "unknown", "notes": "stub analysis"}


def _style_transfer_image_stub(**kwargs) -> dict:
    return {"image_path": kwargs.get("image_path")}


def _generate_multiview_stub(**kwargs) -> dict:
    return {"views": []}


def _generate_3d_stub(**kwargs) -> dict:
    return {"model_path": ""}


def _generate_depth_map_stub(**kwargs) -> dict:
    return {"depth_map_path": ""}


def _generate_relief_mesh_stub(**kwargs) -> dict:
    return {"mesh_path": ""}


def _postprocess_mesh_stub(**kwargs) -> dict:
    return {"report": {}}


def _export_model_stub(**kwargs) -> dict:
    return {"exported_path": ""}


# Register all known skills with stub callables for direct skill execution mode.
# The director usually calls the full pipelines instead of individual stubs.
register("analyze_reference", _analyze_reference_stub)
register("style_transfer_image", _style_transfer_image_stub)
register("generate_multiview", _generate_multiview_stub)
register("generate_3d", _generate_3d_stub)
register("generate_depth_map", _generate_depth_map_stub)
register("generate_relief_mesh", _generate_relief_mesh_stub)
register("postprocess_mesh", _postprocess_mesh_stub)
register("export_model", _export_model_stub)
