import logging
import os
import subprocess
import time
from typing import Optional, Generator
import requests
import json

from ..config import InferenceConfig

logger = logging.getLogger(__name__)

class VLLMServer:
    """Manages a local vLLM subprocess for inference."""
    
    def __init__(self, config: InferenceConfig, is_primary: bool = True):
        """
        Initialises the VLLMServer.
        
        Args:
            config: Inference configuration.
            is_primary: Whether this is the primary or secondary model server.
        """
        self.config = config
        self.is_primary = is_primary
        self.process: Optional[subprocess.Popen] = None
        self.model = config.primary_model if is_primary else config.secondary_model
        # Use a different port for secondary if needed, simple logic for now
        self.port = config.vllm_port if is_primary else config.vllm_port + 1
        
    def start(self) -> bool:
        """
        Launches the vLLM subprocess.
        
        Returns:
            bool: True if started successfully and healthy, False otherwise.
        """
        if self.process is not None:
            logger.warning(f"vLLM server for {self.model} is already running.")
            return True
            
        env = os.environ.copy()
        env["HIP_VISIBLE_DEVICES"] = "0"
        env["PYTORCH_HIP_ALLOC_CONF"] = "max_split_size_mb:512"
        
        cmd = [
            "python", "-m", "vllm.entrypoints.openai.api_server",
            "--model", self.model,
            "--quantization", self.config.quantization,
            "--dtype", self.config.dtype,
            "--max-model-len", str(self.config.max_model_len),
            "--tensor-parallel-size", str(self.config.tensor_parallel_size),
            "--gpu-memory-utilization", str(self.config.gpu_memory_utilization),
            "--host", self.config.vllm_host,
            "--port", str(self.port)
        ]
        
        if self.config.enable_prefix_caching:
            cmd.append("--enable-prefix-caching")
        if self.config.enable_chunked_prefill:
            cmd.append("--enable-chunked-prefill")
            
        logger.info(f"Starting vLLM server: {' '.join(cmd)}")
        
        try:
            self.process = subprocess.Popen(
                cmd,
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True
            )
            
            # Wait for health endpoint
            max_retries = 24  # 120s total (5s intervals)
            for _ in range(max_retries):
                if self.is_healthy():
                    logger.info(f"vLLM server for {self.model} is healthy.")
                    return True
                time.sleep(5)
                
            logger.error(f"vLLM server for {self.model} failed to become healthy within timeout.")
            self.stop()
            return False
            
        except Exception as e:
            logger.error(f"Failed to start vLLM process: {e}")
            return False
            
    def stop(self) -> None:
        """Gracefully terminates the vLLM subprocess."""
        if self.process:
            logger.info(f"Stopping vLLM server for {self.model}...")
            self.process.terminate()
            try:
                self.process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                logger.warning("vLLM process did not terminate gracefully, killing it.")
                self.process.kill()
            self.process = None
            logger.info("vLLM server stopped.")

    def is_healthy(self) -> bool:
        """
        Checks if the vLLM server is responding.
        
        Returns:
            bool: True if healthy, False otherwise.
        """
        try:
            response = requests.get(f"{self.base_url}/health", timeout=2)
            return response.status_code == 200
        except requests.RequestException:
            return False

    def generate(self, messages: list[dict], max_tokens: int = 512, temperature: float = 0.7) -> str:
        """
        Generates text using the OpenAI-compatible endpoint.
        
        Args:
            messages: List of message dictionaries.
            max_tokens: Maximum tokens to generate.
            temperature: Sampling temperature.
            
        Returns:
            str: Generated content.
        """
        url = f"{self.base_url}/v1/chat/completions"
        payload = {
            "model": self.model,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "stream": False
        }
        
        response = requests.post(url, json=payload)
        response.raise_for_status()
        data = response.json()
        return data["choices"][0]["message"]["content"]
        
    def stream_generate(self, messages: list[dict], max_tokens: int = 512, temperature: float = 0.7) -> Generator[str, None, None]:
        """
        Generates text using the OpenAI-compatible endpoint with streaming.
        
        Args:
            messages: List of message dictionaries.
            max_tokens: Maximum tokens to generate.
            temperature: Sampling temperature.
            
        Yields:
            str: Chunks of generated text.
        """
        url = f"{self.base_url}/v1/chat/completions"
        payload = {
            "model": self.model,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "stream": True
        }
        
        response = requests.post(url, json=payload, stream=True)
        response.raise_for_status()
        
        for line in response.iter_lines():
            if line:
                line_str = line.decode('utf-8')
                if line_str.startswith("data: ") and line_str != "data: [DONE]":
                    data = json.loads(line_str[6:])
                    delta = data["choices"][0].get("delta", {})
                    if "content" in delta:
                        yield delta["content"]

    @property
    def base_url(self) -> str:
        """Returns the base URL for the vLLM server."""
        return f"http://{self.config.vllm_host}:{self.port}"
