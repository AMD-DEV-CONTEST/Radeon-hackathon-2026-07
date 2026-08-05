"""
Master Orchestrator - The brain of NEXUS that coordinates all agents
"""
import asyncio
import logging
from pathlib import Path
from typing import Optional, Any
from datetime import datetime
from uuid import uuid4

from nexus.core.config import NexusConfig
from nexus.inference.engine import NexusInferenceEngine
from nexus.graph import CausalGraph, CausalNode, CausalEdge, NodeType, EdgeType
from nexus.agents import (
    AgentPool,
    AgentTask,
    AgentResult,
    TemporalAnalystAgent,
    CodeArchaeologistAgent,
    FixSimulatorAgent,
)

logger = logging.getLogger(__name__)


class Orchestrator:
    """
    Master Orchestrator for NEXUS
    Coordinates agents, manages causal graph, and provides high-level operations
    """

    def __init__(self, config: Optional[NexusConfig] = None):
        self.config = config or NexusConfig()
        self.inference_engine = NexusInferenceEngine(self.config.inference)
        self.causal_graph = CausalGraph()
        self.agent_pool = AgentPool(max_concurrent=self.config.agents.max_agents)
        self._initialized = False

    async def initialize(self) -> None:
        """Initialize the orchestrator and all subsystems"""
        if self._initialized:
            return

        logger.info("Initializing NEXUS Orchestrator")

        # Ensure directories exist
        self.config.ensure_directories()

        # Initialize inference engine
        await self.inference_engine.initialize()

        # Register core agents
        await self._register_core_agents()

        self._initialized = True
        logger.info("NEXUS Orchestrator initialized successfully")

    async def _register_core_agents(self) -> None:
        """Register the core agent types"""
        # Temporal Analyst
        if self.config.agents.enable_temporal_analyst:
            temporal_analyst = TemporalAnalystAgent(
                agent_id="temporal_analyst",
                inference_engine=self.inference_engine,
                causal_graph=self.causal_graph,
            )
            self.agent_pool.register_agent(temporal_analyst)

        # Code Archaeologist
        if self.config.agents.enable_code_archaeologist:
            code_archaeologist = CodeArchaeologistAgent(
                agent_id="code_archaeologist",
                inference_engine=self.inference_engine,
                project_root=self.config.project_root,
            )
            self.agent_pool.register_agent(code_archaeologist)

        # Fix Simulator
        if self.config.agents.enable_fix_simulator:
            fix_simulator = FixSimulatorAgent(
                agent_id="fix_simulator",
                inference_engine=self.inference_engine,
                causal_graph=self.causal_graph,
            )
            self.agent_pool.register_agent(fix_simulator)

        logger.info(f"Registered {len(self.agent_pool.agents)} core agents")

    async def debug_problem(self, problem_description: str) -> dict[str, Any]:
        """
        High-level debugging workflow - the main NEXUS operation
        Coordinates multiple agents to debug a problem
        """
        if not self._initialized:
            await self.initialize()

        logger.info(f"Starting debug workflow for: {problem_description}")

        # Create a problem node in the causal graph
        problem_node = CausalNode(
            id=f"problem_{uuid4().hex[:8]}",
            type=NodeType.USER_ACTION,
            timestamp=datetime.now(),
            data={"description": problem_description},
        )
        self.causal_graph.add_node(problem_node)

        # Phase 1: Temporal Analysis (find root causes)
        temporal_task = AgentTask(
            description=f"Find root causes for: {problem_description}",
            context={
                "node_id": problem_node.id,
                "problem": problem_description,
            },
        )

        logger.info("Phase 1: Running temporal analysis")
        temporal_result = await self.agent_pool.execute_task(
            "temporal_analyst",
            temporal_task,
        )

        # Phase 2: Code Archaeology (find patterns and context)
        code_task = AgentTask(
            description=f"Search for patterns related to: {problem_description}",
            context={
                "query": problem_description,
                "search_type": "pattern",
            },
        )

        logger.info("Phase 2: Running code archaeology")
        code_result = await self.agent_pool.execute_task(
            "code_archaeologist",
            code_task,
        )

        # Phase 3: Fix Simulation (generate and test solutions)
        root_cause = "Unknown"
        if temporal_result.success and temporal_result.output:
            root_causes = temporal_result.output.get("root_cause_nodes", [])
            if root_causes:
                root_cause = root_causes[0].get("data", {}).get("description", "Unknown")

        simulation_task = AgentTask(
            description=f"Simulate fixes for: {problem_description}",
            context={
                "problem": problem_description,
                "root_cause": root_cause,
                "node_id": problem_node.id,
            },
        )

        logger.info("Phase 3: Running fix simulation")
        simulation_result = await self.agent_pool.execute_task(
            "fix_simulator",
            simulation_task,
        )

        # Compile results
        debug_report = {
            "problem": problem_description,
            "timestamp": datetime.now().isoformat(),
            "temporal_analysis": temporal_result.output if temporal_result.success else None,
            "code_analysis": code_result.output if code_result.success else None,
            "fix_simulations": simulation_result.output if simulation_result.success else None,
            "recommendation": self._generate_recommendation(
                temporal_result,
                code_result,
                simulation_result,
            ),
            "performance": {
                "temporal_latency_ms": temporal_result.latency_ms,
                "code_latency_ms": code_result.latency_ms,
                "simulation_latency_ms": simulation_result.latency_ms,
                "total_latency_ms": (
                    temporal_result.latency_ms +
                    code_result.latency_ms +
                    simulation_result.latency_ms
                ),
            },
        }

        logger.info("Debug workflow completed")
        return debug_report

    def _generate_recommendation(
        self,
        temporal_result: AgentResult,
        code_result: AgentResult,
        simulation_result: AgentResult,
    ) -> str:
        """Generate a human-readable recommendation"""
        lines = ["NEXUS Analysis Complete", "=" * 50, ""]

        # Root cause
        if temporal_result.success and temporal_result.output:
            root_causes = temporal_result.output.get("root_cause_nodes", [])
            if root_causes:
                lines.append("ROOT CAUSE:")
                for rc in root_causes[:2]:  # Top 2
                    lines.append(
                        f"- {rc['type']} at {rc['timestamp']}: "
                        f"{rc['data'].get('description', rc['id'])}"
                    )
                lines.append("")

        # Best fix
        if simulation_result.success and simulation_result.output:
            simulations = simulation_result.output.get("simulations", [])
            if simulations:
                best = simulations[0]
                lines.append("RECOMMENDED FIX:")
                lines.append(f"- {best['fix_description']}")
                lines.append(f"- Confidence: {best['confidence_score']:.0%}")
                lines.append(f"- Risk Level: {best['risk_level']}")
                lines.append("")

        if not any([temporal_result.success, simulation_result.success]):
            lines.append("Unable to generate recommendation - agent failures.")

        return "\n".join(lines)

    async def record_event(
        self,
        event_type: NodeType,
        description: str,
        data: Optional[dict[str, Any]] = None,
    ) -> str:
        """
        Record an event in the causal graph
        Returns the node ID
        """
        node = CausalNode(
            id=f"{event_type.value}_{uuid4().hex[:8]}",
            type=event_type,
            timestamp=datetime.now(),
            data={"description": description, **(data or {})},
        )
        self.causal_graph.add_node(node)
        return node.id

    async def link_events(
        self,
        source_id: str,
        target_id: str,
        relationship: EdgeType,
    ) -> None:
        """Create a causal link between two events"""
        edge = CausalEdge(
            source=source_id,
            target=target_id,
            type=relationship,
        )
        self.causal_graph.add_edge(edge)

    def get_graph_stats(self) -> dict[str, Any]:
        """Get statistics about the causal graph"""
        return self.causal_graph.get_stats()

    def get_agent_status(self) -> dict[str, dict[str, Any]]:
        """Get status of all agents"""
        return self.agent_pool.get_agent_status()

    async def shutdown(self) -> None:
        """Shutdown the orchestrator and cleanup"""
        logger.info("Shutting down NEXUS Orchestrator")
        await self.inference_engine.shutdown()
        self._initialized = False
