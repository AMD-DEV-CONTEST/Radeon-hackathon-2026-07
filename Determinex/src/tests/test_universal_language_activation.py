from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

from verified_task.adapters import ide_repair_task_spec, swebench_pro_task_spec, swelancer_task_spec
from verified_task.language_profiles import default_validation_commands


def test_java_profile_uses_native_tools() -> None:
    commands = " ".join(default_validation_commands("java")).lower()
    assert "mvn" in commands or "gradle" in commands or "javac" in commands
    assert "pytest" not in commands


def test_cpp_profile_uses_native_tools() -> None:
    commands = " ".join(default_validation_commands("cpp")).lower()
    assert "g++" in commands or "make" in commands or "cmake" in commands
    assert "python" not in commands


def test_ide_repair_adapter_preserves_java_language(tmp_path: Path) -> None:
    spec = ide_repair_task_spec(
        task_id="ide-java-001",
        language="java",
        workspace=tmp_path,
        diagnostic="Fix the failing JUnit test.",
    )
    assert spec.language == "java"
    assert spec.benchmark == "IDE-Repair"
    assert spec.privacy_policy == "cloak"
    assert any(
        "mvn" in cmd or "gradle" in cmd or "javac" in cmd for cmd in spec.validation_commands
    )


def test_swebench_and_swelancer_emit_cloaked_repo_tasks(tmp_path: Path) -> None:
    swe = swebench_pro_task_spec(
        task_id="swe-go-001",
        language="go",
        workspace=tmp_path,
        issue_text="Fix the regression.",
    )
    swelancer = swelancer_task_spec(
        task_id="swelancer-cpp-001",
        language="cpp",
        workspace=tmp_path,
        work_order="Fix the failing acceptance test.",
    )
    assert swe.privacy_policy == "cloak"
    assert swelancer.privacy_policy == "cloak"
    assert swe.validation_commands == default_validation_commands("go")
    assert swelancer.validation_commands == default_validation_commands("cpp")
