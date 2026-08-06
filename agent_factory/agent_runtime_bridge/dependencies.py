from __future__ import annotations

from pathlib import Path

from agent_factory.runtime_contracts.schema import DependenciesContract


def load_dependencies_contract(package_root: Path) -> DependenciesContract:
    """Load package-local environment requirements without installing anything at runtime."""
    path = package_root / "contracts" / "dependencies.json"
    if not path.is_file():
        return DependenciesContract()
    return DependenciesContract.model_validate_json(path.read_text(encoding="utf-8"))
