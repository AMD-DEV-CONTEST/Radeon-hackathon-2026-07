"""
Basic tests to verify NEXUS components work
"""
import pytest
from datetime import datetime
from pathlib import Path

from nexus.core.config import NexusConfig
from nexus.graph import CausalGraph, CausalNode, CausalEdge, NodeType, EdgeType
from nexus.agents import AgentTask, AgentPool


class TestConfig:
    """Test configuration management"""

    def test_config_creation(self):
        """Test that config can be created with defaults"""
        config = NexusConfig()
        assert config.inference.device in ["hip", "cuda", "cpu"]
        assert config.agents.max_agents > 0
        assert config.inference.max_parallel_agents > 0

    def test_config_paths(self):
        """Test that paths are properly configured"""
        config = NexusConfig()
        assert config.project_root.is_absolute()
        assert config.nexus_dir.is_absolute()


class TestCausalGraph:
    """Test causal graph operations"""

    def test_graph_creation(self):
        """Test creating a causal graph"""
        graph = CausalGraph()
        assert graph.graph.number_of_nodes() == 0
        assert graph.graph.number_of_edges() == 0

    def test_add_node(self):
        """Test adding nodes to graph"""
        graph = CausalGraph()

        node = CausalNode(
            id="test_1",
            type=NodeType.CODE_CHANGE,
            timestamp=datetime.now(),
            data={"description": "Test change"},
        )

        graph.add_node(node)
        assert graph.graph.number_of_nodes() == 1
        assert graph.get_node("test_1") == node

    def test_add_edge(self):
        """Test adding edges to graph"""
        graph = CausalGraph()

        node1 = CausalNode(
            id="test_1",
            type=NodeType.CODE_CHANGE,
            timestamp=datetime.now(),
        )
        node2 = CausalNode(
            id="test_2",
            type=NodeType.TEST_FAILURE,
            timestamp=datetime.now(),
        )

        graph.add_node(node1)
        graph.add_node(node2)

        edge = CausalEdge(
            source="test_1",
            target="test_2",
            type=EdgeType.CAUSES,
        )

        graph.add_edge(edge)
        assert graph.graph.number_of_edges() == 1

    def test_trace_backward(self):
        """Test backward traversal"""
        graph = CausalGraph()

        # Create a chain: node1 -> node2 -> node3
        node1 = CausalNode(id="n1", type=NodeType.CODE_CHANGE, timestamp=datetime.now())
        node2 = CausalNode(id="n2", type=NodeType.GIT_COMMIT, timestamp=datetime.now())
        node3 = CausalNode(id="n3", type=NodeType.TEST_FAILURE, timestamp=datetime.now())

        graph.add_node(node1)
        graph.add_node(node2)
        graph.add_node(node3)

        graph.add_edge(CausalEdge("n1", "n2", EdgeType.CAUSES))
        graph.add_edge(CausalEdge("n2", "n3", EdgeType.CAUSES))

        # Trace backward from n3
        path = graph.trace_backward("n3", max_depth=10)
        assert len(path) == 3  # Should include all nodes
        assert path[0].id == "n1"  # Oldest first
        assert path[-1].id == "n3"  # Newest last

    def test_find_root_causes(self):
        """Test finding root causes"""
        graph = CausalGraph()

        # Create a chain
        root = CausalNode(id="root", type=NodeType.CONFIG_CHANGE, timestamp=datetime.now())
        middle = CausalNode(id="middle", type=NodeType.GIT_COMMIT, timestamp=datetime.now())
        problem = CausalNode(id="problem", type=NodeType.TEST_FAILURE, timestamp=datetime.now())

        graph.add_node(root)
        graph.add_node(middle)
        graph.add_node(problem)

        graph.add_edge(CausalEdge("root", "middle", EdgeType.CAUSES))
        graph.add_edge(CausalEdge("middle", "problem", EdgeType.CAUSES))

        # Find root causes
        roots = graph.find_root_causes("problem")
        assert len(roots) == 1
        assert roots[0].id == "root"


class TestAgentFramework:
    """Test agent framework"""

    def test_agent_task_creation(self):
        """Test creating agent tasks"""
        task = AgentTask(
            description="Test task",
            context={"key": "value"},
        )
        assert task.description == "Test task"
        assert task.context["key"] == "value"
        assert task.id.startswith("task_")

    def test_agent_pool_creation(self):
        """Test creating agent pool"""
        pool = AgentPool(max_concurrent=4)
        assert len(pool.agents) == 0

    def test_agent_pool_status(self):
        """Test getting agent status"""
        pool = AgentPool(max_concurrent=4)
        status = pool.get_agent_status()
        assert isinstance(status, dict)


class TestInferenceEngine:
    """Test inference engine (without actual models)"""

    def test_inference_config(self):
        """Test inference configuration"""
        from nexus.core.config import InferenceConfig

        config = InferenceConfig()
        assert config.device in ["hip", "cuda", "cpu"]
        assert config.max_parallel_agents > 0
        assert config.reasoning_quantization in ["int4", "int8", "fp16", "fp32"]

    @pytest.mark.asyncio
    async def test_engine_initialization(self):
        """Test engine can be initialized (but not load models)"""
        from nexus.inference.engine import NexusInferenceEngine
        from nexus.core.config import InferenceConfig

        config = InferenceConfig(device="cpu")  # Use CPU for testing
        engine = NexusInferenceEngine(config)

        # Just test structure, don't actually load models
        assert engine.config.device == "cpu"
        assert len(engine.models) == 0  # Not initialized yet


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
