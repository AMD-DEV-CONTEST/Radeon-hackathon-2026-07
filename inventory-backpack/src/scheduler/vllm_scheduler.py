"""
vLLM fine-grained scheduling - dynamic parameter adjustment
"""

import asyncio
import logging
from dataclasses import dataclass
from typing import Optional, Dict

logger = logging.getLogger(__name__)


@dataclass
class VLLMScheduleConfig:
    """vLLM scheduling config"""
    max_num_seqs: int = 16
    gpu_memory_utilization: float = 0.85
    max_num_batched_tokens: int = 2048
    scheduling_strategy: str = "fcfs"
    preemption_mode: str = "swap"


class VLLMDynamicScheduler:
    """
    vLLM dynamic scheduler

    Dynamically adjusts scheduling parameters based on real-time load
    """

    # Preset config templates
    PRESETS = {
        "latency": VLLMScheduleConfig(
            max_num_seqs=8,
            gpu_memory_utilization=0.80,
            max_num_batched_tokens=1024,
        ),
        "balanced": VLLMScheduleConfig(
            max_num_seqs=16,
            gpu_memory_utilization=0.85,
            max_num_batched_tokens=2048,
        ),
        "throughput": VLLMScheduleConfig(
            max_num_seqs=32,
            gpu_memory_utilization=0.92,
            max_num_batched_tokens=4096,
        ),
    }
    
    def __init__(self, api_endpoint: str):
        self.api = api_endpoint
        self._current: VLLMScheduleConfig = self.PRESETS["balanced"]
    
    async def apply_profile(self, profile: str):
        """Apply preset config"""
        if profile not in self.PRESETS:
            raise ValueError(f"Unknown profile: {profile}")
        
        self._current = self.PRESETS[profile]
        await self._push_config()
        
        logger.info(f"Applied vLLM profile: {profile}")
    
    async def adjust_for_pressure(self, pressure_level: str):
        """
        Auto-adjust based on pressure level

        pressure_level: "low", "medium", "high", "critical"
        """
        
        adjustments = {
            "low": {"max_num_seqs": +4, "gpu_util": +0.05},
            "medium": {"max_num_seqs": 0, "gpu_util": 0},
            "high": {"max_num_seqs": -4, "gpu_util": -0.05},
            "critical": {"max_num_seqs": -8, "gpu_util": -0.10},
        }
        
        if pressure_level not in adjustments:
            return
        
        adj = adjustments[pressure_level]
        
        # Apply adjustments
        new_max_seqs = max(4, self._current.max_num_seqs + adj["max_num_seqs"])
        new_gpu_util = max(0.70, min(0.95, self._current.gpu_memory_utilization + adj["gpu_util"]))
        
        self._current = VLLMScheduleConfig(
            max_num_seqs=new_max_seqs,
            gpu_memory_utilization=new_gpu_util,
            max_num_batched_tokens=self._current.max_num_batched_tokens,
        )
        
        await self._push_config()
    
    async def _push_config(self):
        """Push config to vLLM"""
        # Actual implementation: call vLLM admin API or restart instance
        config_dict = {
            "max_num_seqs": self._current.max_num_seqs,
            "gpu_memory_utilization": self._current.gpu_memory_utilization,
            "max_num_batched_tokens": self._current.max_num_batched_tokens,
        }
        
        logger.info(f"Pushing config to vLLM: {config_dict}")
        # await self._api_update(config_dict)
    
    @property
    def current(self) -> VLLMScheduleConfig:
        return self._current