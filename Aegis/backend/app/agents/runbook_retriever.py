"""Runbook Retriever agent — the RAG-powered agent that surfaces precedent."""
from app.agents.base import BaseAgent
from app.tools.runbook_search import RunbookSearchTool

_SYSTEM_PROMPT = """You are the Runbook Retrieval agent. Given search results from past
incident postmortems and runbooks, summarize which precedent (if any) is most relevant
to the current incident, in 2-4 sentences, and state a confidence (0-1)."""


class RunbookRetrieverAgent(BaseAgent):
    name = "runbook_retriever"
    system_prompt = _SYSTEM_PROMPT

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.search_tool = RunbookSearchTool(self.db)

    async def act(self, state: dict) -> dict:
        query = f"{state.get('title', '')} {state.get('description', '')}"
        tool_result = await self.search_tool.run(query=query, top_k=5)

        result = await self.inference.complete(
            system_prompt=self.system_prompt,
            user_prompt=f"Query: {query}\nSearch results: {tool_result.output}",
            temperature=0.2,
            max_tokens=400,
        )

        evidence = state.get("evidence", [])
        evidence.append(
            {
                "evidence_type": "runbook",
                "source_agent": self.name,
                "summary": result.text,
                "raw_data": tool_result.output or {},
            }
        )
        return {
            "evidence": evidence,
            "_reasoning": result.text,
            "_tool_calls": [{"tool": self.search_tool.name, "success": tool_result.success}],
            "_tokens_generated": result.completion_tokens,
            "_tokens_per_second": result.tokens_per_second,
        }
