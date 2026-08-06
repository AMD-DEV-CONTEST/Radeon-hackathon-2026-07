from __future__ import annotations

import json
from pathlib import Path

from ruamel.yaml import YAML

from agent_factory.assembly.schema import AgentAssemblySpec


class AgentAssemblyLoader:
    def __init__(self) -> None:
        self._yaml = YAML(typ="safe")

    def load_path(self, path: str | Path) -> AgentAssemblySpec:
        source = Path(path)
        if source.name == "agent_package.json":
            raise ValueError("agent_package.json must be loaded through AgentPackageLoader")
        if source.suffix.lower() == ".json":
            data = json.loads(source.read_text(encoding="utf-8"))
        else:
            data = self._yaml.load(source.read_text(encoding="utf-8")) or {}
        return AgentAssemblySpec.model_validate(data)
