"""Step definitions for Bunker's BDD suite (behave).

The features under ``tests/features/`` pin the two acceptance contracts that
matter most to Bunker:

* ``grounded_rag.feature`` -- multi-hop answers must cite the local passages
  they rely on, and the pipeline must refuse to fabricate facts when the
  retrieved context is insufficient.
* ``privacy.feature`` -- write tools are gated behind explicit consent, and
  no code path may dial out to a non-loopback host.

Live-model steps follow the repository's statistical convention (see
``tests/test_integration_qwen.py``): when the local model is serving on
``http://localhost:8000/v1`` they run the real pipeline ``_NUM_RUNS`` times
and assert a ``_PASS_THRESHOLD`` pass rate; otherwise they fall back to the
deterministic offline pipeline with a scripted LM, so the suite runs on any
machine. All traffic stays on localhost either way.
"""

import re
import socket as socket_module
import types
from unittest.mock import patch

import dspy

from behave import given, then, when

from src import dspy_runtime
from src.agent.permission_controller import PermissionController
from src.config import get_config
from src.rag.multihop_rag import (
    BunkerGroundingError,
    BunkerMultiHopRAG,
    extract_citations,
    make_chromadb_search,
)

_NUM_RUNS = 10
_PASS_THRESHOLD = 0.8

_LOOPBACK_HOSTS = ("127.0.0.1", "localhost", "::1")

# Sentinels for the live-mode results list.
_REFUSED = object()
_ERROR = object()


# ---------------------------------------------------------------------------
# Local model probe and live LM (localhost:8000/v1 only)
# ---------------------------------------------------------------------------


def _vllm_is_healthy() -> bool:
    """Return True when a vLLM server is answering on localhost:8000."""
    try:
        import requests

        return requests.get("http://localhost:8000/health", timeout=2).status_code == 200
    except Exception:
        return False


def _live_lm() -> dspy.LM:
    """The live local model, pinned to localhost:8000/v1 with caching off."""
    served_model = get_config().inference.primary_model
    if not served_model.startswith("openai/"):
        served_model = f"openai/{served_model}"
    return dspy.LM(
        served_model,
        api_base="http://localhost:8000/v1",
        api_key="EMPTY",
        temperature=0.0,
        cache=False,
    )


def _pass_rate(predicates: list) -> float:
    """Fraction of ``predicates`` that are truthy."""
    if not predicates:
        return 0.0
    return sum(1 for p in predicates if p) / len(predicates)


# ---------------------------------------------------------------------------
# Scripted offline LM responses (mirrors tests/test_dspy_rag.py)
# ---------------------------------------------------------------------------


def _fake_completion_response(text: str) -> types.SimpleNamespace:
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


def _query_response(query: str) -> types.SimpleNamespace:
    return _fake_completion_response(
        "[[ ## reasoning ## ]]\nDecide the next query.\n\n"
        f"[[ ## query ## ]]\n{query}\n\n"
        "[[ ## completed ## ]]"
    )


def _notes_response(notes_json: str) -> types.SimpleNamespace:
    return _fake_completion_response(
        "[[ ## reasoning ## ]]\nExtract new facts.\n\n"
        f"[[ ## new_notes ## ]]\n{notes_json}\n\n"
        "[[ ## completed ## ]]"
    )


def _answer_response(answer: str) -> types.SimpleNamespace:
    return _fake_completion_response(
        "[[ ## reasoning ## ]]\nGather the grounded answer.\n\n"
        f"[[ ## answer ## ]]\n{answer}\n\n"
        "[[ ## completed ## ]]"
    )


# ---------------------------------------------------------------------------
# Local vector store (ChromaDB-shaped search results)
# ---------------------------------------------------------------------------


class _PassageStore:
    """Stand-in for VectorStore.search returning ChromaDB-shaped dicts."""

    def __init__(self, passages):
        self.passages = passages  # list of (keyword, text)
        self.calls = []

    def search(self, query: str, k: int = 5, **kwargs):
        self.calls.append((query, k))
        q = query.lower()
        results = []
        for i, (keyword, text) in enumerate(self.passages):
            if keyword in q:
                results.append({
                    "id": f"p{i}",
                    "text": text,
                    "metadata": {"source": "fixture.pdf"},
                    "distance": float(i),
                })
        return results[:k]


def _offline_multihop_responses(num_hops: int) -> list:
    """Scripted LM for a grounded multi-hop run ending in a [1] [2] answer."""
    queries = [
        "Where is the Eiffel Tower located?",
        "What is the capital of France?",
    ]
    responses = []
    for i in range(num_hops):
        responses.append(_query_response(queries[i % len(queries)]))
        responses.append(_notes_response(f'["Passage note {i + 1}."]'))
    responses.append(
        _answer_response("The Eiffel Tower is in Paris, the capital of France. [1] [2]")
    )
    return responses


def _offline_insufficient_responses() -> list:
    """Scripted LM that keeps citing [9] so grounding fails honestly."""
    return [
        _query_response("Find evidence about the telephone."),
        _notes_response("[]"),
        _answer_response("Alexander Graham Bell invented the telephone. [9]"),
        _answer_response("Alexander Graham Bell invented the telephone. [9]"),
        _answer_response("Alexander Graham Bell invented the telephone. [9]"),
    ]


# ---------------------------------------------------------------------------
# RAG scenario steps
# ---------------------------------------------------------------------------


@given("a local vector store containing passages about the Eiffel Tower and Paris")
def step_store_eiffel_and_paris(context):
    context.store = _PassageStore([
        ("eiffel", "The Eiffel Tower is located in Paris, France."),
        ("capital", "Paris is the capital of France."),
        ("france", "France is a country located primarily in Western Europe."),
    ])


@given("a local vector store containing one passage about the Eiffel Tower")
def step_store_one_eiffel(context):
    context.store = _PassageStore([
        ("eiffel", "The Eiffel Tower is located in Paris, France."),
    ])


@given("a local vector store with no passages matching the question")
def step_store_empty(context):
    context.store = _PassageStore([])


@given("the Bunker multi-hop RAG program with {hops} hops over that store")
@given("the Bunker multi-hop RAG program with {hops} hop over that store")
def step_rag_program(context, hops):
    context.num_hops = int(hops)
    context.rag = BunkerMultiHopRAG(
        search=make_chromadb_search(context.store),
        num_hops=int(hops),
        num_docs=2,
        max_backtracks=2,
    )


@when('a user asks "{question}"')
def step_user_asks(context, question):
    context.question = question
    context.live = _vllm_is_healthy()

    if context.live:
        lm = _live_lm()
        results = []
        for _ in range(_NUM_RUNS):
            try:
                with dspy.context(lm=lm):
                    results.append(context.rag(question=question))
            except BunkerGroundingError:
                results.append(_REFUSED)
            except Exception:
                results.append(_ERROR)
        context.results = results
        return

    context.refused = False
    responses = (
        _offline_insufficient_responses()
        if not context.store.passages
        else _offline_multihop_responses(context.num_hops)
    )
    try:
        with patch.object(dspy_runtime.BUNKER_LM, "forward", side_effect=responses):
            context.results = [context.rag(question=question)]
    except BunkerGroundingError:
        context.refused = True
        context.results = []


@then("the answer is grounded in at least two distinct passages")
def step_grounded_in_two_passages(context):
    if context.live:
        def _ok(result):
            if result in (_REFUSED, _ERROR):
                return False
            distinct = {p for ctx in result.contexts for p in ctx}
            return len(distinct) >= 2 and result.grounded is True

        rate = _pass_rate([_ok(r) for r in context.results])
        assert rate >= _PASS_THRESHOLD, (
            f"Two-passage grounding pass rate was {rate:.0%} "
            f"(need >= {_PASS_THRESHOLD:.0%})."
        )
        return

    result = context.results[0]
    distinct = {p for ctx in result.contexts for p in ctx}
    assert len(distinct) >= 2, f"Answer drew from only {len(distinct)} distinct passage(s)"
    assert result.grounded is True
    assert result.backtracks == 0


@then("the answer cites the passages it relies on")
def step_answer_cites_passages(context):
    if context.live:
        def _ok(result):
            if result in (_REFUSED, _ERROR):
                return False
            citations = extract_citations(str(result.answer))
            return bool(citations) and all(1 <= pid <= len(result.notes) for pid in citations)

        rate = _pass_rate([_ok(r) for r in context.results])
        assert rate >= _PASS_THRESHOLD, (
            f"Citation validity pass rate was {rate:.0%} "
            f"(need >= {_PASS_THRESHOLD:.0%})."
        )
        return

    result = context.results[0]
    citations = extract_citations(result.answer)
    assert citations, "Answer has no [pid] citations"
    assert all(1 <= pid <= len(result.notes) for pid in citations), (
        f"Answer cites out-of-range passage(s): {citations} for {len(result.notes)} notes"
    )


@then("the pipeline refuses to fabricate an answer")
def step_pipeline_refuses(context):
    if context.live:
        def _ok(result):
            if result is _REFUSED:
                return True
            if result is _ERROR:
                return False
            answer = str(getattr(result, "answer", ""))
            return result.grounded is True or "INSUFFICIENT_CONTEXT" in answer

        rate = _pass_rate([_ok(r) for r in context.results])
        assert rate >= _PASS_THRESHOLD, (
            f"Honest-refusal pass rate was {rate:.0%} "
            f"(need >= {_PASS_THRESHOLD:.0%})."
        )
        return

    if context.refused:
        assert context.results == []
        return
    answer = str(getattr(context.results[0], "answer", ""))
    assert "INSUFFICIENT_CONTEXT" in answer, (
        "Pipeline returned an answer instead of refusing."
    )


# ---------------------------------------------------------------------------
# Privacy scenario steps
# ---------------------------------------------------------------------------


@given("a permission controller with demo mode disabled")
def step_permission_controller(context):
    context.controller = PermissionController(privacy_config={"demo_mode": False})


@when('the agent requests approval for the "{tool}" tool')
def step_request_approval(context, tool):
    context.approval = context.controller.request_approval(
        tool, {"path": "./data/documents/notes.txt"}, reason="write file"
    )


@when('the agent tries to auto-approve "{tool}"')
def step_try_auto_approve(context, tool):
    context.controller.set_auto_approve(tool, True)


@then("the request is denied")
def step_request_denied(context):
    assert context.approval is False, "Approval was granted without explicit consent"


@then("the denial is recorded in the permission history")
def step_denial_recorded(context):
    history = context.controller.get_history()
    assert history, "No permission request was recorded"
    entry = history[-1]
    assert entry["tool"] == "file_write"
    assert entry["approved"] is False
    assert entry["auto"] is False


@then('"{tool}" still requires explicit approval')
def step_still_requires_approval(context, tool):
    assert context.controller.requires_approval(tool) is True


@then('a fresh "{tool}" request is denied again')
def step_fresh_request_denied(context, tool):
    approved = context.controller.request_approval(tool, {"path": "./x.txt"}, reason="retry")
    assert approved is False, (
        f"set_auto_approve bypassed the consent gate for dangerous tool {tool}"
    )


@given("a guarded socket that rejects non-loopback connections")
def step_guarded_socket(context):
    context.attempted = []

    class GuardedSocket(socket_module.socket):
        def connect(self, address):
            host = address[0]
            if host not in _LOOPBACK_HOSTS:
                raise AssertionError(f"Non-loopback connection attempt: {address!r}")
            context.attempted.append(address)
            return super().connect(address)

    context.GuardedSocket = GuardedSocket
    context._original_socket = socket_module.socket
    socket_module.socket = GuardedSocket


@when('the RAG pipeline answers "{question}"')
def step_rag_pipeline_answers(context, question):
    context.question = question

    # Negative control: the guard must reject a cloud address outright.
    try:
        context.GuardedSocket().connect(("8.8.8.8", 80))
        raise AssertionError("GuardedSocket did not reject a non-loopback connection")
    except AssertionError as exc:
        assert "Non-loopback" in str(exc)

    responses = [
        _query_response("Where is the Eiffel Tower located?"),
        _notes_response('["The Eiffel Tower is located in Paris."]'),
        _answer_response("The Eiffel Tower is located in Paris, France. [1]"),
    ]
    with patch.object(dspy_runtime.BUNKER_LM, "forward", side_effect=responses):
        context.result = context.rag(question=question)


@then("every network connection attempted targets loopback only")
def step_loopback_only(context):
    for address in context.attempted:
        assert address[0] in _LOOPBACK_HOSTS, f"Non-loopback attempt recorded: {address!r}"


@then("the default inference backend targets localhost")
def step_backend_targets_localhost(context):
    api_base = dspy_runtime.BUNKER_LM.kwargs.get("api_base", "")
    assert re.match(r"https?://(localhost|127\.0\.0\.1|::1)(:\d+)?", api_base), (
        f"Default LM api_base is not loopback-only: {api_base!r}"
    )


@then("the answer is produced from local context only")
def step_answer_from_local_context(context):
    result = context.result
    assert result.grounded is True, "Answer was not grounded in the retrieved passage"
    assert extract_citations(result.answer), "Answer does not cite the local passage"
    assert "Eiffel" in result.answer
    assert result.notes and "Eiffel Tower" in result.notes[0]
