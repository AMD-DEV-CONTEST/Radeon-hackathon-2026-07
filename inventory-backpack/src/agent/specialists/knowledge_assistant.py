"""Knowledge assistant"""

from __future__ import annotations

from ..base import BaseAgent
from ...utils.api_client import LLMClient, get_llm_client
from ...utils.config_loader import load_config


class KnowledgeAssistant(BaseAgent):
    def __init__(self, name: str = "knowledge_assistant"):
        super().__init__(name)
        self.rag = None
        self.llm_client: LLMClient | None = None
        self._llm_config = {}

    def initialize(self, *, config: dict, **_):
        """Initialize LLM + RAG"""
        # LLM config: prefer top-level, then remote
        remote = config.get("remote", {})
    
        self._llm_config = {
            "endpoint": config.get("endpoint") or remote.get("endpoint"),
            "api_key": config.get("api_key") or remote.get("api_key"),
            "model": config.get("model") or remote.get("model"),
            "timeout": config.get("timeout", remote.get("timeout", 45)),
        }
        # RAG init - pass full config
        from ...rag.pipeline import get_rag_pipeline
        
        full_config = config
        self.rag = get_rag_pipeline(config=full_config)
        
        print(f"[Agent] RAG 状态: {'✅ 已初始化' if self.rag._initialized else '❌ 未初始化'}")

    async def start(self):
        self.llm_client = await get_llm_client(**self._llm_config)

    async def stop(self):
        if self.llm_client:
            await self.llm_client.__aexit__(None, None, None)

    async def process(self, query: str, **_) -> dict:
        # Query RAG
        rag_result = self.rag.query(query) if self.rag else {"contexts": [], "sources": []}
        
        has_context = bool(rag_result.get("contexts"))
        print(f"[Agent] RAG 上下文: {'✅ 有' if has_context else '❌ 无'} ({len(rag_result.get('contexts', []))} 条)")
        
        if not has_context:
            answer = await self._call_llm(query)
            return {"answer": answer, "sources": [], "mode": "direct"}
        
        # Has context, build RAG prompt
        prompt = self._build_prompt(query, rag_result)
        answer = await self._call_llm(prompt)
        
        return {
            "answer": answer,
            "sources": rag_result.get("sources", []),
            "mode": "rag",
        }

    def _build_prompt(self, query: str, rag_result: dict) -> str:
        contexts = "\n\n---\n\n".join(rag_result["contexts"])
        return f"""基于以下参考文档回答问题。如果文档中没有相关信息，请明确说明。

参考文档：
{contexts}

问题：{query}

请基于上述文档回答："""

    async def _call_llm(self, prompt: str) -> str:
        response = await self.llm_client.chat(
            messages=[{"role": "user", "content": prompt}]
        )
        return response["choices"][0]["message"]["content"]