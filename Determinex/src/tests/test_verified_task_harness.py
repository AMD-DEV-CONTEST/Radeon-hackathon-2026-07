from __future__ import annotations

import json
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO / "scripts"))

from verified_task import CorpusWriter, RetryLoop, TaskSpec, WorkspaceManager  # noqa: E402
from verified_task.adapters import (
    aider_polyglot_task_spec,
    bigcodebench_task_spec,
    debugbench_task_spec,
    security_task_spec,
    sql_task_spec,
)  # noqa: E402
from verified_task.language_profiles import (  # noqa: E402
    default_validation_commands,
    get_language_profile,
)


def test_language_profiles_cover_core_stack():
    for language in [
        "python",
        "bash",
        "go",
        "rust",
        "typescript",
        "javascript",
        "java",
        "c",
        "cpp",
        "sql",
        "ruby",
        "php",
    ]:
        profile = get_language_profile(language)
        assert profile.language
        assert profile.file_globs
        assert default_validation_commands(language)


def test_task_spec_round_trip():
    spec = TaskSpec(
        id="demo",
        benchmark="Terminal-Bench",
        language="python",
        instruction="run tests",
        validation_commands=["python -c \"print('ok')\""],
    )
    assert TaskSpec.from_dict(spec.to_dict()).to_dict() == spec.to_dict()


def test_benchmark_adapters_emit_task_specs(tmp_path):
    ws = tmp_path / "workspace"
    ws.mkdir()
    specs = [
        aider_polyglot_task_spec(
            task_id="a", language="go", workspace=ws, problem_statement="solve"
        ),
        bigcodebench_task_spec(task_id="b", workspace=ws, prompt="use pandas"),
        debugbench_task_spec(task_id="d", language="java", workspace=ws, bug_report="fix bug"),
        security_task_spec(task_id="s", language="python", workspace=ws, instruction="remove vuln"),
        sql_task_spec(task_id="q", benchmark="BIRD-Critic", workspace=ws, question="query"),
    ]
    for spec in specs:
        assert spec.validation_commands
        assert spec.repo_or_workspace == str(ws)


def test_retry_loop_writes_verdict_and_corpus(tmp_path, monkeypatch):
    root = tmp_path / "verified"
    monkeypatch.setenv("DETERMINEX_VERIFIED_TASK_ROOT", str(root))
    source = tmp_path / "source"
    source.mkdir()
    (source / "x.txt").write_text("ok", encoding="utf-8")
    spec = TaskSpec(
        id="demo",
        benchmark="Terminal-Bench",
        language="python",
        repo_or_workspace=str(source),
        instruction="run a passing command",
        # Note: no outer quotes around sys.executable. The previous form
        # `"<exe>" -c "print('ok')"` relied on shell=True's Windows-specific
        # quote-preservation quirk; after HARDENED_VERIFIED_TASK_AND_CODECLASH_LOCK_001
        # commands route through cmd.exe /c via argv-list, where embedded
        # double-quotes are escaped differently. Unquoted form works on
        # both POSIX /bin/sh -c and Windows cmd.exe /c.
        validation_commands=[f"{sys.executable} -c \"print('ok')\""],
    )
    lease = WorkspaceManager(root).create(spec)
    corpus = CorpusWriter(lease.corpus / "trace.jsonl")
    result = RetryLoop(corpus_writer=corpus).run(spec, lease)
    assert result.passed
    payload = json.loads(result.final_verdict_path.read_text(encoding="utf-8"))
    assert payload["passed"] is True
    assert (lease.corpus / "trace.jsonl").is_file()
