"""Chat turns propose edits; they never write.

FOUND BY MEASUREMENT 2026-07-31, not by reading code. A chat session whose only message was "What
is the capital of France? Answer in one word." was run six times against the chat default
(qwen2.5-coder:3b-instruct) on a workspace holding one file. Five turns answered in prose. One
rewrote the workspace's main.rs from `println!("hi")` to `println!("Hello, world!")` -- an
unrequested edit to a source file, from a turn that asked nothing about code.

That is sampling, not prompt wording. Three separate prompt fixes were tried and measured first:
the local agent's system prompt, the order of its prompt sections, and finally the chat room's own
framing (which had been telling every participant to "make the edits that best move the task
forward"). The framing fix was real and necessary -- it took a conversational turn from a hard rc=1
failure to a clean prose answer -- but it could not make the unrequested write impossible, only
rarer. So the write became structurally unavailable: a chat turn emits a validated proposal, and
`apply_proposal` is the only path that puts bytes on disk.

What is verified here is the approval boundary itself: extraction, the staleness refusal that keeps
a proposal from discarding the user's own edit, all-or-nothing multi-file application, and the
refusal of a path that leaves the workspace. Approving a diff approves that change, not write
access to the disk.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
for _p in (_ROOT, _ROOT / "scripts"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import determinex_agent_chat as chat  # noqa: E402

BEFORE = 'fn main() {\n    println!("hi");\n}\n'
AFTER = 'fn main() {\n    println!("hello world");\n}\n'


@pytest.fixture()
def chatroom(tmp_path, monkeypatch):
    """A rewired session store plus a workspace holding one real file."""
    sessions = tmp_path / "corpus" / "chat_sessions"
    monkeypatch.setattr(chat, "SESSIONS_DIR", sessions)
    monkeypatch.setattr(chat, "INDEX_PATH", sessions / "_index.json")
    if hasattr(chat, "_ORACLE_OUTCOMES_PATH"):
        monkeypatch.setattr(chat, "_ORACLE_OUTCOMES_PATH", sessions / "oracle_outcomes.jsonl")
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "main.rs").write_text(BEFORE, encoding="utf-8")
    chat.create_session("s1", str(ws), ["local-ollama"], "broadcast")
    return ws


def proposal_block(files: list[dict]) -> str:
    payload = {"schema": chat.PROPOSAL_SCHEMA, "files": files}
    return f"{chat.PROPOSAL_BEGIN}\n{json.dumps(payload)}\n{chat.PROPOSAL_END}"


def record_proposal(turn_id: str, files: list[dict], prose: str = "on it") -> None:
    chat.append_turn(
        chat.ChatTurn(
            turn_id=turn_id,
            session_id="s1",
            seq=1,
            speaker="local-ollama",
            speaker_kind="agent",
            addressed_to=[],
            mode="broadcast",
            task_prompt="change it",
            raw_output=f"{prose}\n{proposal_block(files)}",
            returncode=0,
            verified=True,
            oracle="",
            n_failures=0,
            note="",
            started_at="2026-07-31T00:00:00Z",
            finished_at="2026-07-31T00:00:01Z",
        )
    )


class TestProposalExtraction:
    def test_a_proposal_is_read_back_out_of_a_turn(self):
        raw = f"prose\n{proposal_block([{'path': 'a.rs', 'before': 'x', 'after': 'y'}])}\ntrailing"
        assert chat.extract_proposals(raw) == [{"path": "a.rs", "before": "x", "after": "y"}]

    def test_prose_with_no_proposal_yields_nothing(self):
        assert chat.extract_proposals("The capital of France is Paris.") == []

    def test_multiple_blocks_are_all_read(self):
        a = proposal_block([{"path": "a.rs", "before": "b", "after": "a"}])
        b = proposal_block([{"path": "b.rs", "before": "b", "after": "a"}])
        assert [p["path"] for p in chat.extract_proposals(f"{a}\nmid\n{b}")] == ["a.rs", "b.rs"]

    def test_malformed_json_is_skipped_not_raised(self):
        """One junk block must not make a whole transcript unreadable."""
        assert (
            chat.extract_proposals(f"{chat.PROPOSAL_BEGIN}\n{{ not json\n{chat.PROPOSAL_END}") == []
        )

    def test_an_unknown_schema_is_ignored(self):
        payload = json.dumps(
            {"schema": "something-else", "files": [{"path": "a", "before": "", "after": "x"}]}
        )
        assert (
            chat.extract_proposals(f"{chat.PROPOSAL_BEGIN}\n{payload}\n{chat.PROPOSAL_END}") == []
        )

    def test_an_unterminated_block_is_ignored(self):
        payload = json.dumps({"schema": chat.PROPOSAL_SCHEMA, "files": []})
        assert chat.extract_proposals(f"{chat.PROPOSAL_BEGIN}\n{payload}") == []

    def test_entries_missing_fields_are_dropped(self):
        raw = proposal_block(
            [
                {"path": "good.rs", "before": "b", "after": "a"},
                {"path": "no-after.rs", "before": "b"},
                {"before": "b", "after": "a"},
            ]
        )
        assert [p["path"] for p in chat.extract_proposals(raw)] == ["good.rs"]


class TestApplyingAnApprovedProposal:
    def test_recording_a_turn_writes_nothing(self, chatroom):
        """The regression, stated directly: the turn exists and the file is untouched."""
        record_proposal("t1", [{"path": "main.rs", "before": BEFORE, "after": AFTER}])
        assert (chatroom / "main.rs").read_text(encoding="utf-8") == BEFORE

    def test_it_writes_when_approved(self, chatroom):
        record_proposal("t1", [{"path": "main.rs", "before": BEFORE, "after": AFTER}])

        result = chat.apply_proposal("s1", "t1", chatroom)

        assert result["applied"] == ["main.rs"]
        assert (chatroom / "main.rs").read_text(encoding="utf-8") == AFTER

    def test_a_stale_proposal_is_refused(self, chatroom):
        """Why the proposal carries `before`: the user's own edit must not be discarded."""
        record_proposal("t1", [{"path": "main.rs", "before": BEFORE, "after": AFTER}])
        mine = "// the user changed this themselves\n"
        (chatroom / "main.rs").write_text(mine, encoding="utf-8")

        with pytest.raises(ValueError, match="has changed since this was proposed"):
            chat.apply_proposal("s1", "t1", chatroom)
        assert (chatroom / "main.rs").read_text(encoding="utf-8") == mine

    def test_applying_twice_is_refused(self, chatroom):
        record_proposal("t1", [{"path": "main.rs", "before": BEFORE, "after": AFTER}])
        chat.apply_proposal("s1", "t1", chatroom)
        with pytest.raises(ValueError, match="has changed since"):
            chat.apply_proposal("s1", "t1", chatroom)

    def test_a_relative_escape_is_refused(self, chatroom):
        """Approving a diff approves that change, not write access to the disk."""
        record_proposal("t1", [{"path": "../escaped.txt", "before": "", "after": "owned"}])

        with pytest.raises(ValueError, match="escapes the workspace"):
            chat.apply_proposal("s1", "t1", chatroom)
        assert not (chatroom.parent / "escaped.txt").exists()

    def test_an_absolute_path_is_refused(self, chatroom):
        outside = chatroom.parent / "outside.txt"
        record_proposal("t1", [{"path": str(outside), "before": "", "after": "owned"}])

        with pytest.raises(ValueError, match="escapes the workspace"):
            chat.apply_proposal("s1", "t1", chatroom)
        assert not outside.exists()

    def test_a_multi_file_proposal_is_all_or_nothing(self, chatroom):
        """A half-applied proposal is a worse state than a refused one."""
        (chatroom / "other.rs").write_text("original\n", encoding="utf-8")
        record_proposal(
            "t1",
            [
                {"path": "main.rs", "before": BEFORE, "after": AFTER},
                {"path": "other.rs", "before": "STALE -- not what is on disk\n", "after": "new\n"},
            ],
        )

        with pytest.raises(ValueError, match="has changed since this was proposed"):
            chat.apply_proposal("s1", "t1", chatroom)
        assert (chatroom / "main.rs").read_text(encoding="utf-8") == BEFORE, (
            "main.rs was written before the stale second file was noticed"
        )
        assert (chatroom / "other.rs").read_text(encoding="utf-8") == "original\n"

    def test_a_new_file_proposal_applies(self, chatroom):
        """An empty `before` is a file that does not exist yet."""
        record_proposal("t1", [{"path": "src/new.rs", "before": "", "after": "fn new() {}\n"}])
        chat.apply_proposal("s1", "t1", chatroom)
        assert (chatroom / "src" / "new.rs").read_text(encoding="utf-8") == "fn new() {}\n"

    def test_a_turn_with_no_proposal_is_an_error(self, chatroom):
        chat.append_turn(
            chat.ChatTurn(
                turn_id="t1",
                session_id="s1",
                seq=1,
                speaker="local-ollama",
                speaker_kind="agent",
                addressed_to=[],
                mode="broadcast",
                task_prompt="q",
                raw_output="Paris.",
                returncode=0,
                verified=True,
                oracle="",
                n_failures=0,
                note="",
                started_at="x",
                finished_at="y",
            )
        )
        with pytest.raises(ValueError, match="no proposed edits"):
            chat.apply_proposal("s1", "t1", chatroom)

    def test_an_unknown_turn_is_an_error(self, chatroom):
        with pytest.raises(KeyError, match="no turn"):
            chat.apply_proposal("s1", "nope", chatroom)


class TestTheLocalAgentProposesInsteadOfWriting:
    """The producer side of the same boundary."""

    def test_chat_mode_does_not_touch_the_file(self, tmp_path):
        import determinex_local_agent as agent

        ws = tmp_path / "ws"
        ws.mkdir()
        (ws / "main.rs").write_text(BEFORE, encoding="utf-8")
        by_file = {
            "main.rs": '<<<SEARCH\n    println!("hi");\n===\n    println!("hello world");\n>>>REPLACE\n'
        }
        proposals: list = []

        applied, attempted, failures, notes = agent._apply_edits(
            by_file, ws, propose_only=True, proposals=proposals
        )

        assert attempted is True
        assert not failures
        assert (ws / "main.rs").read_text(encoding="utf-8") == BEFORE, "chat mode wrote to disk"
        assert proposals == [{"path": "main.rs", "before": BEFORE, "after": AFTER}]
        assert any("PROPOSED" in n and "awaiting your approval" in n for n in notes)

    def test_edit_mode_still_writes(self, tmp_path):
        """The non-chat contract is unchanged -- the hive and run_agent still edit for real."""
        import determinex_local_agent as agent

        ws = tmp_path / "ws"
        ws.mkdir()
        (ws / "main.rs").write_text(BEFORE, encoding="utf-8")
        by_file = {
            "main.rs": '<<<SEARCH\n    println!("hi");\n===\n    println!("hello world");\n>>>REPLACE\n'
        }

        applied, _attempted, failures, _notes = agent._apply_edits(by_file, ws)

        assert applied is True
        assert not failures
        assert (ws / "main.rs").read_text(encoding="utf-8") == AFTER

    def test_a_proposal_that_matches_nothing_is_a_failure_not_a_proposal(self, tmp_path):
        """Validated, not echoed: a patch the user is shown is one that provably applies."""
        import determinex_local_agent as agent

        ws = tmp_path / "ws"
        ws.mkdir()
        (ws / "main.rs").write_text(BEFORE, encoding="utf-8")
        by_file = {
            "main.rs": "<<<SEARCH\nthis text is not in the file\n===\nreplacement\n>>>REPLACE\n"
        }
        proposals: list = []

        _applied, attempted, failures, _notes = agent._apply_edits(
            by_file, ws, propose_only=True, proposals=proposals
        )

        assert attempted is True
        assert failures, "an unmatched SEARCH must feed the retry escalation, not become a proposal"
        assert proposals == []

    def test_the_rendered_block_round_trips_through_the_reader(self, tmp_path):
        """The two halves of the boundary must agree on the format."""
        import determinex_local_agent as agent

        rendered = agent._render_proposal([{"path": "main.rs", "before": BEFORE, "after": AFTER}])
        assert "NOT written" in rendered, "a transcript with no button must still say what happened"
        assert chat.extract_proposals(rendered) == [
            {"path": "main.rs", "before": BEFORE, "after": AFTER}
        ]

    def test_the_two_modules_use_the_same_markers(self):
        """One format, defined twice, is a format that will drift."""
        import determinex_local_agent as agent

        assert agent.PROPOSAL_BEGIN == chat.PROPOSAL_BEGIN
        assert agent.PROPOSAL_END == chat.PROPOSAL_END
