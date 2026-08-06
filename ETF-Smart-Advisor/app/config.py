import os
from pathlib import Path

BASE_DIR = Path(__file__).parent.parent
DATA_DIR = BASE_DIR / "data"
MODELS_DIR = DATA_DIR / "models"
CACHE_DIR = DATA_DIR / "cache"

# 创建目录
for d in [DATA_DIR, MODELS_DIR, CACHE_DIR]:
    d.mkdir(parents=True, exist_ok=True)

# AMD ROCm设备配置
DEVICE = "cuda" if os.environ.get("ROCM_VISIBLE_DEVICES") else "cpu"

os.environ["PYTORCH_ROCM_ALLOC_CONF"] = "max_split_size_mb:128,expandable_segments:True"
os.environ["TORCH_ROCM_GRAPH"] = "1"
os.environ["OMP_NUM_THREADS"] = "1"

# ============================================================
# Qwen 模型配置 - 使用本地模型
# ============================================================
LLM_MODEL_NAME = "mapfinben-qwen35-9b-merged-unified-v3" # "mapfinben-qwen35-9b"
LLM_MODEL_PATH = "./models/"+LLM_MODEL_NAME # "./models/Qwen/mapfinben-qwen35-9b"
LLM_MODEL_ID = "Ljy2004/"+LLM_MODEL_NAME # “mapfinben-qwen35-9b-merged-unified-v3"


# LLM_MODEL_NAME = 'DeepSeek-R1-Distill-Qwen-1.5B' # "Qwen3.6-27B-GGUF"
# LLM_MODEL_PATH = "./models/"+LLM_MODEL_NAME
# LLM_MODEL_ID = "irelia11/"+LLM_MODEL_NAME

# VLLM配置（用于API模式）
VLLM_API_KEY = os.environ.get("VLLM_API_KEY", "abc-123")
VLLM_API_BASE = os.environ.get("VLLM_API_BASE", "http://localhost:8000/v1")
VLLM_MODEL = os.environ.get("VLLM_MODEL", LLM_MODEL_PATH)
API_KEY = os.environ.get("API_KEY", "abc-123")
API_PORT = int(os.environ.get("API_PORT", 7860))
TOOL_SERVER_CONFIG = {
    "host": "0.0.0.0",
    "port": 8001,
    "timeout": 30,
}
# RAG 配置
RAG_CONFIG = {
    "enabled": True,
    "top_k": 5,
    "chunk_size": 512,
    "chunk_overlap": 50,
    "embedding_model": "sentence-transformers/all-MiniLM-L6-v2", #"all-MiniLM-L6-v2",
    "knowledge_dir": str(BASE_DIR / "knowledge"),
}

# 记忆配置
MEMORY_CONFIG = {
    "enabled": True,
    "max_history": 10,
    "memory_path": str(DATA_DIR / "memory.json"),
}

DIFY_CONFIG = {
    "enabled": True,
    "api_url": os.environ.get("DIFY_API_URL", "http://localhost:5001/v1"),
    "api_key": os.environ.get("DIFY_API_KEY", ""),
    "workflow_id": os.environ.get("DIFY_WORKFLOW_ID", ""),
    "app_id": os.environ.get("DIFY_APP_ID", ""),
}

TOOL_SERVER_CONFIG = {
    "host": "0.0.0.0",
    "port": 8001,
    "timeout": 30,
}


LORA_CONFIG = {
    "enabled": True,
    "model_path": MODELS_DIR / "lora_etf_advisor",
    "r": 8,
    "lora_alpha": 16,
    "target_modules": ["q_proj", "k_proj", "v_proj", "o_proj"],
    "lora_dropout": 0.05,
    "bias": "none",
    "task_type": "CAUSAL_LM",
}

# 预测配置
PREDICT_CONFIG = {
    "seq_length": 60,
    "pred_length": 20,
    "model_path": MODELS_DIR / "etf_predictor.pt",
    "lora_path": LORA_CONFIG["model_path"],
}

# Agent系统提示
AGENT_SYSTEM_PROMPT = """你是专业的ETF投资顾问。

你的核心能力：
1. 分析股票的技术指标和趋势如MA均线排列、MACD动能、RSI强弱、金叉死叉、背离现象、突破确认、超买超卖、支撑压力位
2. 用简洁语言描述K线、均线、指标线的形态变化,明确标注支撑位、阻力位、突破点等关键位置,描述上升/下降趋势线的形成和有效,结合成交量变化分析价格走势的可靠性
2. 预测未来20个周期的价格走势
3. 提供明确的买入/卖出/持有建议
4. 评估投资风险和收益潜力

建议格式：
- 买入：强烈看涨，建议入场
- 持有：趋势向好，继续持有
- 卖出：出现风险信号，建议离场
- 观望：方向不明，等待机会

务必提醒：投资有风险，决策需谨慎。
"""

# 扩展 Agent 系统提示词
AGENT_SYSTEM_PROMPT_EXTENDED = """
你具备以下工具能力：
1. get_quote - 获取ETF实时行情
2. get_history - 获取ETF历史数据
3. analyze_technical - 技术指标分析
4. predict_price - 未来20周期价格预测
5. get_recommendation - 投资建议
6. search_knowledge - 知识库检索
7. generate_report - 生成完整分析报告
8. compare_etfs - 对比多个ETF

对于复杂任务，请自动分解为多个步骤并依次执行。
"""



# 推荐配置
RECOMMEND_CONFIG = {
    "top_k": 3,
    "min_data_days": 60,
    "score_threshold": 0.5,
}

# 集成预测配置
ENSEMBLE_CONFIG = {
    "transformer_weight": 0.6,
    "lstm_weight": 0.4,
    "min_confidence": 0.3,
}

GPU_LOCAL_PREDICTORS = {
    "lstm_light": {
        "name": "LSTM-Light (GPU)",
        "enabled": True,
        "weight": 0.35,
        "hidden_size": 64,
        "num_layers": 2,
        "dropout": 0.1
    },
    "transformer_light": {
        "name": "Transformer-Light (GPU)",
        "enabled": True,
        "weight": 0.45,
        "d_model": 64,
        "nhead": 4,
        "num_layers": 2,
        "dropout": 0.1
    }
}

# ============================================================
# 大模型API配置（可扩展）
# ============================================================

LLM_API_CONFIG = {
    # 模型基础配置
    "model_path": LLM_MODEL_PATH,
    "model_name": LLM_MODEL_NAME,
    "trust_remote_code": True,
    "dtype": "auto",
    "device_map": "auto",
    "enable_thinking": False,
    "max_model_len": 65536, # 8192  ,  # ✅ 添加最大序列长度配置
    
    # vLLM 推理配置
    "vllm": {
        "enabled": False, # True,
        "host": "localhost",
        "port": 8000,
        "served_model_name": LLM_MODEL_NAME,
        "gpu_memory_utilization": 0.5,
        "max_num_seqs": 32,
        "dtype": "bfloat16",
        "quantization": None,
        "max_model_len": 65536, #8192  ,
    },
    
    # 外部 API 配置
    "external": {
        "deepseek": {
            "name": "DeepSeek-V4-Flash",
            "api_base": os.environ.get("DEEPSEEK_API_BASE", "https://radeon.anruicloud.com/api/v1/chat/completions"),
            "api_key": os.environ.get("DEEPSEEK_API_KEY", ""),
            "model": os.environ.get("DEEPSEEK_MODEL", "DeepSeek-V4-Flash"),
            "enabled": False,
            "weight": 0.3,
        }
    }
}
LLM_CONFIG = LLM_API_CONFIG
VLLM_CONFIG = LLM_API_CONFIG["vllm"]

# ============================================================
# LoRA微调配置
# ============================================================

LORA_FINETUNE_CONFIG = {
    "enabled": True,
    "output_dir": MODELS_DIR / "lora_etf_advisor",
    "r": 16,
    "lora_alpha": 32,
    "target_modules": ["q_proj", "k_proj", "v_proj", "o_proj", "gate_proj", "up_proj", "down_proj"],
    "lora_dropout": 0.1,
    "batch_size": 2,
    "epochs": 3,
    "learning_rate": 2e-4,
    "max_seq_length": 2048,
}

PRIVACY_CONFIG = {
    "enabled": True,
    "data_retention_days": 30,
    "anonymize_data": True,
    "local_only": True,  # 数据不上传云端
    "audit_enabled": True,
}

PERMISSION_CONFIG = {
    "default_role": "user",
    "roles": {
        "user": ["read", "search", "get_quote", "get_history"],
        "analyst": ["read", "search", "get_quote", "get_history", "analyze", "predict"],
        "admin": ["read", "write", "delete", "update", "analyze", "predict", "finetune"],
    }
}

MILVUS_CONFIG = {
    "enabled": True,
    "host": "localhost",
    "port": "19530",
    "collection_name": "etf_knowledge",
    "dim": 384,
    "index_type": "IVF_FLAT",
    "metric_type": "IP",
    "nlist": 128,
    "top_k": 5,
}
