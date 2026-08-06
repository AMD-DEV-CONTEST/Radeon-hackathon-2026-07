from pydantic import BaseModel
from typing import Literal


class StyleTemplate(BaseModel):
    id: str
    name: str
    description: str
    category: Literal["3d", "relief_2d5", "stylized_3d"]
    output_mode: Literal["fullcolor_3d", "relief_2d5"]
    style_prompt: str
    negative_prompt: str = ""
    postprocess_params: dict = {}
    sample_image_url: str = ""


STYLE_CATALOG: list[StyleTemplate] = [
    # 全彩 3D 风格
    StyleTemplate(
        id="realistic_3d",
        name="Realistic 3D",
        description="High-fidelity, photorealistic look; great for people, pets, and object mementos",
        category="3d",
        output_mode="fullcolor_3d",
        style_prompt="photorealistic 3D model, highly detailed, faithful to reference, soft natural lighting, clean background",
        postprocess_params={"wall_thickness_mm": 2.0, "target_height_mm": 80},
    ),
    StyleTemplate(
        id="cartoon_3d",
        name="Cartoon 3D",
        description="Big eyes, rounded proportions, saturated colors; perfect for pets, kids, and IP characters",
        category="3d",
        output_mode="fullcolor_3d",
        style_prompt="cute 3D cartoon character, chibi style, smooth rounded shapes, vibrant colors, glossy material, clean background",
        postprocess_params={"wall_thickness_mm": 2.0, "target_height_mm": 60},
    ),
    StyleTemplate(
        id="lowpoly_3d",
        name="Low Poly 3D",
        description="Geometric faceted surfaces and low-poly art; ideal for desk ornaments and decoration",
        category="3d",
        output_mode="fullcolor_3d",
        style_prompt="low poly 3D art, faceted geometric surfaces, vibrant flat colors, minimal details, stylized",
        postprocess_params={"wall_thickness_mm": 2.5, "target_height_mm": 70, "decimate_ratio": 0.3},
    ),
    StyleTemplate(
        id="voxel_3d",
        name="Voxel 3D",
        description="Blocky voxel style reminiscent of Minecraft / voxel art",
        category="stylized_3d",
        output_mode="fullcolor_3d",
        style_prompt="voxel art 3D model, made of small cubes, Minecraft style, bright colors, blocky silhouette",
        postprocess_params={"wall_thickness_mm": 2.0, "target_height_mm": 64},
    ),
    StyleTemplate(
        id="clay_3d",
        name="Clay 3D",
        description="Soft clay / pottery texture for a handcrafted keepsake feel",
        category="stylized_3d",
        output_mode="fullcolor_3d",
        style_prompt="claymation 3D model, soft clay texture, fingerprint details, matte material, warm studio lighting",
        postprocess_params={"wall_thickness_mm": 2.5, "target_height_mm": 70},
    ),
    StyleTemplate(
        id="sketch_3d",
        name="Sketch 3D",
        description="Pencil-line / sculpted white-model style for artistic display pieces",
        category="stylized_3d",
        output_mode="fullcolor_3d",
        style_prompt="3D model in pencil sketch style, contour lines, monochrome, artistic sculpture look, clean background",
        postprocess_params={"wall_thickness_mm": 2.0, "target_height_mm": 75},
    ),
    # 2.5D relief styles
    StyleTemplate(
        id="relief_embossed",
        name="Embossed Relief",
        description="Raised relief from a photo; great for medals, plaques, and fridge magnets",
        category="relief_2d5",
        output_mode="relief_2d5",
        style_prompt="embossed relief, high contrast grayscale depth map, smooth gradients, portrait or object centered, no background",
        postprocess_params={"base_thickness_mm": 3.0, "relief_height_mm": 4.0, "invert": False},
    ),
    StyleTemplate(
        id="relief_lithophane",
        name="Lithophane Relief",
        description="Thickness-variation translucency; best printed with light resin or PLA",
        category="relief_2d5",
        output_mode="relief_2d5",
        style_prompt="lithophane height map, grayscale, high contrast, portrait centered, backlit ready, no color",
        postprocess_params={"base_thickness_mm": 0.5, "relief_height_mm": 3.0, "invert": False},
    ),
    StyleTemplate(
        id="relief_coin",
        name="Coin / Medallion Relief",
        description="Circular base with a metallic look; suitable for commemorative coins or keychains",
        category="relief_2d5",
        output_mode="relief_2d5",
        style_prompt="coin medallion relief, circular frame, high contrast depth map, metallic look, centered portrait or emblem",
        postprocess_params={"base_thickness_mm": 2.0, "relief_height_mm": 1.5, "shape": "circular", "invert": False},
    ),
    StyleTemplate(
        id="relief_silhouette",
        name="Silhouette Relief",
        description="Strong outline silhouette style for pendants and decorative plates",
        category="relief_2d5",
        output_mode="relief_2d5",
        style_prompt="silhouette relief, strong outer contour, minimal internal details, flat layers, high contrast depth map",
        postprocess_params={"base_thickness_mm": 2.0, "relief_height_mm": 2.5, "invert": False},
    ),
]

STYLE_MAP = {s.id: s for s in STYLE_CATALOG}


def get_style(style_id: str) -> StyleTemplate:
    if style_id not in STYLE_MAP:
        return STYLE_MAP["realistic_3d"]
    return STYLE_MAP[style_id]


def list_styles() -> list[StyleTemplate]:
    return STYLE_CATALOG
