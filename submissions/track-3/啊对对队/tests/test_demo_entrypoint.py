from __future__ import annotations

import os
from pathlib import Path
import subprocess
import tomllib


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "run_demo.sh"


def test_demo_help_is_checkpoint_free_and_self_describing() -> None:
    if os.name == "nt":
        content = SCRIPT.read_text(encoding="utf-8")
        assert "checkpoint-free" in content
        assert "ScriptedExpertPolicy" in content
        assert "not a pure-VLA" in content
        return
    result = subprocess.run(
        ["bash", str(SCRIPT), "--help"],
        cwd=ROOT,
        check=True,
        text=True,
        capture_output=True,
    )
    assert "ScriptedExpertPolicy" in result.stdout
    assert "not a pure-VLA" in result.stdout
    assert "checkpoint-free" in result.stdout


def test_demo_uses_local_scripted_expert_cli_only() -> None:
    content = SCRIPT.read_text(encoding="utf-8")
    assert "scripts/run_expert.py" in content
    assert "--episodes 1" in content
    assert "--start-episode 0" in content
    assert "--record-video" in content
    assert "--fail-on-unsuccessful" in content
    assert "--checkpoint" not in content
    assert "mobile_vla_service" not in content
    assert "openai" not in content.lower()
    assert "responses" not in content.lower()


def test_container_and_package_metadata_support_the_scripted_demo() -> None:
    with (ROOT / "pyproject.toml").open("rb") as handle:
        project = tomllib.load(handle)["project"]
    assert project["requires-python"] == ">=3.12"
    assert "genesis-world==1.2.3" in project["dependencies"]
    assert project["optional-dependencies"]["lerobot"] == ["lerobot==0.6.1"]

    requirements = (ROOT / "requirements.txt").read_text(encoding="utf-8")
    assert "genesis-world==1.2.3" in requirements
    assert "lerobot==0.6.1" not in requirements

    dockerfile = (ROOT / "Dockerfile.rocm").read_text(encoding="utf-8")
    assert "COPY pyproject.toml requirements.txt requirements-lock.txt" in dockerfile
    assert "-c requirements-lock.txt -r requirements.txt" in dockerfile
    assert "-c requirements-lock.txt -e third_party/genesis-world" in dockerfile
    assert 'CMD ["bash", "scripts/run_demo.sh"]' in dockerfile
