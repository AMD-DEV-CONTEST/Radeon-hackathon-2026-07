# utils/vllm_tuning.py

from dataclasses import dataclass
from typing import Optional, Dict, Any
import os


@dataclass
class VLLMConfig:
    """
    针对AMD GPU和TTFT优化的vLLM配置
    """
    # ========== 核心调度参数 ==========
    max_num_batched_tokens: int = 4096      # 关键：控制prefill batch大小
    max_num_seqs: int = 256                  # 最大并发序列数
    max_model_len: int = 8192                # 模型最大长度
    
    # ========== Chunked Prefill（关键！）==========
    enable_chunked_prefill: bool = True      # 🔑 启用chunked prefill
    chunked_prefill_size: int = 512          # 每个chunk的token数（小=低延迟，大=高吞吐）
    
    # ========== 内存管理 ==========
    gpu_memory_utilization: float = 0.90     # GPU内存利用率
    swap_space: int = 4                      # CPU swap空间(GB)
    
    # ========== 调度策略 ==========
    scheduling_policy: str = "fcfs"          # fcfs 或 priority
    num_scheduler_steps: int = 1             # 调度步数
    
    # ========== 性能优化 ==========
    enable_prefix_caching: bool = True       # 前缀缓存
    dtype: str = "auto"                      # 数据类型

    # ========== Chunked Prefill ==========
    enable_chunked_prefill: bool = True      # 分块 prefill，降低 TTFT
    max_num_prefill_seqs: int = 4            # 限制同时 prefill 的序列数

    # ========== Warmup ==========
    enable_warmup: bool = True               # 启动预热，防止冷启动 TTFT 尖峰
    warmup_token_count: int = 128            # 预热 token 数

    # ========== ROCm特定 ==========
    # 环境变量设置
    env_vars: Dict[str, str] = None
    
    def __post_init__(self):
        if self.env_vars is None:
            self.env_vars = {
                "PYTORCH_HIP_ALLOC_CONF": "expandable_segments:True",
                "HSA_OVERRIDE_GFX_VERSION": "10.3.0",  # 根据实际GPU调整
                "MIOPEN_FIND_MODE": "1",
            }
    
    def get_launch_args(self) -> Dict[str, Any]:
        """生成vLLM启动参数"""
        args = {
            "max_num_seqs": self.max_num_seqs,
            "max_model_len": self.max_model_len,
            "gpu_memory_utilization": self.gpu_memory_utilization,
            "swap_space": self.swap_space,
            "scheduling_policy": self.scheduling_policy,
            "num_scheduler_steps": self.num_scheduler_steps,
            "enable_prefix_caching": self.enable_prefix_caching,
            "dtype": self.dtype,
        }

        # chunked prefill: max_num_batched_tokens controls chunk size
        if self.enable_chunked_prefill:
            args["enable_chunked_prefill"] = True
            args["max_num_batched_tokens"] = self.chunked_prefill_size
        else:
            args["max_num_batched_tokens"] = self.max_num_batched_tokens

        if self.max_num_prefill_seqs > 0:
            args["max_num_prefill_seqs"] = self.max_num_prefill_seqs

        return args

    def get_launch_command(self, model_name: str = "Qwen/Qwen2.5-0.5B-Instruct") -> str:
        """生成完整的 vLLM 启动命令字符串"""
        args = self.get_launch_args()
        parts = [
            "python", "-m", "vllm.entrypoints.openai.api_server",
            "--model", model_name,
        ]
        for key, value in args.items():
            flag = f"--{key.replace('_', '-')}"
            if isinstance(value, bool):
                if value:
                    parts.append(flag)
            else:
                parts.extend([flag, str(value)])
        return " ".join(parts)
    
    def apply_env(self):
        """应用环境变量"""
        for key, value in self.env_vars.items():
            os.environ[key] = value


# 预设配置
PRESETS = {
    # 0.5B 专用：最大化并发，最小化 TTFT
    "low_latency_050b": VLLMConfig(
        max_num_batched_tokens=2048,
        chunked_prefill_size=512,
        max_num_seqs=256,               # 0.5B KV Cache 极小，可高并发
        gpu_memory_utilization=0.95,    # 0.5B 模型本身仅 ~1GB，留更多给 KV Cache
        max_num_prefill_seqs=4,         # 限制并发 prefill，避免 TTFT 尖峰
        enable_warmup=True,
    ),
    "low_latency": VLLMConfig(
        max_num_batched_tokens=1024,    # 小batch，低延迟
        chunked_prefill_size=256,        # 更小的chunk
        max_num_seqs=128,
    ),
    "balanced": VLLMConfig(
        max_num_batched_tokens=4096,   # 平衡
        chunked_prefill_size=512,
        max_num_seqs=256,
    ),
    "high_throughput": VLLMConfig(
        max_num_batched_tokens=8192,    # 大batch，高吞吐
        chunked_prefill_size=1024,
        max_num_seqs=512,
    ),
}


def get_optimal_config(
    target_ttfb_ms: float = 200.0,
    gpu_model: str = "mi250",
) -> VLLMConfig:
    """
    根据目标TTFB自动选择配置
    """
    if target_ttfb_ms < 150:
        return PRESETS["low_latency"]
    elif target_ttfb_ms < 300:
        return PRESETS["balanced"]
    else:
        return PRESETS["high_throughput"]