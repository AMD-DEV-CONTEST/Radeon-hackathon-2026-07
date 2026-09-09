#!/usr/bin/env python3
"""ComfyUI 生图桥 —— super-desktop-assistant 调服务器 ComfyUI (Qwen-Image / Anima v1.1)

接口对齐 src/agents/image_gen.py 的 _generate_local:
    python comfyui_gen.py "<prompt>" --size 832x1216 --cfg 1.0 --steps 35 --prefix agent_xxx
输出: stdout 打印生成图片的完整路径
"""
import argparse
import json
import os
import random
import sys
import time
import urllib.request

COMFYUI_URL = "http://localhost:8188"
MODEL_UNET = "miaomiaoRealskin_anima11.safetensors"
MODEL_TXT = "miaomiaoRealskin_anima11_txt.safetensors"
MODEL_VAE = "qwenImage_qwenImageVAE.safetensors"
OUTPUT_DIR = "/opt/ComfyUI/output"
NEGATIVE = "worst quality, low quality, shiny skin, artist name, nude, naked, explicit, nsfw, sex, topless, underwear, lingerie"


def _post(path: str, payload: dict, timeout: int = 30) -> dict:
    req = urllib.request.Request(
        COMFYUI_URL + path,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _get(path: str, timeout: int = 10) -> dict:
    with urllib.request.urlopen(COMFYUI_URL + path, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def build_workflow(prompt: str, w: int, h: int, cfg: float, steps: int, prefix: str) -> dict:
    seed = random.randint(0, 2**31 - 1)
    return {
        "1": {"class_type": "UNETLoader", "inputs": {"unet_name": MODEL_UNET, "weight_dtype": "default"}},
        "2": {"class_type": "CLIPLoader", "inputs": {"clip_name": MODEL_TXT, "type": "qwen_image"}},
        "3": {"class_type": "VAELoader", "inputs": {"vae_name": MODEL_VAE}},
        "4": {"class_type": "CLIPTextEncode", "inputs": {"text": prompt, "clip": ["2", 0]}},
        "5": {"class_type": "CLIPTextEncode", "inputs": {"text": NEGATIVE, "clip": ["2", 0]}},
        "6": {"class_type": "EmptyLatentImage", "inputs": {"width": w, "height": h, "batch_size": 1}},
        "7": {"class_type": "KSampler", "inputs": {
            "model": ["1", 0], "positive": ["4", 0], "negative": ["5", 0],
            "latent_image": ["6", 0], "seed": seed, "steps": steps, "cfg": cfg,
            "sampler_name": "euler_cfg_pp", "scheduler": "simple", "denoise": 1.0,
        }},
        "8": {"class_type": "VAEDecode", "inputs": {"samples": ["7", 0], "vae": ["3", 0]}},
        "9": {"class_type": "SaveImage", "inputs": {"images": ["8", 0], "filename_prefix": prefix}},
    }


def generate(prompt: str, size: str, cfg: float, steps: int, prefix: str,
             poll_timeout: int = 300) -> str:
    w, h = (int(x) for x in size.lower().split("x"))
    wf = build_workflow(prompt, w, h, cfg, steps, prefix)
    resp = _post("/prompt", {"prompt": wf})
    if "prompt_id" not in resp:
        raise RuntimeError(f"ComfyUI 提交失败: {resp}")
    pid = resp["prompt_id"]

    # 轮询 /history/{pid} 直到完成
    start = time.time()
    while time.time() - start < poll_timeout:
        try:
            hist = _get(f"/history/{pid}")
        except Exception:
            hist = {}
        if pid in hist:
            status = hist[pid].get("status", {})
            if status.get("status_str") == "error":
                msgs = status.get("messages", [])
                err = [m[1].get("exception_message", "") for m in msgs if m[0] == "execution_error"]
                raise RuntimeError(f"ComfyUI 执行错误: {err[:1]}")
            outputs = hist[pid].get("outputs", {})
            images = []
            for node_out in outputs.values():
                for img in node_out.get("images", []):
                    images.append(os.path.join(OUTPUT_DIR, img["filename"]))
            if images:
                return images[0]
        time.sleep(2)

    raise RuntimeError(f"ComfyUI 生成超时 ({poll_timeout}s)")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("prompt")
    ap.add_argument("--size", default="832x1216")
    ap.add_argument("--cfg", type=float, default=1.0)
    ap.add_argument("--steps", type=int, default=35)
    ap.add_argument("--prefix", default="agent")
    args = ap.parse_args()

    path = generate(args.prompt, args.size, args.cfg, args.steps, args.prefix)
    print(path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
