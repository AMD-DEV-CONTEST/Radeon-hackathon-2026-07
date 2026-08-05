"""
Code Archaeologist Agent - Searches codebase for patterns and related issues
"""
import logging
from pathlib import Path
from typing import Any, Optional
import ast

from nexus.agents.base import BaseAgent, AgentTask, AgentResult

logger = logging.getLogger(__name__)


class CodeArchaeologistAgent(BaseAgent):
    """
    Specialized agent for deep code analysis and pattern recognition
    Searches for similar issues, patterns, and historical context
    """

    def __init__(self, agent_id: str, inference_engine, project_root: Path):
        super().__init__(agent_id, inference_engine, model_type="code")
        self.project_root = project_root

    async def execute(self, task: AgentTask) -> AgentResult:
        """
        Execute code archaeology - search for patterns and context
        """
        search_query = task.context.get("query", task.description)
        file_path = task.context.get("file_path")
        search_type = task.context.get("search_type", "pattern")  # pattern, function, class, etc.

        # Gather code context
        code_context = await self._gather_code_context(file_path, search_query, search_type)

        # Build prompt for LLM analysis
        prompt = f"""You are a Code Archaeologist in the NEXUS system.
Your specialty is analyzing code patterns, finding similar issues, and providing historical context.

SEARCH QUERY: {search_query}

CODE CONTEXT:
{code_context}

Analyze the code and:
1. Identify relevant patterns or issues
2. Find similar code structures that might have the same problem
3. Suggest where to look for related issues
4. Provide historical context if patterns suggest common bugs

Provide a structured analysis with specific file paths and line numbers."""

        inference_result = await self._infer(prompt, max_tokens=1024, temperature=0.3)

        if not inference_result.success:
            return AgentResult(
                task_id=task.id,
                agent_id=self.agent_id,
                success=False,
                output=None,
                error=inference_result.error,
            )

        # Structure the output
        analysis = {
            "query": search_query,
            "search_type": search_type,
            "files_analyzed": code_context.get("files_found", 0),
            "patterns_found": [],  # Would be populated by actual pattern matching
            "llm_analysis": inference_result.text,
        }

        return AgentResult(
            task_id=task.id,
            agent_id=self.agent_id,
            success=True,
            output=analysis,
            reasoning=f"Analyzed code patterns for: {search_query}",
            metadata={
                "inference_tokens": inference_result.tokens,
                "inference_latency_ms": inference_result.latency_ms,
            },
        )

    async def _gather_code_context(
        self,
        file_path: Optional[str],
        search_query: str,
        search_type: str,
    ) -> dict[str, Any]:
        """
        Gather relevant code context for analysis
        In MVP, this is simplified - in production would use tree-sitter, AST, etc.
        """
        context = {
            "files_found": 0,
            "code_snippets": [],
        }

        # If specific file provided, read it
        if file_path:
            full_path = self.project_root / file_path
            if full_path.exists():
                try:
                    content = full_path.read_text(encoding="utf-8")
                    context["files_found"] = 1
                    context["code_snippets"].append({
                        "file": file_path,
                        "content": content[:2000],  # Limit to 2000 chars
                    })
                except Exception as e:
                    logger.warning(f"Failed to read {file_path}: {e}")

        # Return context
        # Future enhancements:
        # - Use tree-sitter to parse code
        # - Search for function/class definitions
        # - Find similar patterns using AST matching
        # - Search git history for related changes

        return self._format_code_context(context)

    def _format_code_context(self, context: dict[str, Any]) -> str:
        """Format code context as readable text"""
        lines = []

        if context["files_found"] == 0:
            lines.append("No code context available.")
            return "\n".join(lines)

        lines.append(f"Files found: {context['files_found']}")
        lines.append("")

        for snippet in context["code_snippets"]:
            lines.append(f"File: {snippet['file']}")
            lines.append("```")
            lines.append(snippet["content"])
            lines.append("```")
            lines.append("")

        return "\n".join(lines)

    async def search_function_usage(self, function_name: str) -> list[dict[str, Any]]:
        """
        Search for where a function is used across the codebase
        Future: implement with tree-sitter integration
        """
        # To be implemented
        return []

    async def find_similar_code(self, code_snippet: str) -> list[dict[str, Any]]:
        """
        Find similar code patterns using embeddings or AST matching
        Future: implement with code embeddings
        """
        # To be implemented with code embeddings or AST similarity
        return []
