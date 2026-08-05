"""
Causal graph engine for tracking dependencies and consequences
"""
import logging
from datetime import datetime
from typing import Optional, Any
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

import networkx as nx

logger = logging.getLogger(__name__)


class NodeType(Enum):
    """Types of nodes in the causal graph"""
    CODE_CHANGE = "code_change"
    FILE_EDIT = "file_edit"
    GIT_COMMIT = "git_commit"
    DEPENDENCY_UPDATE = "dependency_update"
    TEST_RUN = "test_run"
    TEST_FAILURE = "test_failure"
    BUILD_EVENT = "build_event"
    CONFIG_CHANGE = "config_change"
    AGENT_ACTION = "agent_action"
    USER_ACTION = "user_action"


class EdgeType(Enum):
    """Types of edges (relationships) in the causal graph"""
    CAUSES = "causes"
    DEPENDS_ON = "depends_on"
    BREAKS = "breaks"
    FIXES = "fixes"
    MODIFIES = "modifies"
    TRIGGERS = "triggers"
    REQUIRES = "requires"


@dataclass
class CausalNode:
    """Node in the causal graph representing an event or state"""
    id: str
    type: NodeType
    timestamp: datetime
    data: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "type": self.type.value,
            "timestamp": self.timestamp.isoformat(),
            "data": self.data,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "CausalNode":
        return cls(
            id=data["id"],
            type=NodeType(data["type"]),
            timestamp=datetime.fromisoformat(data["timestamp"]),
            data=data.get("data", {}),
            metadata=data.get("metadata", {}),
        )


@dataclass
class CausalEdge:
    """Edge in the causal graph representing a relationship"""
    source: str
    target: str
    type: EdgeType
    weight: float = 1.0
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "target": self.target,
            "type": self.type.value,
            "weight": self.weight,
            "metadata": self.metadata,
        }


class CausalGraph:
    """
    Living causal graph that tracks all events and their consequences
    Optimized for temporal traversal and impact analysis
    """

    def __init__(self):
        self.graph = nx.MultiDiGraph()  # Directed graph with multiple edges
        self._node_index: dict[str, CausalNode] = {}
        self._time_index: list[tuple[datetime, str]] = []  # Sorted by time

    def add_node(self, node: CausalNode) -> None:
        """Add a node to the causal graph"""
        self.graph.add_node(
            node.id,
            type=node.type.value,
            timestamp=node.timestamp,
            data=node.data,
            metadata=node.metadata,
        )
        self._node_index[node.id] = node
        self._time_index.append((node.timestamp, node.id))
        self._time_index.sort()  # Keep sorted for temporal queries

        logger.debug(f"Added node {node.id} ({node.type.value})")

    def add_edge(self, edge: CausalEdge) -> None:
        """Add an edge (causal relationship) to the graph"""
        if edge.source not in self._node_index:
            logger.warning(f"Source node {edge.source} not found")
            return
        if edge.target not in self._node_index:
            logger.warning(f"Target node {edge.target} not found")
            return

        self.graph.add_edge(
            edge.source,
            edge.target,
            type=edge.type.value,
            weight=edge.weight,
            metadata=edge.metadata,
        )

        logger.debug(f"Added edge {edge.source} -> {edge.target} ({edge.type.value})")

    def get_node(self, node_id: str) -> Optional[CausalNode]:
        """Get a node by ID"""
        return self._node_index.get(node_id)

    def trace_backward(
        self,
        node_id: str,
        max_depth: int = 10,
        edge_types: Optional[list[EdgeType]] = None,
    ) -> list[CausalNode]:
        """
        Trace backward through the causal graph to find root causes
        Returns nodes in reverse chronological order
        """
        if node_id not in self.graph:
            return []

        # BFS backward through predecessors
        visited = set()
        queue = [(node_id, 0)]
        path = []

        while queue:
            current_id, depth = queue.pop(0)

            if current_id in visited or depth > max_depth:
                continue

            visited.add(current_id)
            node = self.get_node(current_id)
            if node:
                path.append(node)

            # Get predecessors (nodes that caused this one)
            for pred in self.graph.predecessors(current_id):
                # Filter by edge type if specified
                if edge_types:
                    edges = self.graph.get_edge_data(pred, current_id)
                    if not any(
                        EdgeType(e["type"]) in edge_types
                        for e in edges.values()
                    ):
                        continue

                queue.append((pred, depth + 1))

        # Sort by timestamp (oldest first)
        path.sort(key=lambda n: n.timestamp)
        return path

    def trace_forward(
        self,
        node_id: str,
        max_depth: int = 10,
        edge_types: Optional[list[EdgeType]] = None,
    ) -> list[CausalNode]:
        """
        Trace forward through the causal graph to find consequences
        Returns nodes in chronological order
        """
        if node_id not in self.graph:
            return []

        visited = set()
        queue = [(node_id, 0)]
        path = []

        while queue:
            current_id, depth = queue.pop(0)

            if current_id in visited or depth > max_depth:
                continue

            visited.add(current_id)
            node = self.get_node(current_id)
            if node:
                path.append(node)

            # Get successors (nodes caused by this one)
            for succ in self.graph.successors(current_id):
                if edge_types:
                    edges = self.graph.get_edge_data(current_id, succ)
                    if not any(
                        EdgeType(e["type"]) in edge_types
                        for e in edges.values()
                    ):
                        continue

                queue.append((succ, depth + 1))

        path.sort(key=lambda n: n.timestamp)
        return path

    def find_root_causes(self, node_id: str) -> list[CausalNode]:
        """
        Find root causes for a given node (nodes with no predecessors in the path)
        """
        path = self.trace_backward(node_id)
        root_causes = []

        for node in path:
            # Check if this node has no predecessors in our path
            preds = list(self.graph.predecessors(node.id))
            if not any(p in [n.id for n in path] for p in preds):
                root_causes.append(node)

        return root_causes

    def calculate_blast_radius(self, node_id: str, max_depth: int = 5) -> int:
        """
        Calculate the "blast radius" - how many nodes are affected by this change
        """
        affected = self.trace_forward(node_id, max_depth=max_depth)
        return len(affected)

    def get_timeline(
        self,
        start_time: datetime,
        end_time: datetime,
        node_types: Optional[list[NodeType]] = None,
    ) -> list[CausalNode]:
        """
        Get all nodes within a time range
        """
        nodes = []
        for timestamp, node_id in self._time_index:
            if timestamp < start_time:
                continue
            if timestamp > end_time:
                break

            node = self.get_node(node_id)
            if node:
                if not node_types or node.type in node_types:
                    nodes.append(node)

        return nodes

    def find_similar_patterns(
        self,
        node_id: str,
        similarity_threshold: float = 0.7,
    ) -> list[tuple[CausalNode, float]]:
        """
        Find similar patterns in the graph history
        Useful for suggesting fixes based on past solutions
        """
        # Future: Implement pattern matching using graph embeddings
        return []

    def export_subgraph(self, node_ids: list[str]) -> nx.DiGraph:
        """
        Export a subgraph containing specified nodes and their connections
        """
        return self.graph.subgraph(node_ids).copy()

    def get_stats(self) -> dict[str, Any]:
        """Get statistics about the causal graph"""
        return {
            "total_nodes": len(self.graph.nodes),
            "total_edges": len(self.graph.edges),
            "node_types": {
                node_type.value: sum(
                    1 for n in self.graph.nodes
                    if self.graph.nodes[n].get("type") == node_type.value
                )
                for node_type in NodeType
            },
            "avg_degree": sum(dict(self.graph.degree()).values()) / len(self.graph.nodes)
            if len(self.graph.nodes) > 0 else 0,
            "is_dag": nx.is_directed_acyclic_graph(self.graph),
        }

    def clear(self) -> None:
        """Clear the entire graph"""
        self.graph.clear()
        self._node_index.clear()
        self._time_index.clear()
        logger.info("Causal graph cleared")
