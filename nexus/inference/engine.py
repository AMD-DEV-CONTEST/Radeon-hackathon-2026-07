"""
ROCm-optimized inference engine for multi-model parallel execution
"""
import asyncio
import logging
from pathlib import Path
from typing import Optional, Literal, Any
from dataclasses import dataclass
from contextlib import asynccontextmanager

import torch
from transformers import (
    AutoModelForCausalLM,
    AutoTokenizer,
    BitsAndBytesConfig,
    TextIteratorStreamer,
)

from nexus.core.config import InferenceConfig

logger = logging.getLogger(__name__)


@dataclass
class InferenceResult:
    """Result from model inference"""
    text: str
    tokens: int
    latency_ms: float
    model_name: str
    success: bool = True
    error: Optional[str] = None


class ModelInstance:
    """Single model instance with ROCm optimization"""

    def __init__(
        self,
        model_name: str,
        device: str,
        quantization: str,
        use_flash_attention: bool = True,
        max_memory_fraction: float = 0.9,
    ):
        self.model_name = model_name
        self.device = device
        self.quantization = quantization
        self.use_flash_attention = use_flash_attention
        self.max_memory_fraction = max_memory_fraction

        self.model: Optional[Any] = None
        self.tokenizer: Optional[Any] = None
        self.is_loaded = False

    async def load(self) -> None:
        """Load model with ROCm optimizations"""
        if self.is_loaded:
            return

        logger.info(f"Loading model {self.model_name} on {self.device} ({self.quantization})")

        # Configure quantization for memory efficiency
        quantization_config = None
        if self.quantization == "int4":
            quantization_config = BitsAndBytesConfig(
                load_in_4bit=True,
                bnb_4bit_compute_dtype=torch.float16,
                bnb_4bit_use_double_quant=True,
                bnb_4bit_quant_type="nf4",
            )
        elif self.quantization == "int8":
            quantization_config = BitsAndBytesConfig(
                load_in_8bit=True,
                llm_int8_threshold=6.0,
            )

        # Load tokenizer
        self.tokenizer = await asyncio.to_thread(
            AutoTokenizer.from_pretrained,
            self.model_name,
            trust_remote_code=True,
        )

        # Model loading kwargs
        model_kwargs = {
            "pretrained_model_name_or_path": self.model_name,
            "trust_remote_code": True,
            "low_cpu_mem_usage": True,
        }

        # Device mapping
        if self.device == "hip":
            # ROCm uses cuda device strings
            model_kwargs["device_map"] = "cuda:0"
        elif self.device == "cuda":
            model_kwargs["device_map"] = "auto"
        else:
            model_kwargs["device_map"] = "cpu"

        # Quantization config
        if quantization_config:
            model_kwargs["quantization_config"] = quantization_config
        elif self.quantization == "fp16":
            model_kwargs["torch_dtype"] = torch.float16
        else:
            model_kwargs["torch_dtype"] = torch.float32

        # Flash Attention (ROCm 6.0+)
        if self.use_flash_attention and self.device in ["hip", "cuda"]:
            model_kwargs["attn_implementation"] = "flash_attention_2"

        # Load model
        try:
            self.model = await asyncio.to_thread(
                AutoModelForCausalLM.from_pretrained,
                **model_kwargs,
            )
            self.is_loaded = True
            logger.info(f"Model {self.model_name} loaded successfully")
        except Exception as e:
            logger.error(f"Failed to load model {self.model_name}: {e}")
            # Fallback: try without flash attention
            if self.use_flash_attention:
                logger.info("Retrying without flash attention")
                model_kwargs.pop("attn_implementation", None)
                self.model = await asyncio.to_thread(
                    AutoModelForCausalLM.from_pretrained,
                    **model_kwargs,
                )
                self.is_loaded = True

    async def generate(
        self,
        prompt: str,
        max_new_tokens: int = 512,
        temperature: float = 0.7,
        top_p: float = 0.9,
        stream: bool = False,
    ) -> InferenceResult:
        """Generate text with ROCm-optimized inference"""
        if not self.is_loaded:
            await self.load()

        import time
        start_time = time.perf_counter()

        try:
            # Tokenize input
            inputs = self.tokenizer(
                prompt,
                return_tensors="pt",
                truncation=True,
                max_length=self.tokenizer.model_max_length,
            )

            # Move to device
            if self.device in ["hip", "cuda"]:
                inputs = {k: v.cuda() for k, v in inputs.items()}

            # Generate
            with torch.inference_mode():
                outputs = await asyncio.to_thread(
                    self.model.generate,
                    **inputs,
                    max_new_tokens=max_new_tokens,
                    temperature=temperature,
                    top_p=top_p,
                    do_sample=temperature > 0,
                    pad_token_id=self.tokenizer.eos_token_id,
                )

            # Decode
            generated_text = self.tokenizer.decode(
                outputs[0][inputs["input_ids"].shape[1]:],
                skip_special_tokens=True,
            )

            latency_ms = (time.perf_counter() - start_time) * 1000
            num_tokens = outputs.shape[1] - inputs["input_ids"].shape[1]

            return InferenceResult(
                text=generated_text,
                tokens=num_tokens,
                latency_ms=latency_ms,
                model_name=self.model_name,
                success=True,
            )

        except Exception as e:
            logger.error(f"Inference failed for {self.model_name}: {e}")
            latency_ms = (time.perf_counter() - start_time) * 1000
            return InferenceResult(
                text="",
                tokens=0,
                latency_ms=latency_ms,
                model_name=self.model_name,
                success=False,
                error=str(e),
            )

    def unload(self) -> None:
        """Free model from memory"""
        if self.model:
            del self.model
            self.model = None
        if self.tokenizer:
            del self.tokenizer
            self.tokenizer = None

        if torch.cuda.is_available():
            torch.cuda.empty_cache()

        self.is_loaded = False
        logger.info(f"Model {self.model_name} unloaded")


class NexusInferenceEngine:
    """
    Multi-model inference engine optimized for AMD ROCm
    Manages parallel agent inference across multiple models
    """

    def __init__(self, config: InferenceConfig):
        self.config = config
        self.models: dict[str, ModelInstance] = {}
        self.semaphore = asyncio.Semaphore(config.max_parallel_agents)
        self._initialized = False

    async def initialize(self) -> None:
        """Initialize inference engine and load models"""
        if self._initialized:
            return

        logger.info("Initializing NEXUS inference engine")

        # Check device availability
        if self.config.device == "hip":
            if not torch.cuda.is_available():
                logger.warning("ROCm/HIP not available, falling back to CPU")
                self.config.device = "cpu"
            else:
                logger.info(f"ROCm device: {torch.cuda.get_device_name(0)}")
                logger.info(f"ROCm version: {torch.version.hip}")

        # Initialize model instances (lazy loading)
        self.models = {
            "reasoning": ModelInstance(
                self.config.reasoning_model,
                self.config.device,
                self.config.reasoning_quantization,
                self.config.use_flash_attention,
                self.config.memory_fraction,
            ),
            "code": ModelInstance(
                self.config.code_model,
                self.config.device,
                self.config.code_quantization,
                self.config.use_flash_attention,
                self.config.memory_fraction,
            ),
            "fast": ModelInstance(
                self.config.fast_model,
                self.config.device,
                self.config.fast_quantization,
                self.config.use_flash_attention,
                self.config.memory_fraction,
            ),
        }

        self._initialized = True
        logger.info("Inference engine initialized")

    async def infer(
        self,
        prompt: str,
        model_type: Literal["reasoning", "code", "fast"] = "fast",
        max_tokens: int = 512,
        temperature: float = 0.7,
    ) -> InferenceResult:
        """
        Run inference on specified model type
        Automatically handles concurrency limits
        """
        if not self._initialized:
            await self.initialize()

        async with self.semaphore:
            model = self.models[model_type]
            result = await model.generate(
                prompt=prompt,
                max_new_tokens=max_tokens,
                temperature=temperature,
            )
            return result

    async def parallel_infer(
        self,
        prompts: list[tuple[str, str]],  # [(prompt, model_type), ...]
        max_tokens: int = 512,
        temperature: float = 0.7,
    ) -> list[InferenceResult]:
        """
        Run multiple inferences in parallel
        Respects max_parallel_agents concurrency limit
        """
        tasks = [
            self.infer(prompt, model_type, max_tokens, temperature)
            for prompt, model_type in prompts
        ]
        return await asyncio.gather(*tasks)

    async def shutdown(self) -> None:
        """Shutdown inference engine and free resources"""
        logger.info("Shutting down inference engine")
        for model in self.models.values():
            model.unload()
        self._initialized = False

    @asynccontextmanager
    async def session(self):
        """Context manager for inference session"""
        await self.initialize()
        try:
            yield self
        finally:
            await self.shutdown()


def check_rocm_availability() -> dict[str, Any]:
    """Check ROCm/GPU availability and return system info"""
    info = {
        "cuda_available": torch.cuda.is_available(),
        "device": "cpu",
        "device_name": "CPU",
        "device_count": 0,
        "rocm_version": None,
        "memory_total_gb": 0,
        "memory_available_gb": 0,
    }

    if torch.cuda.is_available():
        info["device"] = "hip"  # Assuming ROCm if torch.cuda works
        info["device_count"] = torch.cuda.device_count()
        info["device_name"] = torch.cuda.get_device_name(0)

        if hasattr(torch.version, "hip"):
            info["rocm_version"] = torch.version.hip

        # Memory info
        mem_total = torch.cuda.get_device_properties(0).total_memory
        mem_reserved = torch.cuda.memory_reserved(0)
        info["memory_total_gb"] = mem_total / 1e9
        info["memory_available_gb"] = (mem_total - mem_reserved) / 1e9

    return info
