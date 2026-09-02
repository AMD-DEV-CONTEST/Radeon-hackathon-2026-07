from .base import ExtractorBase, sanitize_input

class OllamaExtractor(ExtractorBase):
    """Entity extractor using Ollama API."""
    
    def __init__(self, model: str = "qwen2.5:7b", base_url: str = "http://localhost:11434"):
        super().__init__(model)
        self.base_url = base_url.rstrip("/")
    
    def _call_llm(self, prompt: str) -> str:
        import requests
        resp = requests.post(
            f"{self.base_url}/api/generate",
            json={"model": self.model, "prompt": prompt, "stream": False},
            timeout=120
        )
        resp.raise_for_status()
        return resp.json().get("response", "")
