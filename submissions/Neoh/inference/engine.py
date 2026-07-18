"""vLLM 推理引擎封装。

使用 vLLM 在 AMD Radeon GPU (ROCm) 上运行 Qwen2.5-7B-Instruct。
vLLM 提供 PagedAttention + 连续批处理，性能优于 llama.cpp。

API 与原 llama_cpp 版本保持兼容：
- generate(prompt, **kwargs) -> str
- chat_completion(messages, **kwargs) -> str
- get_model_info() -> dict
- unload()
"""

import logging
import os

# ---- ROCm 环境变量（必须在 import torch/vllm 之前设置）----
# W7900 / RX 7900 系列是 gfx1100 架构，vLLM 官方 wheel 默认为
# 数据中心卡（MI200/MI300）编译，需要 override 才能识别消费级/专业卡。
os.environ.setdefault("HSA_OVERRIDE_GFX_VERSION", "11.0.0")
os.environ.setdefault("PYTORCH_ROCM_ARCH", "gfx1100")
os.environ.setdefault("HIP_VISIBLE_DEVICES", "0")  # 默认用第一张 GPU
os.environ.setdefault("HSA_ENABLE_SDMA", "0")

# ---- 多卡 TP 必需的环境变量 ----
# vLLM 用 multiprocessing 启动 worker，必须用 spawn 模式才能继承环境变量
os.environ.setdefault("VLLM_WORKER_MULTIPROC_METHOD", "spawn")
# RCCL（ROCm 的 NCCL）多卡通信优化
os.environ.setdefault("RCCL_NCCL_NCHANNELS", "4")
os.environ.setdefault("RCCL_NCCL_NSOCKETS_PERCHANNEL", "8")
os.environ.setdefault("NCCL_SOCKET_IFNAME", "lo")
# 避免 ROCm 在多 GPU 环境下的锁冲突
os.environ.setdefault("HSA_ENABLE_INTERRUPTIBLE", "0")

from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class InferenceConfig(BaseModel):
    model_path: str = Field(..., description="模型目录路径（safetensors 格式）")
    n_gpu_layers: int = Field(-1, description="兼容字段，vLLM 自动全量 offload")
    n_ctx: int = Field(8192, description="上下文窗口大小（max_model_len）")
    n_batch: int = Field(512, description="兼容字段，vLLM 自动管理批处理")
    temperature: float = Field(0.7, description="温度参数")
    max_tokens: int = Field(4096, description="最大生成 token 数")
    chat_format: str = Field("qwen2", description="对话格式（vLLM 自动从 tokenizer 读取）")
    # vLLM 专用参数
    gpu_memory_utilization: float = Field(0.90, description="GPU 显存占用比例")
    dtype: str = Field("float16", description="模型精度：float16/bfloat16/auto")
    trust_remote_code: bool = Field(True, description="是否信任远程代码")
    # 多卡并行参数
    tensor_parallel_size: int = Field(1, description="张量并行 GPU 数（ROCm 7.2.1 仅 1/8 稳定）")
    pipeline_parallel_size: int = Field(1, description="流水线并行 GPU 数")


class InferenceEngine:
    """vLLM 推理引擎，API 与 llama_cpp 版本兼容。"""

    def __init__(self, config: InferenceConfig):
        self.config = config
        self.llm: Optional[Any] = None  # vllm.LLM 实例
        self.tokenizer: Optional[Any] = None
        self._init_llm()

    def _init_llm(self):
        try:
            # 延迟导入，避免 vLLM 未安装时影响其他模块
            from vllm import LLM
            from transformers import AutoTokenizer

            logger.info(f"Loading model from {self.config.model_path}")
            logger.info(f"Context: {self.config.n_ctx}, dtype: {self.config.dtype}")
            logger.info(f"GPU memory utilization: {self.config.gpu_memory_utilization}")
            logger.info(f"Tensor parallel: {self.config.tensor_parallel_size}, "
                        f"Pipeline parallel: {self.config.pipeline_parallel_size}")

            # 加载 tokenizer（用于 chat template）
            self.tokenizer = AutoTokenizer.from_pretrained(
                self.config.model_path,
                trust_remote_code=self.config.trust_remote_code,
            )

            # 加载 vLLM 引擎
            self.llm = LLM(
                model=self.config.model_path,
                max_model_len=self.config.n_ctx,
                gpu_memory_utilization=self.config.gpu_memory_utilization,
                dtype=self.config.dtype,
                trust_remote_code=self.config.trust_remote_code,
                # ROCm 优化
                enforce_eager=False,  # 启用 CUDA graph（ROCm 也支持）
                tensor_parallel_size=self.config.tensor_parallel_size,
                pipeline_parallel_size=self.config.pipeline_parallel_size,
            )
            logger.info("Model loaded successfully (vLLM + ROCm)")

        except ImportError as e:
            logger.error(f"vLLM not installed: {e}")
            raise RuntimeError(
                "vLLM is not installed. Install with:\n"
                "  pip install vllm --extra-index-url https://wheels.vllm.ai/rocm/\n"
                "Or run install_rocm.sh"
            )
        except Exception as e:
            logger.error(f"Failed to load model: {str(e)}")
            raise

    def generate(self, prompt: str, **kwargs) -> str:
        """文本生成（非 chat 格式）。

        Args:
            prompt: 输入文本
            **kwargs: max_tokens, temperature 等

        Returns:
            生成的文本
        """
        if not self.llm:
            raise RuntimeError("LLM engine not initialized")

        from vllm import SamplingParams

        max_tokens = kwargs.get("max_tokens", self.config.max_tokens)
        temperature = kwargs.get("temperature", self.config.temperature)

        sampling_params = SamplingParams(
            max_tokens=max_tokens,
            temperature=temperature,
            stop=["<|im_end|>", "</s>"],
        )

        try:
            outputs = self.llm.generate([prompt], sampling_params)
            return outputs[0].outputs[0].text.strip()
        except Exception as e:
            logger.error(f"Inference error: {str(e)}")
            raise

    def chat_completion(self, messages: List[Dict[str, str]], **kwargs) -> str:
        """Chat 对话补全。

        使用 vLLM 原生的 chat() 方法，自动处理 chat template。

        Args:
            messages: [{"role": "system/user/assistant", "content": "..."}]
            **kwargs: max_tokens, temperature 等

        Returns:
            生成的回复文本
        """
        if not self.llm:
            raise RuntimeError("LLM engine not initialized")

        from vllm import SamplingParams

        max_tokens = kwargs.get("max_tokens", self.config.max_tokens)
        temperature = kwargs.get("temperature", self.config.temperature)

        sampling_params = SamplingParams(
            max_tokens=max_tokens,
            temperature=temperature,
            stop=["<|im_end|>", "</s>"],
        )

        try:
            # vLLM 0.25+ 原生支持 chat()，自动 apply chat template
            outputs = self.llm.chat(messages, sampling_params)
            return outputs[0].outputs[0].text.strip()
        except Exception as e:
            logger.error(f"Chat completion error: {str(e)}")
            raise

    def get_model_info(self) -> Dict[str, Any]:
        if not self.llm:
            return {"status": "not_initialized"}

        return {
            "status": "loaded",
            "engine": "vLLM",
            "model_path": self.config.model_path,
            "n_ctx": self.config.n_ctx,
            "dtype": self.config.dtype,
            "gpu_memory_utilization": self.config.gpu_memory_utilization,
            "temperature": self.config.temperature,
        }

    def unload(self):
        if self.llm:
            del self.llm
            self.llm = None
            logger.info("Model unloaded")
