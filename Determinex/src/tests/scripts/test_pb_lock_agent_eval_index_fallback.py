from argparse import Namespace

import scripts.pb_lock_agent as A


def test_context_uses_eval_index_when_legacy_board_is_missing(tmp_path, monkeypatch, capsys):
    repo = tmp_path
    overrides = repo / "corpus" / "programbench" / "per_tool_overrides"
    tool_dir = overrides / "owner__tool.abc123"
    tool_dir.mkdir(parents=True)
    (tool_dir / "compile.sh").write_text(
        "#!/bin/sh\nrustc reimpl.rs -o executable\n", encoding="utf-8"
    )
    (tool_dir / "reimpl.rs").write_text("fn main() {}\n", encoding="utf-8")

    eval_index = repo / "corpus" / "programbench" / "eval_index.json"
    eval_index.parent.mkdir(parents=True, exist_ok=True)
    eval_index.write_text(
        '[{"slug":"owner__tool","passed":7,"total":11,"failed":4,'
        '"eval_report_path":"T:/missing/owner__tool.abc123.eval.json"}]',
        encoding="utf-8",
    )

    monkeypatch.setattr(A, "BOARD_JSON", repo / "logs" / "programbench_lock_board.json")
    monkeypatch.setattr(A, "EVAL_INDEX_JSON", eval_index)
    monkeypatch.setattr(A, "OVERRIDES", overrides)
    monkeypatch.setattr(A, "LOCKED", repo / "corpus" / "programbench" / "locked")

    A.cmd_context(Namespace(slug="owner__tool.abc123"))

    out = capsys.readouterr().out
    assert "ProgramBench Lock Context: owner__tool.abc123" in out
    assert "Score**: 7/11" in out
    assert "Eval JSON" in out
    assert "not available" in out
