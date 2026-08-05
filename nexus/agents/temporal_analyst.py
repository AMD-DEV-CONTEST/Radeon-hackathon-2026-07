"""
Temporal Analyst Agent - Traces through causal history to find root causes
"""
import logging
from typing import Any

from nexus.agents.base import BaseAgent, AgentTask, AgentResult
from nexus.graph import CausalGraph, NodeType, EdgeType

logger = logging.getLogger(__name__)


class TemporalAnalystAgent(BaseAgent):
    """
    Specialized agent for analyzing causal history and finding root causes
    Traces backward through the causal graph to identify when/where issues originated
    """

    def __init__(self, agent_id: str, inference_engine, causal_graph: CausalGraph):
        super().__init__(agent_id, inference_engine, model_type="reasoning")
        self.causal_graph = causal_graph

    async def execute(self, task: AgentTask) -> AgentResult:
        """
        Execute temporal analysis on a problem
        """
        # Extract the node ID or problem description
        node_id = task.context.get("node_id")
        problem_description = task.context.get("problem", task.description)

        if not node_id and not problem_description:
            return AgentResult(
                task_id=task.id,
                agent_id=self.agent_id,
                success=False,
                output=None,
                error="No node_id or problem description provided",
            )

        # If we have a node ID, trace backward through the causal graph
        causal_path = []
        root_causes = []

        if node_id:
            causal_path = self.causal_graph.trace_backward(node_id, max_depth=10)
            root_causes = self.causal_graph.find_root_causes(node_id)

        # Build context for the LLM
        context_text = self._build_analysis_context(
            problem_description,
            causal_path,
            root_causes,
        )

        # Generate analysis using LLM
        prompt = f"""You are a Temporal Analyst in the NEXUS causal debugging system.
Your specialty is tracing backward through time to find the root causes of problems.

PROBLEM: {problem_description}

CAUSAL HISTORY:
{context_text}

Analyze the causal history and:
1. Identify the root cause(s) of this problem
2. Explain the causal chain from root cause to current problem
3. Estimate when the problem was introduced
4. Suggest what should have been done differently

Provide a clear, structured analysis."""

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
            "problem": problem_description,
            "causal_path_length": len(causal_path),
            "root_causes_found": len(root_causes),
            "root_cause_nodes": [
                {
                    "id": node.id,
                    "type": node.type.value,
                    "timestamp": node.timestamp.isoformat(),
                    "data": node.data,
                }
                for node in root_causes
            ],
            "llm_analysis": inference_result.text,
        }

        return AgentResult(
            task_id=task.id,
            agent_id=self.agent_id,
            success=True,
            output=analysis,
            reasoning=f"Traced {len(causal_path)} causal events, found {len(root_causes)} root causes",
            metadata={
                "inference_tokens": inference_result.tokens,
                "inference_latency_ms": inference_result.latency_ms,
            },
        )

    def _build_analysis_context(
        self,
        problem: str,
        causal_path: list,
        root_causes: list,
    ) -> str:
        """Build a readable context from causal graph data"""
        lines = []

        if causal_path:
            lines.append("Causal Path (chronological):")
            for i, node in enumerate(causal_path, 1):
                lines.append(
                    f"{i}. [{node.timestamp.strftime('%H:%M:%S')}] "
                    f"{node.type.value}: {node.data.get('description', node.id)}"
                )
            lines.append("")

        if root_causes:
            lines.append("Root Causes Identified:")
            for node in root_causes:
                lines.append(
                    f"- {node.type.value} at {node.timestamp.strftime('%H:%M:%S')}: "
                    f"{node.data.get('description', node.id)}"
                )
            lines.append("")
        else:
            lines.append("No clear root causes found in causal history.")
            lines.append("")

        if not causal_path:
            lines.append("No causal history available. This may be a new issue.")

        return "\n".join(lines)
