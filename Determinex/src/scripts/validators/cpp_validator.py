"""C/C++ output validator for corpus sample gating."""

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


def _project_command(path: Path) -> list[str] | None:
    if (path / "CMakeLists.txt").is_file():
        return ["cmake", "--build", "."]
    if (path / "Makefile").is_file() or (path / "makefile").is_file():
        return ["make", "test"]
    return None


def _compiler(language: str) -> tuple[str, str]:
    key = language.lower()
    if key in {"c", "c99", "c11", "c17"}:
        return "gcc", "main.c"
    return "g++", "main.cpp"


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
                return False, "c/cpp project validation timeout"
            except FileNotFoundError as exc:
                return False, f"c/cpp project validator missing tool: {exc}"
            if result.returncode == 0:
                return True, "c/cpp project OK"
            return (
                False,
                f"c/cpp project: {(result.stderr or result.stdout)[:500].replace(chr(10), ' | ')}",
            )

    code = _strip_fences(output)
    if len(code) < 10:
        return False, "output too short"
    if "```" in code:
        return False, "unstripped markdown fences remain"

    language = str(task_meta.get("language") or task_meta.get("lang") or "cpp")
    compiler, filename = _compiler(language)
    try:
        with tempfile.TemporaryDirectory() as tmp:
            td = Path(tmp)
            source = td / filename
            source.write_text(code, encoding="utf-8")
            cmd = [compiler, "-Wall", "-Wextra", "-Werror", str(source.name), "-o", "main.exe"]
            if compiler == "g++":
                cmd.insert(1, "-std=c++20")
            result = subprocess.run(
                cmd, cwd=str(td), capture_output=True, text=True, timeout=_TIMEOUT
            )
            if result.returncode == 0:
                return True, f"{compiler} OK"
            return (
                False,
                f"{compiler}: {(result.stderr or result.stdout)[:500].replace(chr(10), ' | ')}",
            )
    except subprocess.TimeoutExpired:
        return False, f"{compiler} timeout"
    except FileNotFoundError:
        return False, f"{compiler} not on PATH"
    except Exception as exc:
        return False, f"c/cpp validator error: {exc}"
