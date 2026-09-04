import json
import tomllib
from pathlib import Path


def test_repository_uses_approved_tooling_and_license_policy() -> None:
    project = tomllib.loads(Path("pyproject.toml").read_text())
    package = json.loads(Path("package.json").read_text())

    assert "license" not in project["project"]
    assert package["packageManager"] == "pnpm@11.9.0"
    assert Path(".node-version").read_text().strip().split(".")[0] == "22"
    assert not Path("package-lock.json").exists()
    assert Path("pnpm-lock.yaml").exists()
    assert Path("pnpm-workspace.yaml").exists()
