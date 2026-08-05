"""tests/test_determinex_agent_chat.py

Multi-agent chat room session/transcript logic. Covers everything Python owns
for the "Agent Chat Room" IDE panel: session persistence, @mention parsing,
context-prompt building, and record_turn()'s oracle-verification wiring.
Subprocess spawn + live streaming lives in Rust (agent_chat.rs) and calls
back into determinex_agents.py's `record-turn` CLI subcommand, which
delegates to record_turn() here -- not covered by these tests (no subprocess
involved on this side).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import patch

_ROOT = Path(__file__).resolve().parents[1]
for _p in (_ROOT, _ROOT / "scripts"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import determinex_agent_chat as chat  # noqa: E402


def _rewire(monkeypatch, tmp_path: Path) -> None:
    sessions_dir = tmp_path / "agent_chat_sessions"
    monkeypatch.setattr(chat, "SESSIONS_DIR", sessions_dir)
    monkeypatch.setattr(chat, "INDEX_PATH", sessions_dir / "_index.json")
    # Oracle feedback loop's durable store -- must never touch the real
    # corpus/chat_sessions/oracle_outcomes.jsonl during a test run.
    monkeypatch.setattr(
        chat,
        "_ORACLE_OUTCOMES_PATH",
        tmp_path / "corpus" / "chat_sessions" / "oracle_outcomes.jsonl",
    )
    # _CLOAK_CONTEXTS is a module-level, session_id-keyed in-memory cache --
    # clear it so one test's cloak state can't leak into another's.
    chat._CLOAK_CONTEXTS.clear()


# ---------------------------------------------------------------------------
# @mention parsing
# ---------------------------------------------------------------------------


def test_parse_mentions_matches_agent_name_and_alias():
    known = ["claude-code", "codex", "local-ollama"]
    # "claude" is a registered alias of "claude-code" in determinex_agents.py
    result = chat.parse_mentions("hey @claude and @codex, take a look", known)
    assert result == ["claude-code", "codex"]


def test_parse_mentions_case_insensitive_and_no_match_returns_empty():
    known = ["claude-code", "codex"]
    assert chat.parse_mentions("no mentions here at all", known) == []
    assert chat.parse_mentions("@CLAUDE-CODE please help", known) == ["claude-code"]


def test_parse_mentions_ignores_unknown_tokens():
    known = ["claude-code"]
    result = chat.parse_mentions("@claude-code and also @some-random-thing", known)
    assert result == ["claude-code"]


def test_parse_mentions_deduplicates():
    known = ["claude-code"]
    result = chat.parse_mentions("@claude-code ping @claude-code again", known)
    assert result == ["claude-code"]


# ---------------------------------------------------------------------------
# Session create / index
# ---------------------------------------------------------------------------


def test_create_session_writes_index_entry_and_list_sessions_reflects_it(tmp_path, monkeypatch):
    _rewire(monkeypatch, tmp_path)
    result = chat.create_session("sess-a", "C:/ws", ["claude-code", "codex"], "broadcast")
    assert result["session_id"] == "sess-a"
    assert result["turn_count"] == 0

    sessions = chat.list_sessions()
    assert len(sessions) == 1
    assert sessions[0]["session_id"] == "sess-a"
    assert sessions[0]["participants"] == ["claude-code", "codex"]


def test_create_session_rejects_invalid_turn_mode(tmp_path, monkeypatch):
    _rewire(monkeypatch, tmp_path)
    try:
        chat.create_session("sess-b", "C:/ws", ["codex"], "chaos")
        assert False, "expected ValueError"
    except ValueError:
        pass


def test_get_session_returns_none_for_unknown_id(tmp_path, monkeypatch):
    _rewire(monkeypatch, tmp_path)
    assert chat.get_session("does-not-exist") is None


# ---------------------------------------------------------------------------
# append_turn / read_transcript round-trip
# ---------------------------------------------------------------------------


def _make_turn(session_id: str, seq: int, speaker: str = "codex") -> chat.ChatTurn:
    return chat.ChatTurn(
        turn_id=f"{session_id}-{seq}",
        session_id=session_id,
        seq=seq,
        speaker=speaker,
        speaker_kind="agent",
        addressed_to=[],
        mode="broadcast",
        task_prompt="do the thing",
        raw_output="did the thing",
        returncode=0,
        verified=True,
        oracle="pytest",
        n_failures=0,
        note="oracle PASSES after agent edits",
        started_at="2026-07-20T00:00:00+00:00",
        finished_at="2026-07-20T00:00:05+00:00",
    )


def test_append_turn_then_read_transcript_roundtrips(tmp_path, monkeypatch):
    _rewire(monkeypatch, tmp_path)
    turn = _make_turn("sess-c", 0)
    chat.append_turn(turn)

    transcript = chat.read_transcript("sess-c")
    assert len(transcript) == 1
    assert transcript[0]["speaker"] == "codex"
    assert transcript[0]["verified"] is True

    # one JSON object per line, matching the project's established JSONL convention
    lines = chat._session_path("sess-c").read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    json.loads(lines[0])  # must parse standalone


def test_read_transcript_missing_session_returns_empty_list(tmp_path, monkeypatch):
    _rewire(monkeypatch, tmp_path)
    assert chat.read_transcript("never-created") == []


def test_read_transcript_skips_malformed_lines(tmp_path, monkeypatch):
    _rewire(monkeypatch, tmp_path)
    chat.append_turn(_make_turn("sess-d", 0))
    path = chat._session_path("sess-d")
    with open(path, "a", encoding="utf-8") as f:
        f.write("not valid json\n")
    chat.append_turn(_make_turn("sess-d", 1))

    transcript = chat.read_transcript("sess-d")
    assert len(transcript) == 2  # malformed line skipped, both real turns present


# ---------------------------------------------------------------------------
# build_context_prompt
# ---------------------------------------------------------------------------


def test_build_context_prompt_includes_recent_turns_and_workspace(tmp_path, monkeypatch):
    _rewire(monkeypatch, tmp_path)
    chat.create_session("sess-e", "C:/my/workspace", ["claude-code", "codex"], "mention")
    chat.append_turn(_make_turn("sess-e", 0, speaker="user"))
    chat.append_turn(_make_turn("sess-e", 1, speaker="codex"))

    prompt = chat.build_context_prompt("sess-e", "claude-code")
    assert "C:/my/workspace" in prompt
    assert "claude-code" in prompt
    assert "[user]:" in prompt
    assert "[codex]:" in prompt
    assert "--- conversation so far ---" in prompt


def test_build_context_prompt_caps_at_max_turns(tmp_path, monkeypatch):
    _rewire(monkeypatch, tmp_path)
    chat.create_session("sess-f", "C:/ws", ["codex"], "broadcast")
    for i in range(20):
        chat.append_turn(_make_turn("sess-f", i, speaker=f"speaker-{i}"))

    prompt = chat.build_context_prompt("sess-f", "codex", max_turns=3)
    # only the last 3 speakers should appear (speaker-17, 18, 19)
    assert "speaker-19" in prompt
    assert "speaker-18" in prompt
    assert "speaker-17" in prompt
    assert "speaker-0" not in prompt
    assert "speaker-10" not in prompt


# ---------------------------------------------------------------------------
# Shared mission plan -- the one doc every participant reads, independent of
# transcript windowing. "there should be a universal place they all run to
# for their marching orders or we will have chaos and duplication."
# ---------------------------------------------------------------------------


def test_read_plan_returns_default_template_for_a_never_created_session(tmp_path, monkeypatch):
    """read_plan()'s own fallback (no plan file on disk at all) is distinct
    from create_session()'s behavior, which now proactively seeds a real
    plan from stewardship content -- see
    test_create_session_seeds_plan_from_stewardship below."""
    _rewire(monkeypatch, tmp_path)
    plan = chat.read_plan("session-that-was-never-created")
    assert "No plan set yet" in plan
    assert "Positions" in plan


def test_create_session_seeds_plan_from_stewardship(tmp_path, monkeypatch):
    """create_session() proactively populates the plan with a REFERENCE to
    real project context (or an auto-generated stewardship doc's path)
    instead of leaving new sessions on the generic 'No plan set yet'
    placeholder. A reference, not the doc's full content -- embedding full
    file bodies in every chat turn's prompt overwhelmed participants'
    context (found live 2026-07-22, see resolve_stewardship_reference)."""
    _rewire(monkeypatch, tmp_path)
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "pyproject.toml").write_text("[project]\nname='x'\n", encoding="utf-8")

    chat.create_session("sess-plan-a", str(ws), ["codex"], "broadcast")
    plan = chat.read_plan("sess-plan-a")
    assert "No plan set yet" not in plan
    assert "PROJECT.md" in plan  # points at the generated doc's path, not its body
    assert "read them directly" in plan
    assert "Positions" in plan


def test_write_plan_then_read_plan_roundtrips(tmp_path, monkeypatch):
    _rewire(monkeypatch, tmp_path)
    chat.create_session("sess-plan-b", "C:/ws", ["codex"], "broadcast")
    chat.write_plan("sess-plan-b", "# Build a CLI\n\nCodex owns parsing.")
    assert chat.read_plan("sess-plan-b") == "# Build a CLI\n\nCodex owns parsing."


def test_write_plan_updates_index_last_active(tmp_path, monkeypatch):
    _rewire(monkeypatch, tmp_path)
    chat.create_session("sess-plan-c", "C:/ws", ["codex"], "broadcast")
    before = chat._read_index()["sess-plan-c"]["last_active"]
    chat.write_plan("sess-plan-c", "updated plan")
    after = chat._read_index()["sess-plan-c"]["last_active"]
    assert after >= before


def test_build_context_prompt_includes_plan_verbatim_not_windowed(tmp_path, monkeypatch):
    """The plan is NOT subject to max_turns windowing like the transcript --
    it must appear even with max_turns=0."""
    _rewire(monkeypatch, tmp_path)
    chat.create_session("sess-plan-d", "C:/ws", ["codex"], "broadcast")
    chat.write_plan("sess-plan-d", "ALWAYS-VISIBLE-PLAN-MARKER")

    prompt = chat.build_context_prompt("sess-plan-d", "codex", max_turns=0)
    assert "ALWAYS-VISIBLE-PLAN-MARKER" in prompt
    assert "shared mission plan" in prompt


def test_build_context_prompt_truncates_long_output(tmp_path, monkeypatch):
    _rewire(monkeypatch, tmp_path)
    chat.create_session("sess-g", "C:/ws", ["codex"], "broadcast")
    long_turn = _make_turn("sess-g", 0)
    long_turn.raw_output = "x" * 5000
    chat.append_turn(long_turn)

    prompt = chat.build_context_prompt("sess-g", "codex")
    assert "…[truncated]" in prompt
    assert "x" * 5000 not in prompt


# ---------------------------------------------------------------------------
# record_turn -- oracle verification wiring
# ---------------------------------------------------------------------------


def test_record_turn_user_message_is_not_oracle_checked(tmp_path, monkeypatch):
    _rewire(monkeypatch, tmp_path)
    chat.create_session("sess-h", "C:/ws", ["codex"], "broadcast")

    turn = chat.record_turn(
        "sess-h",
        "user",
        tmp_path,
        "please fix it",
        0,
        "sess-h-0",
        "please fix it",
        speaker_kind="user",
    )
    assert turn.verified is True
    assert turn.note == "user message"
    assert turn.oracle == ""


def test_record_turn_agent_message_calls_repair_workspace_and_records_verdict(
    tmp_path, monkeypatch
):
    _rewire(monkeypatch, tmp_path)
    chat.create_session("sess-i", "C:/ws", ["codex"], "broadcast")

    class FakeDiag:
        healthy = True
        oracle = "pytest"
        n_failures = 0

    with patch("determinex_repair.repair_workspace", return_value=FakeDiag()):
        turn = chat.record_turn(
            "sess-i",
            "codex",
            tmp_path,
            "raw agent output",
            0,
            "sess-i-0",
            "do the thing",
            speaker_kind="agent",
        )

    assert turn.verified is True
    assert turn.oracle == "pytest"
    assert "PASSES" in turn.note

    index = chat._read_index()
    assert index["sess-i"]["turn_count"] == 1


def test_record_turn_agent_failure_case_marks_unverified(tmp_path, monkeypatch):
    _rewire(monkeypatch, tmp_path)
    chat.create_session("sess-j", "C:/ws", ["codex"], "broadcast")

    class FakeDiag:
        healthy = False
        oracle = "pytest"
        n_failures = 3

    with patch("determinex_repair.repair_workspace", return_value=FakeDiag()):
        turn = chat.record_turn(
            "sess-j",
            "codex",
            tmp_path,
            "broke something",
            1,
            "sess-j-0",
            "do the thing",
            speaker_kind="agent",
        )

    assert turn.verified is False
    assert turn.n_failures == 3
    assert "still failing" in turn.note


def test_record_turn_caps_raw_output(tmp_path, monkeypatch):
    _rewire(monkeypatch, tmp_path)
    chat.create_session("sess-k", "C:/ws", ["codex"], "broadcast")
    huge = "y" * 50_000

    class FakeDiag:
        healthy = True
        oracle = "pytest"
        n_failures = 0

    with patch("determinex_repair.repair_workspace", return_value=FakeDiag()):
        turn = chat.record_turn(
            "sess-k", "codex", tmp_path, huge, 0, "sess-k-0", "do the thing", speaker_kind="agent"
        )

    assert len(turn.raw_output) <= chat._RAW_OUTPUT_CAP + len("\n…[truncated]")
    assert turn.raw_output.endswith("…[truncated]")


# ---------------------------------------------------------------------------
# Project Cloak room -- "cloak when enabled will put the api llms into a
# seperate room to work from away from the sensitive data... i think we have
# to have that to truly claim cloak ability." Real determinex_cloak calls,
# no mocking of the obfuscation itself (same convention as
# tests/test_cloak_smoke.py) -- only the network-free, fast, deterministic
# parts are exercised here.
# ---------------------------------------------------------------------------

_SENSITIVE_SOURCE = (
    "def calculate_super_secret_algorithm(x, y):\n"
    "    internal_proprietary_constant = 42\n"
    "    return x + y + internal_proprietary_constant\n"
)


def _make_sensitive_workspace(tmp_path: Path) -> Path:
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "secret_module.py").write_text(_SENSITIVE_SOURCE, encoding="utf-8")
    return ws


def test_is_cloud_participant_classifies_known_local_names_as_not_cloud():
    assert chat.is_cloud_participant("codex") is True
    assert chat.is_cloud_participant("claude-code") is True
    assert chat.is_cloud_participant("gemini-cli") is True
    assert chat.is_cloud_participant("local-ollama") is False
    assert chat.is_cloud_participant("aider-local") is False
    assert chat.is_cloud_participant("ollama") is False


def test_is_cloud_participant_defaults_unknown_agents_to_cloud():
    """Conservative default: a future/unrecognized agent name is treated as
    untrusted (cloud) rather than silently exempted from cloaking."""
    assert chat.is_cloud_participant("some-new-agent-nobody-registered-yet") is True


def test_cloak_enabled_reads_env_var(monkeypatch):
    monkeypatch.delenv("DETERMINEX_CLOAK", raising=False)
    assert chat.cloak_enabled() is False
    monkeypatch.setenv("DETERMINEX_CLOAK", "1")
    assert chat.cloak_enabled() is True
    monkeypatch.setenv("DETERMINEX_CLOAK", "")
    assert chat.cloak_enabled() is False


def test_get_cloak_context_builds_real_symbol_map_and_writes_disk_cache(tmp_path, monkeypatch):
    _rewire(monkeypatch, tmp_path)
    ws = _make_sensitive_workspace(tmp_path)

    ctx = chat.get_cloak_context("cloak-sess-a", ws)
    assert ctx is not None
    assert "calculate_super_secret_algorithm" in ctx.symbol_map.forward
    assert "internal_proprietary_constant" in ctx.symbol_map.forward

    cache_path = chat.SESSIONS_DIR / "cloak-sess-a.cloak_map.json"
    assert cache_path.exists()


def test_get_cloak_context_reloads_from_disk_cache_across_process_boundary(tmp_path, monkeypatch):
    """The real scenario: Rust spawns a FRESH python process per subcommand,
    so a second call must reconstruct the context from the on-disk symbol
    map instead of re-scanning the repo -- simulated here by clearing the
    in-memory cache (what a new process would start with) and asserting
    build_cloak_context is NOT called again."""
    _rewire(monkeypatch, tmp_path)
    ws = _make_sensitive_workspace(tmp_path)

    ctx1 = chat.get_cloak_context("cloak-sess-b", ws)
    assert ctx1 is not None
    chat._CLOAK_CONTEXTS.clear()  # simulate a fresh process

    with patch("determinex_cloak.build_cloak_context") as mock_build:
        ctx2 = chat.get_cloak_context("cloak-sess-b", ws)
        mock_build.assert_not_called()

    assert ctx2 is not None
    assert ctx2.symbol_map.forward == ctx1.symbol_map.forward


def test_get_cloak_context_fails_closed_and_caches_the_failure(tmp_path, monkeypatch):
    _rewire(monkeypatch, tmp_path)
    ws = _make_sensitive_workspace(tmp_path)

    with patch(
        "determinex_cloak.build_cloak_context", side_effect=RuntimeError("boom")
    ) as mock_build:
        ctx1 = chat.get_cloak_context("cloak-sess-c", ws)
        ctx2 = chat.get_cloak_context("cloak-sess-c", ws)  # must not retry in the same process
    assert ctx1 is None
    assert ctx2 is None
    assert mock_build.call_count == 1


def test_prepare_cloaked_workspace_obfuscates_real_files(tmp_path, monkeypatch):
    _rewire(monkeypatch, tmp_path)
    ws = _make_sensitive_workspace(tmp_path)

    shadow = chat.prepare_cloaked_workspace("cloak-sess-d", ws)
    assert shadow is not None
    obfuscated = (shadow / "secret_module.py").read_text(encoding="utf-8")
    assert "calculate_super_secret_algorithm" not in obfuscated
    assert "internal_proprietary_constant" not in obfuscated
    assert "x_" in obfuscated


def test_prepare_cloaked_workspace_reuses_existing_shadow_dir(tmp_path, monkeypatch):
    _rewire(monkeypatch, tmp_path)
    ws = _make_sensitive_workspace(tmp_path)

    shadow1 = chat.prepare_cloaked_workspace("cloak-sess-e", ws)
    assert shadow1 is not None
    (shadow1 / "secret_module.py").unlink()  # remove a file from the shadow copy

    shadow2 = chat.prepare_cloaked_workspace("cloak-sess-e", ws)
    assert shadow2 is not None
    assert shadow2 == shadow1
    # second call must NOT have rebuilt the shadow dir -- the deleted file stays deleted
    assert not (shadow2 / "secret_module.py").exists()


def test_prepare_cloaked_workspace_returns_none_when_cloak_unavailable(tmp_path, monkeypatch):
    _rewire(monkeypatch, tmp_path)
    ws = _make_sensitive_workspace(tmp_path)
    with patch("determinex_cloak.build_cloak_context", side_effect=RuntimeError("boom")):
        shadow = chat.prepare_cloaked_workspace("cloak-sess-f", ws)
    assert shadow is None


def test_sync_cloaked_edits_restores_real_identifiers_and_preserves_agent_edit(
    tmp_path, monkeypatch
):
    _rewire(monkeypatch, tmp_path)
    ws = _make_sensitive_workspace(tmp_path)

    shadow = chat.prepare_cloaked_workspace("cloak-sess-g", ws)
    assert shadow is not None
    obfuscated = (shadow / "secret_module.py").read_text(encoding="utf-8")

    # Simulate a cloud agent editing the obfuscated file (adds a real edit,
    # keeps referring to the x_NNNN tokens it was given -- exactly what a
    # real CLI agent operating in the shadow room would do).
    edited = obfuscated.rstrip() + "\n    # agent-added comment\n"
    (shadow / "secret_module.py").write_text(edited, encoding="utf-8")

    synced = chat.sync_cloaked_edits_to_real_workspace("cloak-sess-g", ws)
    assert "secret_module.py" in synced

    real_content = (ws / "secret_module.py").read_text(encoding="utf-8")
    assert "calculate_super_secret_algorithm" in real_content
    assert "internal_proprietary_constant" in real_content
    assert "# agent-added comment" in real_content


def test_sync_cloaked_edits_across_process_boundary(tmp_path, monkeypatch):
    """Same cross-process concern as get_cloak_context's dedicated test, but
    exercised through the actual sync entrypoint Rust calls."""
    _rewire(monkeypatch, tmp_path)
    ws = _make_sensitive_workspace(tmp_path)
    shadow = chat.prepare_cloaked_workspace("cloak-sess-h", ws)
    assert shadow is not None

    chat._CLOAK_CONTEXTS.clear()  # simulate cloak-sync running in a fresh process
    synced = chat.sync_cloaked_edits_to_real_workspace("cloak-sess-h", ws)
    # No edits were made to the shadow copy, so content is identical and
    # nothing needs to be (re)written -- but this must not crash or return
    # None, proving the disk-cache reload path was taken successfully.
    assert synced == []


def test_sync_cloaked_edits_no_shadow_returns_empty_list(tmp_path, monkeypatch):
    _rewire(monkeypatch, tmp_path)
    ws = _make_sensitive_workspace(tmp_path)
    assert chat.sync_cloaked_edits_to_real_workspace("never-prepared", ws) == []


def test_restore_text_deobfuscates_when_context_available(tmp_path, monkeypatch):
    _rewire(monkeypatch, tmp_path)
    ws = _make_sensitive_workspace(tmp_path)
    ctx = chat.get_cloak_context("cloak-sess-i", ws)
    assert ctx is not None
    obfuscated_msg = ctx.obfuscate_text("please look at calculate_super_secret_algorithm")

    restored = chat.restore_text("cloak-sess-i", obfuscated_msg, ws)
    assert "calculate_super_secret_algorithm" in restored


def test_restore_text_returns_unchanged_when_never_cloaked(tmp_path, monkeypatch):
    _rewire(monkeypatch, tmp_path)
    text = "plain uncloaked text with x_0000 in it"
    assert chat.restore_text("never-cloaked-session", text) == text


def test_build_context_prompt_refuses_cloud_agent_when_workspace_missing(tmp_path, monkeypatch):
    _rewire(monkeypatch, tmp_path)
    monkeypatch.setenv("DETERMINEX_CLOAK", "1")
    chat.create_session("cloak-sess-j", "", ["codex"], "broadcast")

    prompt = chat.build_context_prompt("cloak-sess-j", "codex")
    assert "[CLOAK ERROR]" in prompt


def test_build_context_prompt_refuses_cloud_agent_when_context_unbuildable(tmp_path, monkeypatch):
    _rewire(monkeypatch, tmp_path)
    monkeypatch.setenv("DETERMINEX_CLOAK", "1")
    ws = _make_sensitive_workspace(tmp_path)
    chat.create_session("cloak-sess-k", str(ws), ["codex"], "broadcast")

    with patch("determinex_cloak.build_cloak_context", side_effect=RuntimeError("boom")):
        prompt = chat.build_context_prompt("cloak-sess-k", "codex")
    assert "[CLOAK ERROR]" in prompt


def test_build_context_prompt_obfuscates_for_cloud_but_not_local_participant(tmp_path, monkeypatch):
    _rewire(monkeypatch, tmp_path)
    monkeypatch.setenv("DETERMINEX_CLOAK", "1")
    ws = _make_sensitive_workspace(tmp_path)
    chat.create_session("cloak-sess-l", str(ws), ["codex", "local-ollama"], "broadcast")
    msg = "please refactor calculate_super_secret_algorithm and internal_proprietary_constant"
    chat.record_turn("cloak-sess-l", "user", ws, msg, 0, "t0", msg, speaker_kind="user")

    cloud_prompt = chat.build_context_prompt("cloak-sess-l", "codex")
    assert "calculate_super_secret_algorithm" not in cloud_prompt
    assert "internal_proprietary_constant" not in cloud_prompt
    assert "CLOAKED room" in cloud_prompt

    local_prompt = chat.build_context_prompt("cloak-sess-l", "local-ollama")
    assert "calculate_super_secret_algorithm" in local_prompt
    assert "internal_proprietary_constant" in local_prompt
    assert "LOCAL participant" in local_prompt


# ---------------------------------------------------------------------------
# Corpus integration -- "make sure corpus is tied in." Mocked here for speed
# determinism; corpus_context_for() was also verified live against the real
# corpus/programbench/build_knowledge.json during development (found the
# exact git_show_unsupported_filetype_fatal_on_large_diff_20260720 entry).
# ---------------------------------------------------------------------------


class _FakeHit:
    def __init__(self, title, key, snippet):
        self.title, self.key, self.snippet = title, key, snippet


class _FakeAskResult:
    def __init__(self, hits, warnings=None):
        self.hits = hits
        self.warnings = warnings or []


def test_corpus_context_for_empty_query_returns_empty_string():
    assert chat.corpus_context_for("") == ""
    assert chat.corpus_context_for("   ") == ""


def test_corpus_context_for_formats_hits(monkeypatch):
    fake_module = type(sys)("determinex_corpus_api")
    fake_module.ask = lambda q: _FakeAskResult(
        [
            _FakeHit("Some Lesson", "some-lesson-key", "a" * 500),
        ]
    )
    monkeypatch.setitem(sys.modules, "determinex_corpus_api", fake_module)

    result = chat.corpus_context_for("some query")
    assert "Some Lesson" in result
    assert "some-lesson-key" in result
    assert len(result) < 500  # long snippet must be truncated


def test_corpus_context_for_no_hits_returns_empty_string(monkeypatch):
    fake_module = type(sys)("determinex_corpus_api")
    fake_module.ask = lambda q: _FakeAskResult([])
    monkeypatch.setitem(sys.modules, "determinex_corpus_api", fake_module)
    assert chat.corpus_context_for("nothing matches this") == ""


def test_corpus_context_for_failure_is_non_fatal(monkeypatch):
    fake_module = type(sys)("determinex_corpus_api")

    def _raise(q):
        raise RuntimeError("corpus is corrupted")

    fake_module.ask = _raise
    monkeypatch.setitem(sys.modules, "determinex_corpus_api", fake_module)
    assert chat.corpus_context_for("anything") == ""


def test_corpus_context_for_includes_supersession_warning(monkeypatch):
    fake_module = type(sys)("determinex_corpus_api")
    fake_module.ask = lambda q: _FakeAskResult(
        [_FakeHit("Old Claim", "old-claim", "snippet")],
        warnings=["'old-claim' contains a correction -- read carefully"],
    )
    monkeypatch.setitem(sys.modules, "determinex_corpus_api", fake_module)
    result = chat.corpus_context_for("some query")
    assert "correction" in result


def test_build_context_prompt_includes_corpus_lessons_when_relevant(tmp_path, monkeypatch):
    _rewire(monkeypatch, tmp_path)
    ws = _make_sensitive_workspace(tmp_path)
    chat.create_session("sess-corpus-a", str(ws), ["codex"], "broadcast")
    msg = "how do I handle this"
    chat.record_turn("sess-corpus-a", "user", ws, msg, 0, "t0", msg, speaker_kind="user")

    fake_module = type(sys)("determinex_corpus_api")
    fake_module.ask = lambda q: _FakeAskResult(
        [_FakeHit("Corpus Lesson", "corpus-key", "the fix was X")]
    )
    monkeypatch.setitem(sys.modules, "determinex_corpus_api", fake_module)

    prompt = chat.build_context_prompt("sess-corpus-a", "codex")
    assert "Corpus Lesson" in prompt
    assert "relevant lessons from Determinex's own corpus" in prompt


def test_build_context_prompt_unaffected_when_cloak_disabled(tmp_path, monkeypatch):
    _rewire(monkeypatch, tmp_path)
    monkeypatch.delenv("DETERMINEX_CLOAK", raising=False)
    ws = _make_sensitive_workspace(tmp_path)
    chat.create_session("cloak-sess-m", str(ws), ["codex"], "broadcast")
    msg = "please refactor calculate_super_secret_algorithm"
    chat.record_turn("cloak-sess-m", "user", ws, msg, 0, "t0", msg, speaker_kind="user")

    prompt = chat.build_context_prompt("cloak-sess-m", "codex")
    assert "calculate_super_secret_algorithm" in prompt
    assert "PRIVACY" not in prompt


# ---------------------------------------------------------------------------
# Corpus as an addressable chat entity + the oracle feedback loop, 2026-07-22.
# Ryan: "the corpus have an interface and an oracle feedback loop. lets make
# this chat dynamic so that all of them can build from the chat." WRITE side:
# every real agent oracle-verify outcome becomes durable corpus data
# (_record_oracle_outcome / corpus/chat_sessions/oracle_outcomes.jsonl).
# READ side: @corpus responds with corpus hits + this session's own oracle
# history (answer_as_corpus).
# ---------------------------------------------------------------------------


def test_record_turn_agent_message_writes_oracle_outcome_to_corpus(tmp_path, monkeypatch):
    _rewire(monkeypatch, tmp_path)
    chat.create_session("sess-oracle-a", "C:/ws", ["codex"], "broadcast")

    class FakeDiag:
        healthy = True
        oracle = "pytest"
        n_failures = 0

    with patch("determinex_repair.repair_workspace", return_value=FakeDiag()):
        chat.record_turn(
            "sess-oracle-a",
            "codex",
            tmp_path,
            "raw output",
            0,
            "sess-oracle-a-0",
            "do the thing",
            speaker_kind="agent",
        )

    assert chat._ORACLE_OUTCOMES_PATH.exists()
    records = [
        json.loads(line)
        for line in chat._ORACLE_OUTCOMES_PATH.read_text(encoding="utf-8").splitlines()
    ]
    assert len(records) == 1
    assert records[0]["session_id"] == "sess-oracle-a"
    assert records[0]["agent"] == "codex"
    assert records[0]["oracle"] == "pytest"
    assert records[0]["verified"] is True


def test_record_turn_user_and_corpus_turns_do_not_write_oracle_outcomes(tmp_path, monkeypatch):
    _rewire(monkeypatch, tmp_path)
    chat.create_session("sess-oracle-b", "C:/ws", ["codex"], "broadcast")

    chat.record_turn("sess-oracle-b", "user", tmp_path, "hi", 0, "t0", "hi", speaker_kind="user")
    chat.record_turn(
        "sess-oracle-b",
        chat.CORPUS_SPEAKER,
        tmp_path,
        "an answer",
        0,
        "t1",
        "hi",
        speaker_kind="corpus",
    )

    assert not chat._ORACLE_OUTCOMES_PATH.exists()


def test_record_turn_dispatch_failed_does_not_write_oracle_outcome(tmp_path, monkeypatch):
    _rewire(monkeypatch, tmp_path)
    chat.create_session("sess-oracle-c", "C:/ws", ["codex"], "broadcast")

    chat.record_turn(
        "sess-oracle-c",
        "codex",
        tmp_path,
        "spawn error",
        1,
        "t0",
        "do the thing",
        speaker_kind="agent",
        dispatch_failed=True,
    )

    assert not chat._ORACLE_OUTCOMES_PATH.exists()


def test_record_turn_corpus_speaker_kind_is_not_oracle_checked(tmp_path, monkeypatch):
    _rewire(monkeypatch, tmp_path)
    chat.create_session("sess-oracle-d", "C:/ws", ["codex"], "broadcast")

    turn = chat.record_turn(
        "sess-oracle-d",
        chat.CORPUS_SPEAKER,
        tmp_path,
        "the answer",
        0,
        "t0",
        "the question",
        speaker_kind="corpus",
    )

    assert turn.verified is True
    assert turn.note == "corpus response"
    assert turn.oracle == ""


def test_record_oracle_outcome_write_failure_is_non_fatal(tmp_path, monkeypatch):
    _rewire(monkeypatch, tmp_path)
    # Point the outcomes path at something that can never be created as a
    # directory (a file already occupies that name) to force a real write
    # failure -- record_turn must still return a normal turn.
    blocker = tmp_path / "blocker_file"
    blocker.write_text("x", encoding="utf-8")
    monkeypatch.setattr(chat, "_ORACLE_OUTCOMES_PATH", blocker / "oracle_outcomes.jsonl")
    chat.create_session("sess-oracle-e", "C:/ws", ["codex"], "broadcast")

    class FakeDiag:
        healthy = True
        oracle = "pytest"
        n_failures = 0

    with patch("determinex_repair.repair_workspace", return_value=FakeDiag()):
        turn = chat.record_turn(
            "sess-oracle-e", "codex", tmp_path, "raw", 0, "t0", "do it", speaker_kind="agent"
        )
    assert turn.verified is True  # the chat turn itself is unaffected


def test_session_oracle_digest_empty_when_no_outcomes_file(tmp_path, monkeypatch):
    _rewire(monkeypatch, tmp_path)
    assert chat.session_oracle_digest("no-such-session") == ""


def test_session_oracle_digest_filters_by_session_and_counts_verified(tmp_path, monkeypatch):
    _rewire(monkeypatch, tmp_path)
    chat.create_session("sess-digest-a", "C:/ws", ["codex"], "broadcast")
    chat.create_session("sess-digest-b", "C:/ws", ["codex"], "broadcast")

    class Pass:
        healthy = True
        oracle = "pytest"
        n_failures = 0

    class Fail:
        healthy = False
        oracle = "pytest"
        n_failures = 2

    with patch("determinex_repair.repair_workspace", return_value=Pass()):
        chat.record_turn(
            "sess-digest-a", "codex", tmp_path, "ok", 0, "t0", "x", speaker_kind="agent"
        )
    with patch("determinex_repair.repair_workspace", return_value=Fail()):
        chat.record_turn(
            "sess-digest-a", "codex", tmp_path, "bad", 1, "t1", "x", speaker_kind="agent"
        )
    # A different session's outcomes must not leak into sess-digest-a's digest.
    with patch("determinex_repair.repair_workspace", return_value=Pass()):
        chat.record_turn(
            "sess-digest-b", "codex", tmp_path, "ok", 0, "t0", "x", speaker_kind="agent"
        )

    digest = chat.session_oracle_digest("sess-digest-a")
    assert "1/2 agent turns verified" in digest
    assert "PASS" in digest
    assert "FAIL" in digest


def test_last_query_for_session_empty_transcript(tmp_path, monkeypatch):
    _rewire(monkeypatch, tmp_path)
    chat.create_session("sess-lastq-a", "C:/ws", ["codex"], "broadcast")
    assert chat._last_query_for_session("sess-lastq-a") == ""


def test_last_query_for_session_returns_most_recent_message(tmp_path, monkeypatch):
    _rewire(monkeypatch, tmp_path)
    chat.create_session("sess-lastq-b", "C:/ws", ["codex"], "broadcast")
    chat.record_turn(
        "sess-lastq-b", "user", tmp_path, "first", 0, "t0", "first", speaker_kind="user"
    )
    chat.record_turn(
        "sess-lastq-b",
        "user",
        tmp_path,
        "second question",
        0,
        "t1",
        "second question",
        speaker_kind="user",
    )
    assert chat._last_query_for_session("sess-lastq-b") == "second question"


def test_answer_as_corpus_includes_hits_and_oracle_digest(tmp_path, monkeypatch):
    _rewire(monkeypatch, tmp_path)
    chat.create_session("sess-ask-a", "C:/ws", ["codex"], "broadcast")
    chat.record_turn(
        "sess-ask-a",
        "user",
        tmp_path,
        "how do I fix the build",
        0,
        "t0",
        "how do I fix the build",
        speaker_kind="user",
    )

    class Pass:
        healthy = True
        oracle = "pytest"
        n_failures = 0

    with patch("determinex_repair.repair_workspace", return_value=Pass()):
        chat.record_turn(
            "sess-ask-a", "codex", tmp_path, "fixed", 0, "t1", "x", speaker_kind="agent"
        )

    fake_module = type(sys)("determinex_corpus_api")
    fake_module.ask = lambda q: _FakeAskResult(
        [_FakeHit("Build Fix Lesson", "build-fix-key", "do X")]
    )
    monkeypatch.setitem(sys.modules, "determinex_corpus_api", fake_module)

    answer = chat.answer_as_corpus("sess-ask-a")
    assert "Build Fix Lesson" in answer
    assert "oracle-verification history" in answer
    assert "1/1 agent turns verified" in answer


def test_answer_as_corpus_handles_no_hits_and_no_history_gracefully(tmp_path, monkeypatch):
    _rewire(monkeypatch, tmp_path)
    chat.create_session("sess-ask-b", "C:/ws", ["codex"], "broadcast")

    fake_module = type(sys)("determinex_corpus_api")
    fake_module.ask = lambda q: _FakeAskResult([])
    monkeypatch.setitem(sys.modules, "determinex_corpus_api", fake_module)

    answer = chat.answer_as_corpus("sess-ask-b")
    assert "No corpus hits and no oracle-verification history" in answer


def test_answer_as_corpus_survives_corpus_query_failure(tmp_path, monkeypatch):
    _rewire(monkeypatch, tmp_path)
    chat.create_session("sess-ask-c", "C:/ws", ["codex"], "broadcast")
    chat.record_turn(
        "sess-ask-c", "user", tmp_path, "anything", 0, "t0", "anything", speaker_kind="user"
    )

    fake_module = type(sys)("determinex_corpus_api")

    def _raise(q):
        raise RuntimeError("corpus is corrupted")

    fake_module.ask = _raise
    monkeypatch.setitem(sys.modules, "determinex_corpus_api", fake_module)

    answer = chat.answer_as_corpus("sess-ask-c")  # must not raise
    assert isinstance(answer, str)


# ---------------------------------------------------------------------------
# Per-agent model overrides persist with the session (2026-07-31)
#
# `ensure_session_loaded` in agent_chat.rs rehydrates a session's workspace,
# participants and turn_mode from this index after an app restart, but had
# nothing to read models from and reset them to empty. Losing a preference
# would be mild; this was worse. local-ollama's fallback is a DIFFERENT model
# (model_puller::DEFAULT_LOCAL_CHAT_MODEL) from whatever the user picked, so
# the same conversation resumed on another model and nothing said so.
# ---------------------------------------------------------------------------


def test_a_new_session_starts_with_no_model_overrides(tmp_path, monkeypatch):
    _rewire(monkeypatch, tmp_path)
    chat.create_session("s1", str(tmp_path), ["claude-code", "local-ollama"], "broadcast")
    assert chat.session_models("s1") == {}
    # The key must exist on the record so the Rust side reads a real value, not a gap.
    assert chat.get_session("s1")["models"] == {}


def test_set_model_persists_to_the_index(tmp_path, monkeypatch):
    _rewire(monkeypatch, tmp_path)
    chat.create_session("s1", str(tmp_path), ["claude-code", "local-ollama"], "broadcast")

    chat.set_model("s1", "local-ollama", "qwen2.5-coder:14b-instruct-q4_K_M")
    chat.set_model("s1", "claude-code", "opus")

    on_disk = json.loads(chat.INDEX_PATH.read_text(encoding="utf-8"))["s1"]["models"]
    assert on_disk == {
        "local-ollama": "qwen2.5-coder:14b-instruct-q4_K_M",
        "claude-code": "opus",
    }, "the override has to be on the record, or a restart cannot restore it"


def test_a_restart_sees_the_same_models(tmp_path, monkeypatch):
    """The actual regression, expressed the way it is experienced: re-read the index cold."""
    _rewire(monkeypatch, tmp_path)
    chat.create_session("s1", str(tmp_path), ["local-ollama"], "broadcast")
    chat.set_model("s1", "local-ollama", "deepseek-coder:6.7b")

    # Nothing cached: this is what a fresh process does.
    assert chat.session_models("s1") == {"local-ollama": "deepseek-coder:6.7b"}


def test_an_empty_model_clears_the_override(tmp_path, monkeypatch):
    """Mirrors agent_chat_set_model: empty means "use the agent's own default"."""
    _rewire(monkeypatch, tmp_path)
    chat.create_session("s1", str(tmp_path), ["claude-code"], "broadcast")
    chat.set_model("s1", "claude-code", "opus")

    chat.set_model("s1", "claude-code", "")

    assert chat.session_models("s1") == {}
    assert (
        "claude-code" not in json.loads(chat.INDEX_PATH.read_text(encoding="utf-8"))["s1"]["models"]
    )


def test_a_whitespace_model_is_not_stored(tmp_path, monkeypatch):
    """A blank tag is the empty-model 404 this module already guards against elsewhere."""
    _rewire(monkeypatch, tmp_path)
    chat.create_session("s1", str(tmp_path), ["local-ollama"], "broadcast")
    chat.set_model("s1", "local-ollama", "   ")
    assert chat.session_models("s1") == {}


def test_model_names_are_stripped(tmp_path, monkeypatch):
    _rewire(monkeypatch, tmp_path)
    chat.create_session("s1", str(tmp_path), ["local-ollama"], "broadcast")
    chat.set_model("s1", "local-ollama", "  qwen2.5-coder:7b-instruct \n")
    assert chat.session_models("s1") == {"local-ollama": "qwen2.5-coder:7b-instruct"}


def test_setting_one_agents_model_leaves_the_others_alone(tmp_path, monkeypatch):
    _rewire(monkeypatch, tmp_path)
    chat.create_session("s1", str(tmp_path), ["a", "b"], "broadcast")
    chat.set_model("s1", "a", "model-a")
    chat.set_model("s1", "b", "model-b")
    chat.set_model("s1", "a", "model-a2")
    assert chat.session_models("s1") == {"a": "model-a2", "b": "model-b"}


def test_set_model_on_an_unknown_session_is_an_error(tmp_path, monkeypatch):
    """Must not conjure a session record from a stray call."""
    _rewire(monkeypatch, tmp_path)
    try:
        chat.set_model("nope", "claude-code", "opus")
    except KeyError as exc:
        assert "nope" in str(exc)
    else:
        raise AssertionError("set_model accepted an unknown session")
    assert chat.get_session("nope") is None


def test_a_session_predating_model_persistence_still_opens(tmp_path, monkeypatch):
    """Records written before this change have no `models` key at all."""
    _rewire(monkeypatch, tmp_path)
    chat.create_session("s1", str(tmp_path), ["a"], "broadcast")
    index = json.loads(chat.INDEX_PATH.read_text(encoding="utf-8"))
    del index["s1"]["models"]
    chat.INDEX_PATH.write_text(json.dumps(index), encoding="utf-8")

    assert chat.session_models("s1") == {}
    chat.set_model("s1", "a", "opus")
    assert chat.session_models("s1") == {"a": "opus"}


def test_a_corrupt_models_field_reads_as_no_overrides(tmp_path, monkeypatch):
    """A chat that will not open is worse than one that opens on defaults."""
    _rewire(monkeypatch, tmp_path)
    chat.create_session("s1", str(tmp_path), ["a"], "broadcast")
    for junk in ("not-a-dict", 42, ["a", "b"]):
        index = json.loads(chat.INDEX_PATH.read_text(encoding="utf-8"))
        index["s1"]["models"] = junk
        chat.INDEX_PATH.write_text(json.dumps(index), encoding="utf-8")
        assert chat.session_models("s1") == {}


def test_models_survive_other_index_updates(tmp_path, monkeypatch):
    """record_turn bumps last_active/turn_count through update_index; that must not drop models."""
    _rewire(monkeypatch, tmp_path)
    chat.create_session("s1", str(tmp_path), ["a"], "broadcast")
    chat.set_model("s1", "a", "opus")
    chat.update_index("s1", turn_count=7, last_active="2026-07-31T00:00:00Z")
    assert chat.session_models("s1") == {"a": "opus"}
    assert chat.get_session("s1")["turn_count"] == 7
