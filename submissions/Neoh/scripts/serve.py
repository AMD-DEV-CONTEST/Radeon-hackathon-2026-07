# -*- coding: utf-8 -*-
"""启动 vLLM 的 OpenAI 兼容推理服务（供 Dify / 任意 OpenAI 客户端接入）。

把本地 Qwen2.5-14B（或其他尺寸）以 OpenAI 兼容 API 暴露出来：
    GET /v1/models
    POST /v1/chat/completions
    POST /v1/embeddings # 若后续用 Dify 自带 RAG 也可复用本地 embedding

Dify 接入：在 Model Provider 里选「OpenAI-API-compatible」，
Base URL 填 http://<本机IP>:8000/v1，API Key 任意非空字符串，
模型名填 served-model-name（默认 qwen2.5-14b）。

ROCm 环境变量与 inference/engine.py 保持一致，必须在 import torch/vllm 前设置。

用法（Linux + AMD GPU / Radeon Cloud，项目根目录）：
    python scripts/serve.py --model qwen2.5-14b
    python scripts/serve.py --model qwen2.5-7b --port 8001
"""

import os
import sys
import argparse
import subprocess

# ---------------------------------------------------------------------------
# ROCm 环境变量（必须在 vLLM / torch 加载前设置，与 engine.py 一致）
# ---------------------------------------------------------------------------
os.environ.setdefault("HSA_OVERRIDE_GFX_VERSION", "11.0.0")
os.environ.setdefault("PYTORCH_ROCM_ARCH", "gfx1100")
os.environ.setdefault("HIP_VISIBLE_DEVICES", "0")
os.environ.setdefault("HSA_ENABLE_SDMA", "0")
os.environ.setdefault("VLLM_WORKER_MULTIPROC_METHOD", "spawn")
os.environ.setdefault("RCCL_NCCL_NCHANNELS", "4")
os.environ.setdefault("RCCL_NCCL_NSOCKETS_PERCHANNEL", "8")
os.environ.setdefault("NCCL_SOCKET_IFNAME", "lo")
os.environ.setdefault("HSA_ENABLE_INTERRUPTIBLE", "0")
# glibc 2.35 (Ubuntu 22.04) 兼容 + flash-attn ROCm 启用（与 install_rocm.sh / app.py 一致）
os.environ.setdefault("FLASH_ATTENTION_TRITON_AMD_ENABLE", "TRUE")
os.environ.setdefault(
    "PYTHONPATH",
    os.path.join(sys.prefix, "lib", "python3.14", "site-packages",
                 "_rocm_sdk_core", "share", "amd_smi"),
)

MODEL_DIR_MAP = {
    "qwen2.5-7b": "./models/Qwen2.5-7B-Instruct",
    "qwen2.5-14b": "./models/Qwen2.5-14B-Instruct",
    "qwen2.5-32b": "./models/Qwen2.5-32B-Instruct",
}


def main():
    ap = argparse.ArgumentParser(description="vLLM OpenAI 兼容服务（ROCm 本地部署）")
    ap.add_argument("--model", default="qwen2.5-14b", choices=list(MODEL_DIR_MAP.keys()))
    ap.add_argument("--host", default="0.0.0.0", help="监听地址（同机 Dify 用 host.docker.internal 或本机IP）")
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--gpu-memory-utilization", type=float, default=0.90)
    ap.add_argument("--dtype", default="float16")
    ap.add_argument("--max-model-len", type=int, default=8192)
    args = ap.parse_args()

    model_path = MODEL_DIR_MAP[args.model]
    if not os.path.exists(model_path):
        sys.exit(
            f"模型未找到: {model_path}\n"
            f"请先下载: python scripts/download_model.py --model {args.model}"
        )

    cmd = [
        sys.executable, "-m", "vllm.entrypoints.openai.api_server",
        "--model", model_path,
        "--served-model-name", args.model,
        "--host", args.host,
        "--port", str(args.port),
        "--gpu-memory-utilization", str(args.gpu_memory_utilization),
        "--dtype", args.dtype,
        "--max-model-len", str(args.max_model_len),
        "--trust-remote-code",
    ]

    print(f"[*] 启动 vLLM OpenAI 兼容服务")
    print(f" 模型 : {args.model} @ {model_path}")
    print(f" 地址 : http://{args.host}:{args.port}/v1")
    print(f" Dify 模型名 : {args.model}")
    print(f"[*] 等待模型加载完成（首次需数十秒~几分钟）...\n")

    try:
        subprocess.run(cmd, check=True)
    except FileNotFoundError:
        sys.exit(
            "未找到 vllm。请先运行 ROCm 安装脚本: bash install_rocm.sh\n"
            "（注意：本机为 AMD ROCm 环境，请勿用 wheels.vllm.ai / 清华源等 CUDA 构建）"
        )
    except KeyboardInterrupt:
        print("\n[*] 服务已停止")


if __name__ == "__main__":
    main()
