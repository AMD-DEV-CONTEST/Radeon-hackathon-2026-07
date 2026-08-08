"""Dependency Graph — builds and validates a DAG of tasks.

The graph:
  - Nodes are tasks
  - Edges are dependencies (task A depends on task B)
  - Topological sort produces a valid execution order
  - Cycle detection prevents invalid graphs
  - Wave grouping identifies tasks that can run in parallel
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set, Tuple

from .task_decomposer import Task


@dataclass
class GraphNode:
    """A node in the dependency graph."""
    task: Task
    dependencies: Set[str] = field(default_factory=set)
    dependents: Set[str] = field(default_factory=set)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "task": self.task.to_dict(),
            "dependencies": list(self.dependencies),
            "dependents": list(self.dependents),
        }


@dataclass
class GraphValidation:
    """Result of graph validation."""
    valid: bool
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    cycles: List[List[str]] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "valid": self.valid,
            "errors": self.errors,
            "warnings": self.warnings,
            "cycles": self.cycles,
        }


class DependencyGraph:
    """A DAG of tasks with dependency tracking."""

    def __init__(self):
        self.nodes: Dict[str, GraphNode] = {}
        self._task_index: Dict[str, Task] = {}

    @classmethod
    def from_tasks(cls, tasks: List[Task]) -> "DependencyGraph":
        """Build a graph from a list of tasks."""
        graph = cls()
        for task in tasks:
            graph.add_task(task)
        return graph

    def add_task(self, task: Task) -> None:
        """Add a task to the graph."""
        node = GraphNode(task=task, dependencies=set(task.depends_on))
        self.nodes[task.id] = node
        self._task_index[task.id] = task
        # Update dependents of dependencies
        for dep_id in task.depends_on:
            if dep_id in self.nodes:
                self.nodes[dep_id].dependents.add(task.id)

    def validate(self) -> GraphValidation:
        """Validate the graph for cycles and missing dependencies."""
        result = GraphValidation(valid=True)

        # Check for missing dependencies
        for task_id, node in self.nodes.items():
            for dep_id in node.dependencies:
                if dep_id not in self.nodes:
                    result.errors.append(
                        f"Task {task_id} depends on missing task {dep_id}"
                    )
                    result.valid = False

        # Check for cycles
        cycles = self._detect_cycles()
        if cycles:
            result.cycles = cycles
            result.errors.append(f"Found {len(cycles)} cycle(s)")
            result.valid = False

        # Warnings
        if not self.nodes:
            result.warnings.append("Empty graph")

        # Check for orphaned tasks (no dependents and no dependencies)
        for task_id, node in self.nodes.items():
            if not node.dependencies and not node.dependents:
                result.warnings.append(f"Task {task_id} is isolated")

        return result

    def topological_sort(self) -> List[str]:
        """Return tasks in topological order."""
        # Kahn's algorithm
        in_degree = {tid: len(node.dependencies) for tid, node in self.nodes.items()}
        queue = [tid for tid, deg in in_degree.items() if deg == 0]
        result: List[str] = []

        while queue:
            # Sort for deterministic order
            queue.sort()
            current = queue.pop(0)
            result.append(current)

            for dependent in self.nodes[current].dependents:
                in_degree[dependent] -= 1
                if in_degree[dependent] == 0:
                    queue.append(dependent)

        return result

    def build_waves(self) -> List[List[str]]:
        """Group tasks into waves (parallel-executable sets)."""
        waves: List[List[str]] = []
        completed: Set[str] = set()
        remaining = set(self.nodes.keys())

        while remaining:
            wave = []
            for task_id in sorted(remaining):
                node = self.nodes[task_id]
                if node.dependencies.issubset(completed):
                    wave.append(task_id)
            if not wave:
                # Cycle or invalid graph
                break
            waves.append(wave)
            completed.update(wave)
            remaining -= set(wave)

        return waves

    def critical_path(self) -> List[str]:
        """Find the longest path through the graph."""
        # Compute longest path using dynamic programming
        topo = self.topological_sort()
        if not topo:
            return []

        # duration = timeout for each task
        duration = {tid: self.nodes[tid].task.timeout for tid in topo}
        # longest_to[tid] = (length, path)
        longest_to: Dict[str, Tuple[float, List[str]]] = {}

        for tid in topo:
            node = self.nodes[tid]
            best = (duration[tid], [tid])
            for dep_id in node.dependencies:
                if dep_id in longest_to:
                    candidate = (longest_to[dep_id][0] + duration[tid],
                                 longest_to[dep_id][1] + [tid])
                    if candidate[0] > best[0]:
                        best = candidate
            longest_to[tid] = best

        # Find the task with the longest total
        if not longest_to:
            return []
        end_tid = max(longest_to.keys(), key=lambda t: longest_to[t][0])
        return longest_to[end_tid][1]

    def _detect_cycles(self) -> List[List[str]]:
        """Detect cycles using DFS."""
        cycles: List[List[str]] = []
        WHITE, GRAY, BLACK = 0, 1, 2
        color = {tid: WHITE for tid in self.nodes}
        path: List[str] = []

        def dfs(task_id: str) -> None:
            color[task_id] = GRAY
            path.append(task_id)
            for dep_id in self.nodes[task_id].dependencies:
                if dep_id not in color:
                    continue
                if color[dep_id] == GRAY:
                    # Cycle found
                    cycle_start = path.index(dep_id)
                    cycles.append(path[cycle_start:] + [dep_id])
                elif color[dep_id] == WHITE:
                    dfs(dep_id)
            path.pop()
            color[task_id] = BLACK

        for tid in self.nodes:
            if color[tid] == WHITE:
                dfs(tid)

        return cycles

    def to_dict(self) -> Dict[str, Any]:
        return {
            "nodes": {tid: node.to_dict() for tid, node in self.nodes.items()},
            "topological_order": self.topological_sort(),
            "waves": self.build_waves(),
            "critical_path": self.critical_path(),
        }
