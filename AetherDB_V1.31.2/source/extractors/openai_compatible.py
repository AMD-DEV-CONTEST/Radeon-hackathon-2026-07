from .base import ExtractorBase

class OpenAICompatibleExtractor(ExtractorBase):
    """Entity extractor using OpenAI-compatible API.
    
    Supports: OpenAI, DeepSeek, Claude (via API), Gemini (via API), and any OpenAI-compatible endpoint.
    """
    
    def __init__(self, model: str = "gpt-4o-mini", api_key: str = "", base_url: str = "https://api.openai.com/v1"):
        super().__init__(model)
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
    
    def _call_llm(self, prompt: str) -> str:
        from openai import OpenAI
        client = OpenAI(api_key=self.api_key, base_url=self.base_url)
        resp = client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": "You are a worldbuilding entity extractor. Respond only with JSON."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.1,
            max_tokens=4096
        )
        return resp.choices[0].message.content
