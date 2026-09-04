#!/bin/bash
# ============================================================
# AMD Radeon Cloud (RC) 一键部署脚本
# 在 RC 工作区（Jupyter 环境，预装 ROCm + PyTorch）里运行：
#   1. 用 vLLM(ROCm) 启动大模型推理服务
#   2. 安装本项目依赖
#   3. 导入文档、启动网页界面
#
# 用法（在 RC 工作区的 Terminal 里）：
#   bash deploy_rc.sh
# ============================================================
set -e

echo "=============================================="
echo " AMD Radeon Cloud 部署 — Private RAG Agent"
echo "=============================================="

echo ""
echo "[1/6] 检测 AMD GPU ..."
if command -v amd-smi >/dev/null 2>&1; then
    amd-smi static 2>/dev/null | grep -iE "card|gpu" | head -3 || true
    amd-smi monitor -e 2>/dev/null | head -2 || true
elif command -v rocm-smi >/dev/null 2>&1; then
    rocm-smi 2>/dev/null | head -8
else
    echo "未检测到 amd-smi/rocm-smi，尝试用 python 检测..."
    python -c "
import torch
print('PyTorch', torch.__version__)
print('GPU available:', torch.cuda.is_available())
if torch.cuda.is_available():
    print('GPU:', torch.cuda.get_device_name(0))
"
fi

echo ""
echo "[2/6] 确认 vLLM ..."
if command -v vllm >/dev/null 2>&1 || python -c "import vllm" 2>/dev/null; then
    echo "vLLM 已安装 ✓"
else
    echo "安装 vLLM (ROCm)..."
    pip install vllm torchvision --index-url https://mirrors.aliyun.com/pypi/simple/ \
        --extra-index-url https://wheels.vllm.ai/rocm/ 2>&1 | tail -3
fi

echo ""
echo "[3/6] 安装本项目依赖 ..."
pip install -r requirements.txt 2>&1 | tail -2
# RC 上 embedding 用 sentence-transformers（vLLM 只管 LLM，embedding 走 CPU 即可）
pip install sentence-transformers 2>&1 | tail -1

echo ""
echo "[4/6] 启动 vLLM 推理服务（后台）..."
# 优先用 RC 模板预下载的模型（如 /models/Qwen3.6-35B-A3B-AWQ-4bit）
# 否则用 VLLM_MODEL 环境变量，默认 Qwen3-8B
if [ -z "$VLLM_MODEL" ] && ls -d /models/*/ 2>/dev/null | head -1 >/dev/null; then
    VLLM_MODEL=$(ls -d /models/*/ | head -1 | sed 's|/$||')
    echo "检测到 RC 预下载模型: $VLLM_MODEL"
fi
MODEL="${VLLM_MODEL:-Qwen/Qwen3-8B}"
export HIP_VISIBLE_DEVICES=0
if curl -s http://localhost:8000/v1/models >/dev/null 2>&1; then
    echo "vLLM 已在运行，跳过启动"
else
    # 若检测到 RC 预下载模型，用模板官方优化参数启动（ROCm 专用）
    if [ -d "/models/Qwen3.6-35B-A3B-AWQ-4bit" ]; then
        echo "使用 RC 模板官方 vLLM 优化命令 (Qwen3.6-35B-A3B)"
        export PATH=/opt/venv/bin:$PATH
        export VLLM_ROCM_USE_AITER=0
        nohup vllm serve /models/Qwen3.6-35B-A3B-AWQ-4bit \
            --served-model-name qwen3.6 \
            --host 0.0.0.0 --port 8000 \
            --dtype float16 \
            --max-model-len 262144 \
            --max-num-seqs 16 \
            --gpu-memory-utilization 0.90 \
            --kv-cache-dtype int8_per_token_head \
            --attention-backend TRITON_ATTN \
            --enable-auto-tool-choice \
            --tool-call-parser qwen3_coder \
            --reasoning-parser qwen3 \
            > /tmp/vllm.log 2>&1 &
        SERVED_MODEL="qwen3.6"
    else
        nohup vllm serve "$MODEL" \
            --served-model-name qwen \
            --host 0.0.0.0 --port 8000 \
            --gpu-memory-utilization 0.85 \
            > /tmp/vllm.log 2>&1 &
        SERVED_MODEL="qwen"
    fi
    echo "vLLM 启动中 (模型: $MODEL, 日志: /tmp/vllm.log)"
    # 等待 vLLM 就绪
    for i in $(seq 1 60); do
        if curl -s http://localhost:8000/v1/models >/dev/null 2>&1; then
            echo "vLLM 就绪 ✓ ($((i*5))s)"
            break
        fi
        sleep 5
    done
fi

echo ""
echo "[5/6] 切换配置到 vLLM 后端 ..."
# 备份原配置
cp -n config.yaml config.yaml.ollama.bak 2>/dev/null || true
# 用 Python 精确改写（避免 sed 被行尾注释干扰）
python - <<'PYEOF'
import yaml
cfg = yaml.safe_load(open("config.yaml", encoding="utf-8"))
cfg["model"]["backend"] = "vllm"
# 若用 RC 预下载模型，served-model-name 是 qwen3.6
if __import__("os").path.isdir("/models/Qwen3.6-35B-A3B-AWQ-4bit"):
    cfg["model"]["name"] = "qwen3.6"
else:
    cfg["model"]["name"] = "qwen"
cfg["model"]["base_url"] = "http://localhost:8000/v1"
# embedding 与本地开发保持一致（bge-m3, 1024 维），避免向量库跨环境维度不匹配；
# 若向量库在 RC 上重建，也可换更轻量的 bge-small-zh-v1.5（512 维）加速
cfg["embedding"]["backend"] = "sentence_transformers"
cfg["embedding"]["name"] = "BAAI/bge-m3"
cfg["embedding"]["dim"] = 1024
yaml.safe_dump(cfg, open("config.yaml", "w", encoding="utf-8"), allow_unicode=True, sort_keys=False)
print("config.yaml 已切换到 vLLM 后端 + sentence-transformers embedding")
PYEOF

echo ""
echo "[6/6] 验证推理 ..."
python -u -c "
from agent.llm import LLMBackend
llm = LLMBackend()
r = llm.chat([{'role':'user','content':'用一句话介绍你自己'}], max_tokens=64)
print('✅ AMD GPU 推理 OK:', r['content'][:60])
"

echo ""
echo "=============================================="
echo " ✅ 部署完成！在 RC 工作区使用："
echo "    python main.py ingest data/docs/    导入文档"
echo "    python main.py ask '你的问题'        提问"
echo "    python main.py ui                    网页界面 (需端口转发/公开)"
echo "=============================================="
