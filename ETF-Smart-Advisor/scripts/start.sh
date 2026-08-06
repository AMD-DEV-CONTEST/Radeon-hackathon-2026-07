#!/bin/bash
# scripts/start.sh - Service startup script

set -e

echo "=============================================="
echo "🚀 Starting ETF-Smart Advisor"
echo "=============================================="

# 1. Get project root directory
PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$PROJECT_DIR"

# 2. Activate virtual environment
echo ""
echo "📦 Activating virtual environment..."
if [ -d "etfadvisorvenv" ]; then
    source etfadvisorvenv/bin/activate
else
    echo "❌ Virtual environment not found, please run setup_env.sh first"
    exit 1
fi

# 3. 从 config.py 读取配置
echo ""
echo "📖 Reading configuration from app/config.py..."

# 使用 Python 读取配置
read_config() {
    python -c "
import sys
from pathlib import Path
sys.path.insert(0, str(Path('.').resolve()))
try:
    from app.config import LLM_MODEL_PATH, LLM_MODEL_NAME, LLM_MODEL_ID, VLLM_CONFIG
    print(f'MODEL_PATH={LLM_MODEL_PATH}')
    print(f'MODEL_NAME={LLM_MODEL_NAME}')
    print(f'MODEL_ID={LLM_MODEL_ID}')
    print(f'VLLM_PORT={VLLM_CONFIG.get(\"port\", 8000)}')
    print(f'VLLM_GPU_MEM={VLLM_CONFIG.get(\"gpu_memory_utilization\", 0.85)}')
    print(f'VLLM_MAX_MODEL_LEN={VLLM_CONFIG.get(\"max_model_len\", 8192)}')
    print(f'VLLM_ENABLED={VLLM_CONFIG.get(\"enabled\", True)}')
except ImportError as e:
    print(f'ERROR={e}', file=sys.stderr)
    sys.exit(1)
"
}

# 读取配置
CONFIG_OUTPUT=$(read_config)
if [ $? -ne 0 ]; then
    echo "❌ Failed to read config.py"
    echo "   Please ensure app/config.py exists and contains LLM_MODEL_PATH, LLM_MODEL_NAME, LLM_MODEL_ID, VLLM_CONFIG"
    exit 1
fi

# 解析配置
eval "$CONFIG_OUTPUT"

# 检查必要配置是否存在
if [ -z "$MODEL_PATH" ] || [ -z "$MODEL_NAME" ] || [ -z "$MODEL_ID" ]; then
    echo "❌ LLM_MODEL_PATH, LLM_MODEL_NAME or LLM_MODEL_ID not set in config.py"
    exit 1
fi

echo "  ✅ Model path: $MODEL_PATH"
echo "  ✅ Model name: $MODEL_NAME"
echo "  ✅ Model ID: $MODEL_ID"
echo "  ✅ vLLM enabled in config: $VLLM_ENABLED"
echo "  ✅ vLLM port: $VLLM_PORT"
echo "  ✅ GPU memory: $VLLM_GPU_MEM"
echo "  ✅ Max model len: $VLLM_MAX_MODEL_LEN"

# 4. Set GPU optimization environment variables
echo ""
echo "🔧 Setting GPU optimization environment variables..."
export PYTORCH_ROCM_ALLOC_CONF="max_split_size_mb:128,expandable_segments:True"
export PYTORCH_ALLOC_CONF="expandable_segments:True"
export TORCH_ROCM_GRAPH=1
export OMP_NUM_THREADS=1
export MKL_NUM_THREADS=1
export VLLM_ENGINE_READY_TIMEOUT_S=1800

# 5. Check ROCm environment
echo ""
echo "🔍 Checking ROCm environment..."
if command -v rocm-smi &> /dev/null; then
    echo "✅ ROCm detected successfully!"
    rocm-smi --showproductname
else
    echo "⚠️ ROCm not detected, using CPU mode"
fi

# 6. Check AMD GPU
echo ""
echo "🔍 Checking AMD GPU..."
if [ -d /dev/dri ]; then
    echo "✅ AMD GPU detected"
    export ROCM_VISIBLE_DEVICES=0
else
    echo "⚠️ AMD GPU not detected"
fi

# 7. Check VRAM
echo ""
echo "💾 Checking VRAM..."
if command -v rocm-smi &> /dev/null; then
    rocm-smi --showmeminfo vram
fi

# 8. Check Python dependencies
echo ""
echo "🔍 Checking Python dependencies..."
MISSING_PKGS=""
for pkg in torch transformers fastapi uvicorn pymilvus sentence-transformers; do
    if ! python -c "import $pkg" 2>/dev/null; then
        MISSING_PKGS="$MISSING_PKGS $pkg"
    fi
done
if [ -n "$MISSING_PKGS" ]; then
    echo "  ⚠️ Installing missing packages:$MISSING_PKGS"
    pip install $MISSING_PKGS
else
    echo "  ✅ All dependencies installed"
fi

# 9. Check Qwen model
echo ""
echo "🔍 Checking Qwen model..."

if [ ! -d "$MODEL_PATH" ]; then
    echo "  ❌ Model not found at: $MODEL_PATH"
    echo "  💡 Please check LLM_MODEL_PATH in app/config.py"
    echo "  💡 Or run setup_env.sh to download the model"
    exit 1
fi

# 检查模型文件是否完整
if [ ! -f "$MODEL_PATH/config.json" ]; then
    echo "  ❌ Model config.json not found. Model may be incomplete."
    exit 1
fi

echo "  ✅ Model exists at: $MODEL_PATH"
echo "  ✅ Model files verified"

# 10. Check Milvus Lite
echo ""
echo "🔍 Checking Milvus Lite..."
python -c "from app.milvus_client import get_milvus_client; client = get_milvus_client(); print(f'✅ Milvus Lite: {client.get_stats()}')" 2>/dev/null || echo "  ⚠️ Milvus Lite will start on demand"

# 11. Check ports
echo ""
echo "🔍 Checking ports..."
check_port() {
    local port=$1
    if lsof -i :$port > /dev/null 2>&1; then
        echo "  ⚠️ Port $port is already in use"
        return 1
    else
        echo "  ✅ Port $port is available"
        return 0
    fi
}

check_port 7860 || echo "  💡 Web service may fail if port 7860 is occupied"
check_port $VLLM_PORT || echo "  💡 vLLM may fail if port $VLLM_PORT is occupied"

# 12. Determine whether to use vLLM
echo ""
echo "🔍 Checking vLLM availability..."

# 初始化USE_VLLM为false
USE_VLLM=$VLLM_ENABLED

# 只有在配置中启用且端口可用时才尝试vLLM
if [ "$VLLM_ENABLED" = "True" ] || [ "$VLLM_ENABLED" = "true" ]; then
    echo "  vLLM is enabled in config, checking availability..."
    
    # 检查vLLM是否安装
    if python -c "import vllm" 2>/dev/null; then
        echo "  ✅ vLLM package installed"
        
        # 检查端口是否可用
        if ! lsof -i :$VLLM_PORT > /dev/null 2>&1; then
            echo "  ✅ Port $VLLM_PORT is available"
            USE_VLLM=true
            echo "  ✅ vLLM will be used (if startup succeeds)"
        else
            echo "  ⚠️ Port $VLLM_PORT is occupied, cannot start vLLM"
            echo "  💡 Will fallback to Transformers mode"
        fi
    else
        echo "  ⚠️ vLLM package not installed"
        echo "  💡 Will fallback to Transformers mode"
    fi
else
    echo "  ℹ️ vLLM disabled in config"
    echo "  💡 Using Transformers mode"
fi

# 13. Start vLLM (if available and enabled)
VLLM_PID=""
if [ "$USE_VLLM" = true ]; then
    echo ""
    echo "🚀 Starting vLLM inference service..."
    echo "  Model: $MODEL_PATH"
    echo "  GPU memory utilization: $VLLM_GPU_MEM"
    echo "  Port: $VLLM_PORT"
    echo "  Max model len: $VLLM_MAX_MODEL_LEN"
    
    # 启动 vLLM（在后台运行）
    VLLM_USE_TRITON_FLASH_ATTN=0 \
    vllm serve "$MODEL_PATH" \
        --served-model-name "$MODEL_NAME" \
        --port $VLLM_PORT \
        --trust-remote-code \
        --gpu-memory-utilization=$VLLM_GPU_MEM \
        --max-num-seqs=8 \
        --dtype=auto \
        --max-model-len=$VLLM_MAX_MODEL_LEN \
        > vllm.log 2>&1 &
    
    VLLM_PID=$!
    echo "  vLLM PID: $VLLM_PID"
    
    # 等待 vLLM 启动
    echo ""
    echo "⏳ Waiting for vLLM to be ready (timeout: 300s)..."
    MAX_WAIT=10 # 300
    WAIT_COUNT=0
    WAIT_INTERVAL=5
    VLLM_READY=false
    
    while [ $WAIT_COUNT -lt $MAX_WAIT ]; do
        # 检查进程是否还在运行
        if ! kill -0 $VLLM_PID 2>/dev/null; then
            echo ""
            echo "  ❌ vLLM process died unexpectedly"
            echo "  --- Last 20 lines of vLLM log ---"
            tail -20 vllm.log 2>/dev/null || echo "  No logs available"
            echo "  ---------------------------------"
            USE_VLLM=false
            VLLM_PID=""
            break
        fi
        
        # 检查健康状态
        if curl -s http://localhost:$VLLM_PORT/health > /dev/null 2>&1; then
            echo ""
            echo "  ✅ vLLM is ready (took ${WAIT_COUNT}s)"
            VLLM_READY=true
            break
        fi
        
        sleep $WAIT_INTERVAL
        WAIT_COUNT=$((WAIT_COUNT + WAIT_INTERVAL))
        echo -n "."
    done
    
    # 如果vLLM未就绪，进行清理和fallback
    if [ "$VLLM_READY" = false ] && [ "$USE_VLLM" = true ]; then
        echo ""
        if [ $WAIT_COUNT -ge $MAX_WAIT ]; then
            echo "  ⚠️ vLLM startup timeout after ${MAX_WAIT}s"
        fi
        echo "  --- Last 20 lines of vLLM log ---"
        tail -20 vllm.log 2>/dev/null || echo "  No logs available"
        echo "  ---------------------------------"
        echo "  💡 Falling back to Transformers mode"
        
        # 清理vLLM进程
        if [ -n "$VLLM_PID" ]; then
            echo "  Cleaning up vLLM process (PID: $VLLM_PID)..."
            kill $VLLM_PID 2>/dev/null || true
            sleep 2
            # 强制杀死
            kill -9 $VLLM_PID 2>/dev/null || true
            VLLM_PID=""
        fi
        USE_VLLM=false
    fi
fi

# 14. Final decision on inference mode
echo ""
if [ "$USE_VLLM" = true ]; then
    echo "✅ Using vLLM for inference (high performance)"
else
    echo "✅ Using Transformers for inference (compatible mode)"
fi

# 15. Check LLM Client
echo ""
echo "🔍 Checking LLM Client..."
python -c "
from app.llm_client import get_llm_client
try:
    llm = get_llm_client()
    status = llm.get_model_status()
    print(f'  ✅ LLM Client ready')
    print(f'  📊 vLLM 可用: {status.get(\"vllm_available\", False)}')
    print(f'  📊 Transformers 已加载: {status.get(\"transformers_loaded\", False)}')
    print(f'  📊 推理模式: {\"vLLM\" if status.get(\"vllm_available\", False) else \"Transformers\"}')
    print(f'  📊 模型路径: {status.get(\"model_path\", \"N/A\")}')
except Exception as e:
    print(f'  ⚠️ LLM Client: {e}')
"

# 16. Start application
echo ""
echo "🚀 Starting ETF-Smart Advisor Web service..."
echo "  📊 Web UI: http://localhost:7860"
echo "  📚 API Docs: http://localhost:7860/docs"
echo "  🔧 推理模式: $( [ "$USE_VLLM" = true ] && echo "vLLM (高性能)" || echo "Transformers" )"
echo "  🗄️  知识库: Milvus Lite"
echo "  📁 模型: $MODEL_NAME"
echo "  🆔 模型ID: $MODEL_ID"
echo "  ⏹️  Press Ctrl+C to stop"
echo ""

# 设置环境变量
export VLLM_ENABLED=$USE_VLLM
export VLLM_PORT=$VLLM_PORT
export MODEL_PATH=$MODEL_PATH
export MODEL_NAME=$MODEL_NAME
export MODEL_ID=$MODEL_ID

# 启动应用
PYTHONPATH=. python -m app.main

# 17. Cleanup
cleanup() {
    echo ""
    echo "🛑 Shutting down..."

    # 1. 停止 Milvus Lite
    echo "  Stopping Milvus Lite..."
    python3 -c "
from app.milvus_client import get_milvus_client
get_milvus_client().stop()
print('  ✅ Milvus Lite stopped')
" 2>/dev/null || true

    # 2. 停止 vLLM
    if [ -n "$VLLM_PID" ] && kill -0 $VLLM_PID 2>/dev/null; then
        echo "  Stopping vLLM (PID: $VLLM_PID)..."
        kill $VLLM_PID 2>/dev/null || true
        sleep 2
        kill -9 $VLLM_PID 2>/dev/null || true
        echo "  ✅ vLLM stopped"
    fi
    echo "  ✅ Service stopped"
    exit 0
}

trap cleanup EXIT