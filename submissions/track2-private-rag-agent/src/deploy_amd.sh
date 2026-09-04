# AMD ROCm 部署脚本 —— 在 Radeon Cloud / 本地 AMD GPU (Linux) 上一键部署
# 用法: bash deploy_amd.sh

set -e
echo "=== [1/5] 检测 AMD ROCm 环境 ==="
if command -v rocminfo >/dev/null 2>&1; then
    rocminfo | grep -E "Name:|Marketing Name:" | head -4
else
    echo "未检测到 rocminfo，请确认已安装 ROCm 6.x" && exit 1
fi

echo "=== [2/5] 安装 Python 依赖 ==="
pip install -r requirements.txt

echo "=== [3/5] 拉取模型 (Ollama + ROCm) ==="
ollama pull qwen3:8b        # LLM（AMD 上可用更小更快模型，如 qwen3:4b）
ollama pull bge-m3          # Embedding

echo "=== [4/5] 启动 Ollama 服务 ==="
if ! pgrep -x ollama >/dev/null; then
    (ollama serve >/tmp/ollama.log 2>&1 &)
    sleep 3
fi
ollama ps || true

echo "=== [5/5] 验证推理在 GPU 上运行 ==="
python -u -c "
from agent.llm import LLMBackend
llm = LLMBackend()
r = llm.chat([{'role':'user','content':'你好，用一句话回答'}], max_tokens=64)
print('推理 OK:', r['content'][:50])
"
ollama ps   # 应显示 100% GPU

echo ""
echo "✅ 部署完成！开始使用:"
echo "  python main.py ingest data/docs/    # 导入文档"
echo "  python main.py ask '你的问题'        # 提问"
echo "  python main.py ui                    # 网页界面"
