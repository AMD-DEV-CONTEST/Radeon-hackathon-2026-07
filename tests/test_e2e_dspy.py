"""End-to-end tests for the DSPy demo golden path.

These tests exercise the app's real orchestration layer
(``BunkerOrchestrator``) driving both the multi-hop RAG program and the
DSPy ReAct agent against a real (offline) ChromaDB store and a real PDF
fixture. The only mocked component is the local LM itself: every LLM
completion is scripted via ``dspy_runtime.BUNKER_LM.forward``, matching the
per-component tests in ``tests/test_dspy_rag.py`` and
``tests/test_dspy_agent.py``.
"""

import json
import types
from unittest.mock import patch

import numpy  # noqa: F401 — fully initialize numpy before dspy/chromadb (lazy-import proxy guard)

import pytest
import fitz

from src import dspy_runtime
from src.agent import DspyReActAgent, PermissionController
from src.agent.orchestrator import BunkerOrchestrator, heuristic_router
from src.privacy import AuditLogger, DataFlowMonitor
from src.rag.document_loader import DocumentLoader
from src.rag.multihop_rag import BunkerMultiHopRAG, make_chromadb_search
from src.rag.vector_store import VectorStore


# ---------------------------------------------------------------------------
# Scripted LM responses (same shapes as the per-component tests)
# ---------------------------------------------------------------------------


def _fake_completion_response(text: str):
    """Build an OpenAI chat-completion-shaped object for a mocked LM.forward()."""
    message = types.SimpleNamespace(content=text, tool_calls=None)
    choice = types.SimpleNamespace(message=message, finish_reason="stop", logprobs=None)
    return types.SimpleNamespace(
        choices=[choice],
        model=dspy_runtime.BUNKER_LM.model,
        usage={"prompt_tokens": 5, "completion_tokens": 4, "total_tokens": 9},
        cache_hit=False,
        _hidden_params={},
    )


def _route_response(intent: str):
    return _fake_completion_response(
        "[[ ## reasoning ## ]]\nDecide the route.\n\n"
        f"[[ ## intent ## ]]\n{intent}\n\n"
        "[[ ## completed ## ]]"
    )


def _query_response(query: str):
    return _fake_completion_response(
        "[[ ## reasoning ## ]]\nDecide the next query.\n\n"
        f"[[ ## query ## ]]\n{query}\n\n"
        "[[ ## completed ## ]]"
    )


def _notes_response(notes_json: str):
    return _fake_completion_response(
        "[[ ## reasoning ## ]]\nExtract new facts.\n\n"
        f"[[ ## new_notes ## ]]\n{notes_json}\n\n"
        "[[ ## completed ## ]]"
    )


def _answer_response(answer: str):
    return _fake_completion_response(
        "[[ ## reasoning ## ]]\nGather the grounded answer.\n\n"
        f"[[ ## answer ## ]]\n{answer}\n\n"
        "[[ ## completed ## ]]"
    )


def _plan_response(plan_json: str):
    return _fake_completion_response(
        "[[ ## reasoning ## ]]\nPlan the steps.\n\n"
        f"[[ ## plan ## ]]\n{plan_json}\n\n"
        "[[ ## completed ## ]]"
    )


def _react_response(thought: str, tool_name: str, tool_args_json: str):
    return _fake_completion_response(
        f"[[ ## next_thought ## ]]\n{thought}\n\n"
        f"[[ ## next_tool_name ## ]]\n{tool_name}\n\n"
        f"[[ ## next_tool_args ## ]]\n{tool_args_json}\n\n"
        "[[ ## completed ## ]]"
    )


def _extract_response(answer: str):
    return _fake_completion_response(
        "[[ ## reasoning ## ]]\nGather the answer.\n\n"
        f"[[ ## answer ## ]]\n{answer}\n\n"
        "[[ ## completed ## ]]"
    )


# ---------------------------------------------------------------------------
# Offline document + vector store fixture
# ---------------------------------------------------------------------------


class FakeEmbedder:
    """Zero-vector embedder so ChromaDB runs fully offline (no model download)."""

    def __init__(self, dim: int = 384):
        self.dim = dim

    def embed_documents(self, texts):
        return [[0.0] * self.dim for _ in texts]

    def embed_query(self, text):
        return [0.0] * self.dim


def _make_two_section_pdf(path):
    """Create a two-section PDF fixture with PyMuPDF (fitz)."""
    sections = [
        "Section A: The Eiffel Tower is located in Paris, France.",
        "Section B: Paris is the capital of France.",
    ]
    doc = fitz.open()
    for text in sections:
        page = doc.new_page()
        page.insert_text((72, 72), text, fontsize=12)
    doc.save(str(path))
    doc.close()
    return path


def _build_rag(tmp_path):
    """Ingest the PDF fixture into an offline ChromaDB store and build the RAG."""
    pdf_path = _make_two_section_pdf(tmp_path / "report.pdf")
    chunks = DocumentLoader(chunk_size=512, chunk_overlap=50).load_file(str(pdf_path))
    store = VectorStore(
        embeddings=FakeEmbedder(),
        persist_dir=str(tmp_path / "vector_db"),
    )
    store.add_documents(chunks)
    rag = BunkerMultiHopRAG(
        search=make_chromadb_search(store),
        num_hops=2,
        num_docs=2,
    )
    return rag, store, chunks, pdf_path


# ---------------------------------------------------------------------------
# Demo golden path: RAG question -> email draft + save -> follow-up
# ---------------------------------------------------------------------------


def test_e2e_demo_golden_path(tmp_path, monkeypatch):
    """Two turns through the orchestrator: cited RAG answer, then a gated,
    audited, locally-recorded agent turn that reuses turn 1 without re-retrieving."""
    monkeypatch.chdir(tmp_path)  # email_draft writes ./data/documents/email_drafts
    rag, store, chunks, pdf_path = _build_rag(tmp_path)
    assert len(chunks) >= 2  # the fixture really has two sections

    controller = PermissionController({"demo_mode": True})
    monitor = DataFlowMonitor()
    audit = AuditLogger(log_path=str(tmp_path / "audit" / "audit.jsonl"))
    agent = DspyReActAgent(
        permission_controller=controller,
        base_dir=str(tmp_path),
        data_flow_monitor=monitor,
        audit_logger=audit,
    )
    orchestrator = BunkerOrchestrator(rag=rag, agent=agent)

    turn1_message = (
        "Answer from the uploaded PDF: where is the Eiffel Tower and "
        "what country is it in?"
    )
    turn2_message = (
        "Based on the previous answer, draft an email to user@example.com "
        "and save a copy."
    )

    responses = [
        _route_response("rag"),
        _query_response("Where is the Eiffel Tower located?"),
        _notes_response('["The Eiffel Tower is located in Paris."]'),
        _query_response("What is the capital of France?"),
        _notes_response('["Paris is the capital of France."]'),
        _answer_response(
            "The Eiffel Tower is in Paris [1] and Paris is the capital of France [2]."
        ),
        _route_response("agent"),
        _plan_response('[{"step": 1, "action": "draft", "tool": "email_draft", "rationale": "draft email"}]'),
        _react_response(
            "Draft the email.",
            "email_draft",
            json.dumps({
                "to": "user@example.com",
                "subject": "Eiffel Tower",
                "body": "The Eiffel Tower is in Paris.",
            }),
        ),
        _react_response(
            "Save a copy.",
            "file_write",
            json.dumps({"path": "email.txt", "content": "The Eiffel Tower is in Paris."}),
        ),
        _react_response("Done.", "finish", "{}"),
        _extract_response("Drafted and saved the email."),
    ]

    # Spy on the agent run to capture the threaded history it received.
    seen = {}
    original_run = DspyReActAgent.run

    def _spy_run(self, user_message, session_id="", context=None):
        seen["user_message"] = user_message
        seen["context"] = list(context or [])
        return original_run(self, user_message, session_id=session_id, context=context)

    with patch.object(dspy_runtime.BUNKER_LM, "forward", side_effect=responses):
        with patch.object(DspyReActAgent, "run", new=_spy_run):
            turn1 = orchestrator.run(turn1_message)
            turn2 = orchestrator.run(turn2_message)

    # --- Turn 1: multi-hop RAG, grounded with valid [pid] citations. ---
    assert turn1["intent"] == "rag"
    assert turn1["grounded"] is True
    assert turn1["citations"] == 2
    assert "[1]" in turn1["response"] and "[2]" in turn1["response"]
    assert len(turn1["queries"]) == 2
    assert len(turn1["notes"]) == 2

    # Retrieval ran exactly num_hops times on turn 1 and never on turn 2.
    assert store.search.call_count == 2

    # --- Turn 2: agent path; history from turn 1 threaded into the agent. ---
    assert turn2["intent"] == "agent"
    assert turn2["response"] == "Drafted and saved the email."
    real_tool_calls = [call["tool"] for call in turn2["tool_calls"] if call["tool"] != "finish"]
    assert real_tool_calls == ["email_draft", "file_write"]
    assert seen["user_message"] == turn2_message
    threaded = seen["context"]
    assert threaded[0] == {"role": "user", "content": turn1_message}
    assert threaded[1]["role"] == "assistant"
    assert "Eiffel" in threaded[1]["content"] and "[1]" in threaded[1]["content"]

    # --- PermissionController.gate invoked for both dangerous tools. ---
    gated = {entry["tool"]: entry for entry in controller.get_history()}
    assert set(gated) == {"email_draft", "file_write"}
    assert gated["email_draft"]["approved"] is True
    assert gated["file_write"]["approved"] is True

    # The "save" actually wrote a local file.
    assert (tmp_path / "email.txt").read_text(encoding="utf-8") == "The Eiffel Tower is in Paris."

    # --- DataFlowMonitor: only local events -> 100% localhost. ---
    status = monitor.get_current_status()
    assert status["local_percentage"] == 100.0
    assert status["external_bytes"] == 0
    event_tools = {
        e["metadata"]["tool"]
        for e in status["recent_events"]
        if e["event_type"] == "tool_call"
    }
    assert {"email_draft", "file_write"} <= event_tools

    # --- AuditLogger captured both tool calls. ---
    audited = {
        e["details"]["tool_name"]
        for e in audit.get_recent_events(20)
        if e["event_type"] == "tool_call"
    }
    assert {"email_draft", "file_write"} <= audited

    # --- Orchestrator threaded the whole conversation. ---
    assert [h["role"] for h in orchestrator.history] == [
        "user", "assistant", "user", "assistant",
    ]


# ---------------------------------------------------------------------------
# Orchestrator routing (deterministic, no LM)
# ---------------------------------------------------------------------------


class _FakeRag:
    def __call__(self, question):
        return types.SimpleNamespace(
            answer=f"rag answer for: {question}",
            grounded=True,
            citation_count=2,
            queries=["q"],
            notes=["n"],
        )


class _FakeAgent:
    def run(self, user_message, session_id="", context=None):
        return {"response": "agent answer", "trajectory": {}, "tool_calls": []}


def test_orchestrator_heuristic_router_routes_deterministically():
    """The heuristic router sends document questions to RAG and tool requests to the agent."""
    orchestrator = BunkerOrchestrator(
        rag=_FakeRag(),
        agent=_FakeAgent(),
        router=heuristic_router,
    )

    turn1 = orchestrator.run("Answer from the pdf about the Eiffel Tower")
    turn2 = orchestrator.run("draft an email for me")

    assert turn1["intent"] == "rag"
    assert turn1["grounded"] is True
    assert turn1["citations"] == 2
    assert turn2["intent"] == "agent"
    assert turn2["response"] == "agent answer"
    assert orchestrator.history == [
        {"role": "user", "content": "Answer from the pdf about the Eiffel Tower"},
        {"role": "assistant", "content": "rag answer for: Answer from the pdf about the Eiffel Tower"},
        {"role": "user", "content": "draft an email for me"},
        {"role": "assistant", "content": "agent answer"},
    ]


def test_orchestrator_lm_router_falls_back_to_heuristic_on_error():
    """When the LM router fails, routing falls back to the deterministic heuristic."""
    orchestrator = BunkerOrchestrator(rag=_FakeRag(), agent=_FakeAgent())

    with patch("src.agent.orchestrator.route_request", side_effect=RuntimeError("router down")):
        result = orchestrator.run("save the file")

    assert result["intent"] == "agent"
    assert result["response"] == "agent answer"
