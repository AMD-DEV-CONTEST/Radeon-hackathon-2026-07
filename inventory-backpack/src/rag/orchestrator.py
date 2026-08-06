# Register new knowledge assistant in orchestrator

from .specialists.knowledge_assistant import KnowledgeAssistant

class AgentOrchestrator:
    def __init__(self):
        self.agents = {
            # Existing agents...
            "code": CodeAgent(),
            "creative": CreativeAgent(),
            # Added
            "knowledge": KnowledgeAssistant(),
        }

    async def route(self, query: str, context: dict) -> str:
        """Route to the appropriate agent"""

        # Detect whether knowledge base query is needed
        if self._is_knowledge_query(query):
            return await self.agents["knowledge"].process(query, context)

        # ... other routing logic

    def _is_knowledge_query(self, query: str) -> bool:
        """Determine whether knowledge base is needed"""
        keywords = ["文档", "资料", "根据", "查询", "搜索", "找到"]
        return any(kw in query for kw in keywords)