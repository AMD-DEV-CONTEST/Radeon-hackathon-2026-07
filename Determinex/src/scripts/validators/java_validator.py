"""Java output validator for corpus sample gating.

The validator accepts either a single Java source snippet or a small project
layout supplied through task metadata. It is intentionally conservative: if a
Maven or Gradle project exists, use that project validator; otherwise compile a
single class with javac.
"""

from __future__ import annotations

import re
import subprocess
import tempfile
from pathlib import Path

_TIMEOUT = 60


def _strip_fences(code: str) -> str:
    code = code.strip()
    code = re.sub(r"^```\w*\s*\n", "", code, flags=re.MULTILINE)
    code = re.sub(r"\n```\s*$", "", code, flags=re.MULTILINE)
    return code.strip()


def _class_name(code: str) -> str:
    match = re.search(r"\bpublic\s+(?:final\s+)?class\s+([A-Za-z_][A-Za-z0-9_]*)", code)
    if match:
        return match.group(1)
    match = re.search(r"\bclass\s+([A-Za-z_][A-Za-z0-9_]*)", code)
    return match.group(1) if match else "Main"


def _project_command(path: Path) -> list[str] | None:
    if (path / "mvnw.cmd").is_file():
        return ["cmd", "/c", "mvnw.cmd", "test", "-q", "--no-transfer-progress"]
    if (path / "mvnw").is_file():
        return ["sh", "./mvnw", "test", "-q", "--no-transfer-progress"]
    if (path / "pom.xml").is_file():
        return ["mvn", "test", "-q", "--no-transfer-progress"]
    if (path / "gradlew.bat").is_file():
        return ["cmd", "/c", "gradlew.bat", "test", "--quiet"]
    if (path / "gradlew").is_file():
        return ["sh", "./gradlew", "test", "--quiet"]
    if (path / "build.gradle").is_file() or (path / "build.gradle.kts").is_file():
        return ["gradle", "test", "--quiet"]
    return None


def validate(output: str, task_meta: dict) -> tuple[bool, str]:
    workspace = task_meta.get("workspace") or task_meta.get("repo_or_workspace")
    if workspace:
        path = Path(str(workspace))
        cmd = _project_command(path)
        if cmd:
            try:
                result = subprocess.run(
                    cmd, cwd=str(path), capture_output=True, text=True, timeout=_TIMEOUT
                )
            except subprocess.TimeoutExpired:
                return False, "java project validation timeout"
            except FileNotFoundError as exc:
                return False, f"java project validator missing tool: {exc}"
            text = (result.stderr or result.stdout)[:500].replace("\n", " | ")
            return (
                result.returncode == 0,
                "java project OK" if result.returncode == 0 else f"java project: {text}",
            )

    code = _strip_fences(output)
    if len(code) < 10:
        return False, "output too short"
    if "```" in code:
        return False, "unstripped markdown fences remain"

    try:
        with tempfile.TemporaryDirectory() as tmp:
            td = Path(tmp)
            name = _class_name(code)
            source = td / f"{name}.java"
            source.write_text(code, encoding="utf-8")
            result = subprocess.run(
                ["javac", str(source.name)],
                cwd=str(td),
                capture_output=True,
                text=True,
                timeout=_TIMEOUT,
            )
            if result.returncode == 0:
                return True, "javac OK"
            return False, f"javac: {(result.stderr or result.stdout)[:500].replace(chr(10), ' | ')}"
    except subprocess.TimeoutExpired:
        return False, "javac timeout"
    except FileNotFoundError:
        return False, "javac not on PATH"
    except Exception as exc:
        return False, f"java validator error: {exc}"
