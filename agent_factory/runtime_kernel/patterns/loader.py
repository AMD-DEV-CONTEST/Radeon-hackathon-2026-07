from __future__ import annotations

from pathlib import Path

from ruamel.yaml import YAML

from agent_factory.runtime_kernel.patterns.schema import GraphPatternSpec, PatternCatalogItemSpec


class PatternLoader:
    def __init__(self) -> None:
        self._yaml = YAML(typ="safe")

    def load_path(self, path: str | Path) -> GraphPatternSpec:
        data = self._yaml.load(Path(path).read_text(encoding="utf-8")) or {}
        return GraphPatternSpec.model_validate(data)

    def load_catalog_item_path(self, path: str | Path) -> PatternCatalogItemSpec:
        data = self._yaml.load(Path(path).read_text(encoding="utf-8")) or {}
        return PatternCatalogItemSpec.model_validate(
            {
                "pattern_id": data.get("pattern_id"),
                "kind": data.get("kind"),
                "embeddable": data.get("embeddable"),
                "version": data.get("version"),
                "name": data.get("name"),
                "description": data.get("description"),
                "metadata": data.get("metadata") or {},
            }
        )
