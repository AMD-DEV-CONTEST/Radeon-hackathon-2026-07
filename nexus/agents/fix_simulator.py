"""
Fix Simulator Agent - Simulates multiple fix strategies and ranks them
"""
import logging
from typing import Any, Literal
from datetime import datetime

from nexus.agents.base import BaseAgent, AgentTask, AgentResult
from nexus.graph import CausalGraph, CausalNode, NodeType

logger = logging.getLogger(__name__)


class SimulationBranch:
    """Represents a simulated timeline branch with a proposed fix"""

    def __init__(self, branch_id: str, fix_description: str):
        self.branch_id = branch_id
        self.fix_description = fix_description
        self.predicted_outcome: dict[str, Any] = {}
        self.confidence_score: float = 0.0
        self.blast_radius: int = 0
        self.risk_level: Literal["low", "medium", "high"] = "medium"


class FixSimulatorAgent(BaseAgent):
    """
    Specialized agent for simulating multiple fix strategies in parallel
    Predicts outcomes and ranks solutions by success probability
    """

    def __init__(self, agent_id: str, inference_engine, causal_graph: CausalGraph):
        super().__init__(agent_id, inference_engine, model_type="reasoning")
        self.causal_graph = causal_graph

    async def execute(self, task: AgentTask) -> AgentResult:
        """
        Simulate multiple fix strategies for a problem
        """
        problem_description = task.context.get("problem", task.description)
        root_cause = task.context.get("root_cause", "Unknown")
        proposed_fixes = task.context.get("proposed_fixes", [])
        node_id = task.context.get("node_id")

        # If no proposed fixes, generate some
        if not proposed_fixes:
            proposed_fixes = await self._generate_fix_strategies(
                problem_description,
                root_cause,
            )

        # Simulate each fix in parallel
        simulations = []
        for i, fix in enumerate(proposed_fixes):
            branch = SimulationBranch(f"branch_{i}", fix)
            simulation_result = await self._simulate_branch(
                branch,
                problem_description,
                root_cause,
                node_id,
            )
            simulations.append(simulation_result)

        # Rank simulations by multiple criteria
        ranked_simulations = self._rank_simulations(simulations)

        # Generate recommendation
        recommendation = await self._generate_recommendation(
            problem_description,
            ranked_simulations,
        )

        return AgentResult(
            task_id=task.id,
            agent_id=self.agent_id,
            success=True,
            output={
                "problem": problem_description,
                "simulations": [
                    {
                        "branch_id": sim.branch_id,
                        "fix_description": sim.fix_description,
                        "confidence_score": sim.confidence_score,
                        "blast_radius": sim.blast_radius,
                        "risk_level": sim.risk_level,
                        "predicted_outcome": sim.predicted_outcome,
                    }
                    for sim in ranked_simulations
                ],
                "recommendation": recommendation,
            },
            reasoning=f"Simulated {len(simulations)} fix strategies",
        )

    async def _generate_fix_strategies(
        self,
        problem: str,
        root_cause: str,
    ) -> list[str]:
        """
        Generate multiple fix strategies using LLM
        """
        prompt = f"""You are a Fix Simulator in the NEXUS system.
Generate 3-4 different approaches to fix this problem:

PROBLEM: {problem}
ROOT CAUSE: {root_cause}

For each fix strategy, provide:
- A clear description of the approach
- What changes would be needed
- Potential trade-offs

Format your response as a numbered list of fix strategies."""

        inference_result = await self._infer(prompt, max_tokens=512, temperature=0.8)

        if not inference_result.success:
            # Fallback strategies
            return [
                f"Revert changes that caused: {root_cause}",
                f"Modify code to handle: {problem}",
                f"Add safeguards for: {problem}",
            ]

        # Parse out individual strategies (simple parsing for MVP)
        strategies = []
        for line in inference_result.text.split("\n"):
            line = line.strip()
            if line and (line[0].isdigit() or line.startswith("-")):
                # Remove numbering
                strategy = line.lstrip("0123456789.-) ")
                if strategy:
                    strategies.append(strategy)

        return strategies[:4]  # Limit to 4 strategies

    async def _simulate_branch(
        self,
        branch: SimulationBranch,
        problem: str,
        root_cause: str,
        node_id: Optional[str],
    ) -> SimulationBranch:
        """
        Simulate a specific fix strategy
        """
        # Build simulation context
        blast_radius = 0
        if node_id:
            blast_radius = self.causal_graph.calculate_blast_radius(node_id)

        prompt = f"""You are simulating the outcome of applying a fix.

PROBLEM: {problem}
ROOT CAUSE: {root_cause}
PROPOSED FIX: {branch.fix_description}
BLAST RADIUS: {blast_radius} affected components

Predict the outcome of this fix:
1. Success probability (0-100%)
2. Potential side effects
3. Risk level (low/medium/high)
4. Would this fix the root cause or just symptoms?

Provide a brief analysis (3-4 sentences)."""

        inference_result = await self._infer(prompt, max_tokens=256, temperature=0.3)

        # Parse the analysis (simplified for MVP)
        analysis_text = inference_result.text if inference_result.success else ""

        # Extract confidence score (look for percentage)
        confidence = 0.5  # default
        for word in analysis_text.split():
            if "%" in word:
                try:
                    confidence = float(word.strip("%")) / 100.0
                    break
                except ValueError:
                    pass

        # Determine risk level from text
        risk_level = "medium"
        if "low risk" in analysis_text.lower():
            risk_level = "low"
        elif "high risk" in analysis_text.lower():
            risk_level = "high"

        branch.confidence_score = confidence
        branch.blast_radius = blast_radius
        branch.risk_level = risk_level
        branch.predicted_outcome = {
            "analysis": analysis_text,
            "success_probability": confidence,
        }

        return branch

    def _rank_simulations(
        self,
        simulations: list[SimulationBranch],
    ) -> list[SimulationBranch]:
        """
        Rank simulations by multiple criteria:
        - Confidence score (higher is better)
        - Blast radius (lower is better)
        - Risk level (lower is better)
        """
        risk_scores = {"low": 0, "medium": 1, "high": 2}

        def score(sim: SimulationBranch) -> float:
            # Composite score (higher is better)
            confidence_component = sim.confidence_score * 100
            blast_radius_penalty = min(sim.blast_radius * 2, 50)
            risk_penalty = risk_scores[sim.risk_level] * 10
            return confidence_component - blast_radius_penalty - risk_penalty

        return sorted(simulations, key=score, reverse=True)

    async def _generate_recommendation(
        self,
        problem: str,
        ranked_simulations: list[SimulationBranch],
    ) -> str:
        """
        Generate a final recommendation based on simulation results
        """
        if not ranked_simulations:
            return "No viable fix strategies found."

        best = ranked_simulations[0]

        prompt = f"""Based on simulation results, recommend the best fix strategy:

PROBLEM: {problem}

TOP SOLUTION:
- Fix: {best.fix_description}
- Confidence: {best.confidence_score:.0%}
- Risk: {best.risk_level}
- Blast radius: {best.blast_radius} components

Provide a clear recommendation (2-3 sentences) explaining why this is the best approach."""

        inference_result = await self._infer(prompt, max_tokens=256, temperature=0.3)

        if inference_result.success:
            return inference_result.text
        else:
            return f"Recommend: {best.fix_description} (confidence: {best.confidence_score:.0%})"
