from __future__ import annotations

from pathlib import Path

from agent_factory.runtime_kernel.errors import RuntimeKernelError
from agent_factory.runtime_kernel.patterns.loader import PatternLoader
from agent_factory.runtime_kernel.patterns.schema import (
    GraphPatternSpec,
    PatternCatalogItemSpec,
    PatternStructureSummary,
)
from agent_factory.runtime_kernel.patterns.validator import PatternValidator


class PatternRegistry:
    def __init__(
        self,
        *,
        builtins_dir: str | Path | None = None,
        loader: PatternLoader | None = None,
        validator: PatternValidator | None = None,
    ) -> None:
        self.loader = loader or PatternLoader()
        self.validator = validator or PatternValidator()
        self._patterns: dict[str, GraphPatternSpec] = {}
        self._catalog: dict[str, PatternCatalogItemSpec] = {}
        self._known_node_impl_ids: set[str] = set()
        if builtins_dir is not None:
            self.load_builtins(builtins_dir)

    def load_builtins(self, builtins_dir: str | Path) -> None:
        root = Path(builtins_dir)
        raw_patterns = [self.loader.load_path(path) for path in sorted(root.glob("*.yaml"))]
        known_ids = {pattern.pattern_id for pattern in raw_patterns}
        self._patterns = {
            pattern.pattern_id: self.validator.validate(pattern, known_patterns=known_ids)
            for pattern in raw_patterns
        }
        self._catalog = {
            item.pattern_id: item
            for item in [
                self.loader.load_catalog_item_path(path) for path in sorted(root.glob("*.yaml"))
            ]
        }

    def get(self, pattern_id: str) -> GraphPatternSpec:
        if pattern_id not in self._patterns:
            raise RuntimeKernelError(f"Unknown pattern: {pattern_id}")
        return self._patterns[pattern_id]

    def register(self, pattern: GraphPatternSpec) -> None:
        known_ids = {*self._patterns, pattern.pattern_id}
        validated = self.validator.validate(
            pattern,
            known_patterns=known_ids,
            known_node_impls=set(self._known_node_impl_ids),
        )
        self._patterns[pattern.pattern_id] = validated
        self._catalog[pattern.pattern_id] = PatternCatalogItemSpec.model_validate(
            validated.model_dump(
                include={
                    "pattern_id",
                    "kind",
                    "embeddable",
                    "version",
                    "name",
                    "description",
                    "metadata",
                }
            )
        )

    def list_pattern_ids(self) -> list[str]:
        return sorted(self._patterns)

    def register_node_impl_ids(self, impl_ids: list[str] | tuple[str, ...] | set[str]) -> None:
        self._known_node_impl_ids.update(str(impl_id) for impl_id in impl_ids)

    def list_pattern_catalog(self, *, include_embeddable: bool = False) -> list[PatternCatalogItemSpec]:
        items = self._catalog.values()
        if not include_embeddable:
            items = [item for item in items if not item.embeddable]
        return sorted(items, key=lambda item: item.pattern_id)

    def get_structure_summary(self, pattern_id: str) -> PatternStructureSummary:
        pattern = self.get(pattern_id)
        return PatternStructureSummary(
            pattern_id=pattern.pattern_id,
            kind=pattern.kind,
            name=pattern.name,
            description=pattern.description,
            entry_node=pattern.entry_node,
            nodes=[
                {
                    "node_id": node.id,
                    "node_type": node.type,
                    "impl": node.impl,
                }
                for node in pattern.nodes
            ],
            routes=[
                {
                    "from_node": edge.from_,
                    "to_node": edge.to,
                    "condition": edge.when,
                }
                for edge in pattern.edges
            ],
            slots=pattern.slots,
            interrupt_points=pattern.interrupt_points,
            termination={
                "success_nodes": pattern.termination.success_nodes,
                "failure_nodes": pattern.termination.failure_nodes,
            },
        )
