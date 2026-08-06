from ..config import settings

class LLMService:
    def __init__(self):
        self.enabled = settings.LOCAL_LLM_ENABLED
        self.model_path = settings.LOCAL_LLM_PATH
        self.lora_path = settings.LORA_PATH
        
    def generate(self, prompt: str):
        return "LLM Response Stub"

llm_service = LLMService()
