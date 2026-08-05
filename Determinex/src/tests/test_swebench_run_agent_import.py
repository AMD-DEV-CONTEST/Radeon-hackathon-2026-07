"""Regression guard for a real, showstopping bug found live 2026-07-19: a systematic
sweep for this session's recurring CITADEL_/DETERMINEX_ rename-split-brain bug class
turned up a much worse instance in scripts/determinex_swebench_run.py --
run_agent_on_instance() (the function that actually runs the agent on every single
SWE-bench instance) did:

    from citadel_swebench_agent import CitadelSWEAgent
    agent = CitadelSWEAgent()

but the real module on disk is scripts/determinex_swebench_agent.py, exporting
DeterminexSWEAgent -- no module named citadel_swebench_agent has ever existed. That
import sits BEFORE the function's own try/except (which only wraps agent.solve()), so
every real SWE-bench run through this entry point would have crashed with
ModuleNotFoundError the first time it tried to process an instance. Existing test
coverage for this file (test_swebench_replay_prediction_source.py) only exercised the
small prediction-source helpers, never this path -- which is exactly how a hard crash
like this can go unnoticed.

Also fixed in the same sweep: the CLI's --builder-model/--observer-model defaults
pointed at "citadel-engineer-v11-dsl"/"citadel-observer-v6-dsl", but the actually
registered Ollama tags (per CLAUDE.md's own model table) are
"determinex-engineer-v11-dsl"/"determinex-observer-v6-dsl".
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_SCRIPT = _ROOT / "scripts" / "determinex_swebench_run.py"
sys.path.insert(0, str(_ROOT / "scripts"))


def test_run_agent_on_instance_imports_the_real_agent_module():
    """The exact regression: this import must resolve to a module/class that
    genuinely exists, not a phantom pre-rename name."""
    import determinex_swebench_agent  # the real module -- must exist and import clean

    assert hasattr(determinex_swebench_agent, "DeterminexSWEAgent")

    source = _SCRIPT.read_text(encoding="utf-8")
    tree = ast.parse(source)
    found_import = False
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module == "determinex_swebench_agent":
            names = {alias.name for alias in node.names}
            assert "DeterminexSWEAgent" in names
            found_import = True
    assert found_import, "run_agent_on_instance's agent import not found"


def test_no_phantom_citadel_swebench_agent_reference():
    source = _SCRIPT.read_text(encoding="utf-8")
    assert "citadel_swebench_agent" not in source
    assert "CitadelSWEAgent" not in source


def test_cli_model_defaults_match_actually_registered_ollama_tags():
    source = _SCRIPT.read_text(encoding="utf-8")
    assert '"determinex-engineer-v11-dsl"' in source
    assert '"determinex-observer-v6-dsl"' in source
    assert '"citadel-engineer-v11-dsl"' not in source
    assert '"citadel-observer-v6-dsl"' not in source
