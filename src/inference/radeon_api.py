import logging
import requests
import json
from typing import Generator

logger = logging.getLogger(__name__)

class RadeonCloudAPI:
    """Radeon Cloud Model API fallback — always uses 4-bit quantization."""
    
    DEFAULT_BASE_URL = "https://developer.amd.com.cn/radeon/api/v1"
    
    def __init__(self, api_key: str, model: str = "Qwen3-30B-A3B", base_url: str = None):
        """
        Initialises the RadeonCloudAPI client.
        
        Args:
            api_key: The API key for authentication.
            model: The model identifier to use.
            base_url: Optional custom base URL for Radeon Cloud.
        """
        self.api_key = api_key
        self.model = model
        self.base_url = (base_url or self.DEFAULT_BASE_URL).rstrip("/")
        self.session = requests.Session()
        self.session.headers.update({
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        })

    def generate(self, messages: list[dict], max_tokens: int = 512, temperature: float = 0.7) -> str:
        """
        Generates text via the Radeon Cloud API.
        
        Args:
            messages: List of message dictionaries.
            max_tokens: Maximum tokens to generate.
            temperature: Sampling temperature.
            
        Returns:
            str: Generated content string.
        """
        url = f"{self.base_url}/chat/completions"
        payload = {
            "model": self.model,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "extra_body": {"quantization": "4bit"}  # CRITICAL REQUIREMENT
        }
        
        response = self.session.post(url, json=payload)
        response.raise_for_status()
        data = response.json()
        return data["choices"][0]["message"]["content"]

    def stream_generate(self, messages: list[dict], max_tokens: int = 512, temperature: float = 0.7) -> Generator[str, None, None]:
        """
        Generates text via the Radeon Cloud API with streaming.
        
        Args:
            messages: List of message dictionaries.
            max_tokens: Maximum tokens to generate.
            temperature: Sampling temperature.
            
        Yields:
            str: Chunks of generated text.
        """
        url = f"{self.base_url}/chat/completions"
        payload = {
            "model": self.model,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "stream": True,
            "extra_body": {"quantization": "4bit"}  # CRITICAL REQUIREMENT
        }
        
        response = self.session.post(url, json=payload, stream=True)
        response.raise_for_status()
        
        for line in response.iter_lines():
            if line:
                line_str = line.decode('utf-8')
                if line_str.startswith("data: ") and line_str != "data: [DONE]":
                    try:
                        data = json.loads(line_str[6:])
                        delta = data["choices"][0].get("delta", {})
                        if "content" in delta:
                            yield delta["content"]
                    except json.JSONDecodeError:
                        continue

    def is_available(self) -> bool:
        """
        Quick health check to ensure the API is reachable.
        
        Returns:
            bool: True if available, False otherwise.
        """
        if not self.api_key:
            return False
            
        try:
            response = self.session.get(f"{self.base_url}/models", timeout=3)
            return response.status_code == 200
        except requests.RequestException:
            # Fallback to checking basic connectivity if /models doesn't exist
            return True
