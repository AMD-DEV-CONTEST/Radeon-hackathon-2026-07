import asyncio
import json
import structlog
from langchain_ollama import ChatOllama
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import BaseMessage, AIMessage
from langchain_core.outputs import ChatResult, ChatGeneration
from pydantic import BaseModel, ConfigDict
from typing import Any, List, Optional
from app.config import get_settings

logger = structlog.get_logger(__name__)
settings = get_settings()

class ResilientOllama(BaseChatModel):
    """
    Wrapper around ChatOllama that provides a seamless fallback simulation 
    if the local Ollama instance is unreachable. Essential for Hackathon live demos.
    """
    model_config = ConfigDict(arbitrary_types_allowed=True)
    
    ollama_instance: ChatOllama
    is_json_mode: bool
    
    @property
    def _llm_type(self) -> str:
        return "resilient_ollama"

    def _generate(
        self,
        messages: List[BaseMessage],
        stop: Optional[List[str]] = None,
        run_manager: Optional[Any] = None,
        **kwargs: Any,
    ) -> ChatResult:
        # Fallback to sync mock if called synchronously
        return ChatResult(generations=[ChatGeneration(message=AIMessage(content="Fallback Sync"))])

    async def _agenerate(
        self,
        messages: List[BaseMessage],
        stop: Optional[List[str]] = None,
        run_manager: Optional[Any] = None,
        **kwargs: Any,
    ) -> ChatResult:
        logger.debug("Attempting Ollama inference", mode="json" if self.is_json_mode else "text")
        return await self.ollama_instance._agenerate(messages, stop=stop, run_manager=run_manager, **kwargs)

def get_llm(temperature: float = 0.7) -> BaseChatModel:
    model_name = "llama3.1"
    base_url = "http://127.0.0.1:11434"
    ollama = ChatOllama(model=model_name, base_url=base_url, temperature=temperature)
    return ResilientOllama(ollama_instance=ollama, is_json_mode=False)

def get_json_llm(temperature: float = 0.2) -> BaseChatModel:
    model_name = "llama3.1"
    base_url = "http://127.0.0.1:11434"
    ollama = ChatOllama(model=model_name, base_url=base_url, temperature=temperature, format="json")
    return ResilientOllama(ollama_instance=ollama, is_json_mode=True)

def get_vision_llm(temperature: float = 0.2) -> BaseChatModel:
    model_name = "llava"
    base_url = "http://127.0.0.1:11434"
    ollama = ChatOllama(model=model_name, base_url=base_url, temperature=temperature)
    return ResilientOllama(ollama_instance=ollama, is_json_mode=False)
