"""
NodeFlow — 一键下载全部 LoRA (自包含版本)

不依赖 config.py / store_service，直接把所有 HF 镜像链接写死。
使用 urllib 下载，避免依赖 httpx。

用法:
    HF_ENDPOINT=https://hf-mirror.com python download_all_loras.py
    HF_ENDPOINT=https://hf-mirror.com python download_all_loras.py --only sdxl_cyberpunk sdxl_watercolor
"""

import argparse
import os
import sys
import urllib.request
from pathlib import Path

# ---------------------------------------------------------------------------
# 全部 LoRA: (id, 仓库路径, 文件名, 目标路径)
# ---------------------------------------------------------------------------
LORAS = [
    # 通用优化
    ("sdxl_detail_tweaker",
     "LengXuXu/Detail_Tweaker_XL",
     "add-detail-xl.safetensors",
     "/persistent/loras/sdxl/add-detail-xl.safetensors"),
    ("flux_add_details",
     "Shakker-Labs/FLUX.1-dev-LoRA-add-details",
     "FLUX-dev-lora-add_details.safetensors",
     "/persistent/loras/flux/FLUX.1-dev-LoRA-add-details.safetensors"),
    ("flux_realistic_lora",
     "pablobonilla/flux-realistic-lora",
     "lora.safetensors",
     "/persistent/loras/flux/flux-realistic-lora.safetensors"),
    # 风格化
    ("sdxl_cyberpunk",
     "issaccyj/lora-sdxl-cyberpunk",
     "pytorch_lora_weights.safetensors",
     "/persistent/loras/sdxl/cyberpunk.safetensors"),
    ("sdxl_anime",
     "DarkAngelH/Models_100_AnimeLoRA_SDXL",
     "anime_sdxl_v1.safetensors",
     "/persistent/loras/sdxl/anime.safetensors"),
    ("sdxl_watercolor",
     "ostris/watercolor_style_lora_sdxl",
     "watercolor_v1_sdxl.safetensors",
     "/persistent/loras/sdxl/watercolor.safetensors"),
    ("sdxl_oil_painting",
     "chuckma/sdxl-oil-painting-lora",
     "oil-painting.safetensors",
     "/persistent/loras/sdxl/oil_painting.safetensors"),
    ("sdxl_3d_render",
     "suholee/3dAnimation-SDXL-LoRA-v1-50",
     "3dAnimation-SDXL-LoRA-v1-50.safetensors",
     "/persistent/loras/sdxl/3d_render.safetensors"),
    ("sdxl_pixel_art",
     "nerijs/pixel-art-xl",
     "pixel-art-xl.safetensors",
     "/persistent/loras/sdxl/pixel_art.safetensors"),
    ("sdxl_concept_art",
     "nncyberpunk/SDXL1.0_LoRA_ConceptArt_EclipseStyle_Pony",
     "SDXL1.0_LoRA_ConceptArt_EclipseStyle_Pony.safetensors",
     "/persistent/loras/sdxl/concept_art.safetensors"),
    ("sdxl_minimalist",
     "e-n-v-y/envy-shadow-minimalism-xl-01",
     "EnvyShadowMinimalismXL01.safetensors",
     "/persistent/loras/sdxl/minimalist.safetensors"),
]


def build_url(repo: str, filename: str) -> str:
    """基于 HF_ENDPOINT 构造 resolve 直链。"""
    endpoint = os.environ.get("HF_ENDPOINT", "https://huggingface.co").rstrip("/")
    return f"{endpoint}/{repo}/resolve/main/{filename}"


def download_one(lora_id: str, repo: str, filename: str, target: str) -> bool:
    target_path = Path(target)
    target_path.parent.mkdir(parents=True, exist_ok=True)

    # 已存在则跳过
    if target_path.exists() and target_path.stat().st_size > 0:
        print(f"[SKIP] {lora_id}: 已存在 ({target_path.stat().st_size/1e6:.1f} MB)")
        return True

    url = build_url(repo, filename)
    print(f"[GET ] {lora_id}: {url}")
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "NodeFlow/1.0"})
        with urllib.request.urlopen(req, timeout=120) as resp, open(target, "wb") as f:
            total = 0
            while True:
                chunk = resp.read(1024 * 256)
                if not chunk:
                    break
                f.write(chunk)
                total += len(chunk)
        print(f"[OK  ] {lora_id}: {total/1e6:.1f} MB -> {target}")
        return True
    except Exception as exc:  # noqa: BLE001
        print(f"[FAIL] {lora_id}: {exc}")
        if target_path.exists():
            target_path.unlink()
        return False


def main() -> None:
    parser = argparse.ArgumentParser(description="NodeFlow 全部 LoRA 下载")
    parser.add_argument("--only", nargs="+", help="只下载指定 ID")
    args = parser.parse_args()

    ids = {l[0] for l in LORAS}
    if args.only:
        unknown = [i for i in args.only if i not in ids]
        if unknown:
            print(f"未知 ID: {unknown}")
        selected = [l for l in LORAS if l[0] in args.only]
    else:
        selected = LORAS

    print(f"=== 计划下载 {len(selected)} 个 LoRA ===")
    for l in selected:
        print(f"  {l[0]}")

    ok, fail = 0, 0
    for lora_id, repo, filename, target in selected:
        if download_one(lora_id, repo, filename, target):
            ok += 1
        else:
            fail += 1

    print(f"=== 完成: {ok} 成功, {fail} 失败 ===")


if __name__ == "__main__":
    main()