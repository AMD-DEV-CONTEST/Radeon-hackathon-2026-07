"""
validators — Determinex Output Validation Gate
============================================
DATA ENGINE ONLY. These validators are used exclusively by deepseek_data_engine.py
to gate training samples before they are written to the JSONL corpus. They are NOT
used by the main inference pipeline (determinex_hive.py, executor.py,
determinex_swebench_agent.py), which uses hive/compiler.py (validate_project) as the
Compiler Oracle instead.

Each module exposes a single function:

    validate(output: str, task_meta: dict) -> tuple[bool, str]

Returns (passed: bool, reason: str).
A False result means the sample is discarded and not written to JSONL.

Validator modules:
    rust_validator      — Compiles Rust code via rustc, checks exit code and stderr
    python_validator    — ast.parse() + optional sandboxed exec(), checks for exceptions
    json_validator      — jsonschema validation against task-defined schema
    regex_validator     — Configurable pattern matching (e.g., function signature presence)
    llm_critic_validator — Sends output to a secondary model for pass/fail critique
"""

from .bash_validator import validate as bash_validate
from .cpp_validator import validate as cpp_validate
from .dockerfile_validator import validate as dockerfile_validate
from .go_validator import validate as go_validate
from .java_validator import validate as java_validate
from .json_validator import validate as json_validate
from .llm_critic_validator import validate as llm_critic_validate
from .powershell_validator import validate as powershell_validate
from .python_validator import validate as python_validate
from .regex_validator import validate as regex_validate
from .rust_validator import validate as rust_validate
from .sql_validator import validate as sql_validate
from .xdist_validator import validate as xdist_validate
from .yaml_validator import validate as yaml_validate

VALIDATOR_MAP = {
    "rustc": rust_validate,
    "python_ast": python_validate,
    "json_schema": json_validate,
    "regex": regex_validate,
    "llm_critic": llm_critic_validate,
    "go": go_validate,
    # Sprint 3 — Universal Oracle Pack additions (2026-05-15)
    "bash": bash_validate,
    "powershell": powershell_validate,
    "dockerfile": dockerfile_validate,
    "yaml": yaml_validate,
    "xdist": xdist_validate,
    "sql": sql_validate,
    "java": java_validate,
    "c": cpp_validate,
    "cpp": cpp_validate,
    "c++": cpp_validate,
}

__all__ = ["VALIDATOR_MAP"]
