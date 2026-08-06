"""
vLLM adapter - apply parameters to vLLM instances
"""

import asyncio
import logging
import time
from typing import Dict, Optional
import aiohttp

logger = logging.getLogger(__name__)


class VLLMInstance:
    """vLLM instance management"""

    def __init__(self, base_url: str, api_key: Optional[str] = None,
                 model_name: str = "Qwen/Qwen2.5-0.5B-Instruct"):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model_name = model_name

        self._current_config: Dict = {}
        self._session: Optional[aiohttp.ClientSession] = None
    
    async def __aenter__(self):
        self._session = aiohttp.ClientSession()
        return self
    
    async def __aexit__(self, *args):
        if self._session:
            await self._session.close()
    
    async def apply_config(self, config: dict) -> bool:
        """
        Dynamically apply configuration
        
        Note: some vLLM parameters require restart, some can be hot-updated
        """
        # Check which parameters require restart
        restart_required = self._check_restart_needed(config)
        
        if restart_required:
            await self._restart_with_config(config)
        else:
            await self._hot_update(config)
        
        self._current_config = config.copy()
        return True
    
    def _check_restart_needed(self, new_config: dict) -> bool:
        """Check whether a restart is needed"""
        restart_params = {
            "max_num_seqs",
            "gpu_memory_utilization",
            "max_model_len",
            "pipeline_parallel_size",
        }
        
        for param in restart_params:
            if param in new_config and self._current_config.get(param) != new_config[param]:
                return True
        
        return False
    
    async def _restart_with_config(self, config: dict):
        """Restart vLLM with the given configuration"""
        # Actual implementation requires container orchestration (K8s/Docker)
        logger.info(f"Restarting vLLM with config: {config}")
        
        # 1. Graceful shutdown
        await self._graceful_shutdown()
        
        # 2. Build launch command
        cmd = self._build_launch_command(config)
        
        # 3. Start new instance
        # Done by external orchestration in practice
        pass
    
    async def _hot_update(self, config: dict):
        """Hot update (if vLLM supports it)"""
        # vLLM currently has limited hot-update support
        # Some parameters can be adjusted via API
        pass
    
    def _build_launch_command(self, config: dict) -> list:
        """Build the vLLM launch command"""
        cmd = ["python", "-m", "vllm.entrypoints.openai.api_server"]

        # Model path (configurable)
        cmd.extend(["--model", config.pop("model_name", self.model_name)])
        
        # Dynamic parameters
        for key, value in config.items():
            param_name = key.replace("_", "-")
            
            if isinstance(value, bool):
                if value:
                    cmd.append(f"--{param_name}")
            else:
                cmd.extend([f"--{param_name}", str(value)])
        
        return cmd
    
    async def _graceful_shutdown(self):
        """Graceful shutdown"""
        # Send shutdown signal
        try:
            await self._session.post(f"{self.base_url}/shutdown")
        except Exception:
            pass

    async def warmup(self, token_count: int = 128) -> bool:
        """Send a warmup request to keep model in GPU memory.

        Call this after startup and periodically during idle periods
        to prevent cold-start TTFT spikes.
        """
        headers = {}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        payload = {
            "model": self.model_name,
            "messages": [{"role": "user", "content": "Hello"}],
            "max_tokens": token_count,
            "stream": False,
        }

        try:
            async with self._session.post(
                f"{self.base_url}/v1/chat/completions",
                json=payload,
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=30),
            ) as resp:
                if resp.status == 200:
                    logger.info(f"vLLM warmup OK (tokens={token_count})")
                    return True
                else:
                    logger.warning(f"vLLM warmup returned {resp.status}")
                    return False
        except Exception as e:
            logger.warning(f"vLLM warmup failed: {e}")
            return False

    async def keepalive_loop(self, interval: float = 30.0, stop_event: Optional[asyncio.Event] = None):
        """Periodically send minimal requests to prevent model eviction from GPU.

        Args:
            interval: seconds between keepalive requests
            stop_event: set this to stop the loop
        """
        headers = {}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        payload = {
            "model": self.model_name,
            "messages": [{"role": "user", "content": "ok"}],
            "max_tokens": 1,
            "stream": False,
        }

        while stop_event is None or not stop_event.is_set():
            try:
                async with self._session.post(
                    f"{self.base_url}/v1/chat/completions",
                    json=payload,
                    headers=headers,
                    timeout=aiohttp.ClientTimeout(total=10),
                ) as resp:
                    pass
            except Exception:
                pass

            if stop_event:
                try:
                    await asyncio.wait_for(stop_event.wait(), timeout=interval)
                    break
                except asyncio.TimeoutError:
                    continue
            else:
                await asyncio.sleep(interval)


class VLLMPerformanceEvaluator:
    """
    vLLM performance evaluator
    
    Runs short benchmarks and returns performance metrics
    """
    
    def __init__(self, endpoint: str, benchmark_tool: str = "benchmark_v4.py"):
        self.endpoint = endpoint
        self.benchmark_tool = benchmark_tool
    
    async def evaluate(self, config: dict) -> dict:
        """
        Evaluate configuration performance
        
        Returns:
            {
                "ttft_p99": float,  # P99 time-to-first-token latency (ms)
                "rps": float,        # Throughput
                "error_rate": float, # Error rate
                "latency_curve": list,  # Latency distribution
            }
        """
        
        # 1. Apply configuration
        # await instance.apply_config(config)
        
        # 2. Wait for service to be ready
        await asyncio.sleep(5)
        
        # 3. Run benchmark
        # Actually calls the benchmark tool
        result = await self._run_benchmark(config)
        
        return result
    
    async def _run_benchmark(self, config: dict) -> dict:
        """Run benchmark"""
        # Simplified: actually calls benchmark_v4.py
        # Here we return simulated data
        
        # Simulate: better config = better performance
        base_ttft = 3000
        base_rps = 3.0
        
        # Adjust based on configuration
        max_seqs = config.get("max_num_seqs", 32)
        gpu_util = config.get("gpu_memory_utilization", 0.85)
        
        # Simulated performance model
        ttft = base_ttft / (max_seqs / 16) * (1 + (gpu_util - 0.85) * 2)
        rps = base_rps * (max_seqs / 16) * gpu_util
        
        # Add noise
        import random
        ttft *= random.uniform(0.8, 1.2)
        rps *= random.uniform(0.9, 1.1)
        
        return {
            "ttft_p99": max(500, min(ttft, 10000)),
            "rps": max(1, min(rps, 10)),
            "error_rate": random.uniform(0, 0.05),
        }
