# -*- coding: utf-8 -*-
"""一键下载全部模型权重。

用法：
    python scripts/download_models.py              # 下载全部
    python scripts/download_models.py --minimal    # 仅核心模型（重绘 + 轻量超分）

Hugging Face 权重会进入本地 HF 缓存（可用 HF_ENDPOINT=https://hf-mirror.com 使用镜像）；
Real-ESRGAN 权重下载到 ./models 目录。
"""
from __future__ import annotations

import argparse
import os
import urllib.request

ESRGAN_WEIGHTS = {
    "RealESR_general_x4v3.pth": "https://github.com/xinntao/Real-ESRGAN/releases/download/v0.2.5.0/RealESR_general_x4v3.pth",
    "RealESRGAN_x4plus.pth": "https://github.com/xinntao/Real-ESRGAN/releases/download/v0.1.0/RealESRGAN_x4plus.pth",
}

EXTRA_WEIGHTS = {
    "GFPGANv1.4.pth": "https://github.com/TencentARC/GFPGAN/releases/download/v1.3.0/GFPGANv1.4.pth",
    # YuNet 人脸检测（opencv_zoo，Git LFS 文件走 media 端点）
    "face_detection_yunet_2023mar.onnx": "https://media.githubusercontent.com/media/opencv/opencv_zoo/main/models/face_detection_yunet/face_detection_yunet_2023mar.onnx",
}

# GitHub 直连较慢时可用的加速代理（按需自行替换/去掉）
GH_PROXIES = ["", "https://gh-proxy.com/", "https://ghfast.top/"]


def download_file(url: str, dst: str) -> None:
    if os.path.exists(dst):
        print(f"[跳过] 已存在 {dst}")
        return
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    last_err = None
    for proxy in GH_PROXIES:
        full = proxy + url if proxy else url
        try:
            print(f"[下载] {full}\n    -> {dst}")
            urllib.request.urlretrieve(full, dst)
            print("[完成]")
            return
        except Exception as e:  # noqa: BLE001
            last_err = e
            print(f"[失败] {proxy or '直连'}: {e}")
    raise RuntimeError(f"下载失败 {url}: {last_err}")


def hf_download(repo_id: str) -> None:
    from huggingface_hub import snapshot_download
    print(f"[HF] {repo_id}")
    path = snapshot_download(repo_id, allow_patterns=[
        "*.json", "*.txt", "*.safetensors", "*.bin", "scheduler/*", "unet/*",
        "vae/*", "text_encoder/*", "tokenizer/*", "feature_extractor/*", "model_index.json",
    ])
    print(f"    -> {path}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--minimal", action="store_true", help="仅下载核心模型")
    parser.add_argument("--model-dir", default="./models")
    args = parser.parse_args()

    os.makedirs(args.model_dir, exist_ok=True)

    # 1. 超分权重（体积小，优先）
    download_file(ESRGAN_WEIGHTS["RealESR_general_x4v3.pth"],
                  os.path.join(args.model_dir, "RealESR_general_x4v3.pth"))
    if not args.minimal:
        download_file(ESRGAN_WEIGHTS["RealESRGAN_x4plus.pth"],
                      os.path.join(args.model_dir, "RealESRGAN_x4plus.pth"))

    # 2. Stable Diffusion 重绘模型（核心，约 4GB）
    hf_download("stable-diffusion-v1-5/stable-diffusion-inpainting")

    if not args.minimal:
        # 3. img2img / 文生图底模（约 4GB，风格迁移与海报生成共用）
        hf_download("stable-diffusion-v1-5/stable-diffusion-v1-5")
        # 4. BiRefNet 背景移除/素材拆分（约 900MB）
        hf_download("ZhengPeng7/BiRefNet")
        # 5. GFPGAN 人像修复 + YuNet 人脸检测
        for name, url in EXTRA_WEIGHTS.items():
            download_file(url, os.path.join(args.model_dir, name))
        # 6. LCM-LoRA 极速生成（约 130MB，强烈推荐）
        hf_download("latent-consistency/lcm-lora-sdv1-5")

    print("\n说明：")
    print("- LaMa 物体移除模型会在首次使用「物体/水印移除」功能时自动下载（约 200MB）。")
    print("- 如 HF 下载缓慢，可先执行：export HF_ENDPOINT=https://hf-mirror.com")
    print("全部下载完成 ✅")


if __name__ == "__main__":
    main()
