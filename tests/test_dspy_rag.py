import types
from unittest.mock import patch

import pytest

from src import dspy_runtime
from src.rag.multihop_rag import (
    AppendNotes,
    BunkerGroundingError,
    BunkerMultiHopRAG,
    GenerateQuery,
    GroundedAnswer,
    extract_citations,
    make_chromadb_search,
)


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


class FakeVectorStore:
    """Stand-in for VectorStore.search returning ChromaDB-shaped dicts per query."""

    def __init__(self):
        self.calls = []  # (query, k)

    def search(self, query: str, k: int = 5, **kwargs):
        self.calls.append((query, k))
        q = query.lower()
        if "eiffel" in q:
            return [{
                "id": "p1",
                "text": "The Eiffel Tower is located in Paris, France.",
                "metadata": {"source": "travel.pdf"},
                "distance": 0.1,
            }]
        if "capital" in q or "paris" in q:
            return [{
                "id": "p2",
                "text": "Paris is the capital of France.",
                "metadata": {"source": "geography.pdf"},
                "distance": 0.2,
            }]
        return []


# ---------------------------------------------------------------------------
# Search wrapper
# ---------------------------------------------------------------------------


def test_chromadb_search_wrapper_returns_plain_passages():
    """make_chromadb_search adapts VectorStore results into list[str] passages."""
    fake = FakeVectorStore()
    search = make_chromadb_search(fake)

    passages = search("Where is the Eiffel Tower?", k=2)

    assert passages == ["The Eiffel Tower is located in Paris, France."]
    assert fake.calls == [("Where is the Eiffel Tower?", 2)]


def test_chromadb_search_wrapper_handles_empty_results():
    search = make_chromadb_search(FakeVectorStore())
    assert search("nothing matches", k=3) == []


def test_extract_citations():
    assert extract_citations("Paris is in France. [1] and [3]") == [1, 3]
    assert extract_citations("no citations here") == []
    assert extract_citations("") == []


# ---------------------------------------------------------------------------
# Multi-hop RAG module
# ---------------------------------------------------------------------------


def test_multihop_rag_signatures():
    """The RAG signatures declare the expected input/output fields."""
    assert set(GenerateQuery.input_fields) == {"claim", "notes"}
    assert set(GenerateQuery.output_fields) == {"query"}
    assert set(AppendNotes.input_fields) == {"claim", "notes", "context"}
    assert set(AppendNotes.output_fields) == {"new_notes"}
    assert set(GroundedAnswer.input_fields) == {"context", "question"}
    assert set(GroundedAnswer.output_fields) == {"answer"}


def test_multihop_rag_retrieves_from_two_distinct_passages():
    """A two-part question gathers facts across two hops from two distinct passages."""
    fake = FakeVectorStore()
    rag = BunkerMultiHopRAG(
        search=make_chromadb_search(fake),
        num_hops=2,
        num_docs=2,
    )

    responses = [
        _query_response("Where is the Eiffel Tower located?"),
        _notes_response('["The Eiffel Tower is located in Paris."]'),
        _query_response("What is the capital of France?"),
        _notes_response('["Paris is the capital of France."]'),
        _answer_response("The Eiffel Tower is in Paris, the capital of France. [1] [2]"),
    ]
    with patch.object(dspy_runtime.BUNKER_LM, "forward", side_effect=responses):
        result = rag(question="Where is the Eiffel Tower and what country is it in?")

    assert len(result.queries) == 2
    assert len(result.notes) == 2
    # Both retrieval hops hit the ChromaDB wrapper with num_docs.
    assert fake.calls == [
        ("Where is the Eiffel Tower located?", 2),
        ("What is the capital of France?", 2),
    ]
    # Facts were drawn from at least two distinct passages.
    distinct = {p for ctx in result.contexts for p in ctx}
    assert len(distinct) >= 2
    assert "The Eiffel Tower is located in Paris, France." in distinct
    assert "Paris is the capital of France." in distinct
    assert "Eiffel" in result.answer and "France" in result.answer
    # Both citations [1] and [2] exist in the two-note context: no backtracking.
    assert result.grounded is True
    assert result.backtracks == 0
    assert result.citation_count == 2


# ---------------------------------------------------------------------------
# Grounding assertions (native dspy.Assert / dspy.Suggest equivalents)
# ---------------------------------------------------------------------------


def _one_hop_rag(max_backtracks: int):
    return BunkerMultiHopRAG(
        search=make_chromadb_search(FakeVectorStore()),
        num_hops=1,
        num_docs=1,
        max_backtracks=max_backtracks,
    )


def test_grounding_assertion_retries_on_fake_pid():
    """A cited [pid] missing from context triggers a hard retry with feedback."""
    rag = _one_hop_rag(max_backtracks=2)

    responses = [
        _query_response("Where is the Eiffel Tower located?"),
        _notes_response('["The Eiffel Tower is located in Paris."]'),
        _answer_response("The Eiffel Tower is in Berlin. [9]"),
        _answer_response("The Eiffel Tower is in Paris. [1]"),
    ]
    with patch.object(dspy_runtime.BUNKER_LM, "forward", side_effect=responses) as mock_lm:
        result = rag(question="Where is the Eiffel Tower?")

    assert result.answer == "The Eiffel Tower is in Paris. [1]"
    assert result.grounded is True
    assert result.backtracks == 1
    assert result.citation_count == 1
    # query + notes + first (bad) answer + retried (good) answer
    assert mock_lm.call_count == 4


def test_grounding_assertion_hard_fails_after_backtracks():
    """Persistent fake [pid] raises BunkerGroundingError after max_backtracks."""
    rag = _one_hop_rag(max_backtracks=1)

    responses = [
        _query_response("Where is the Eiffel Tower located?"),
        _notes_response('["The Eiffel Tower is located in Paris."]'),
        _answer_response("The Eiffel Tower is in Berlin. [9]"),
        _answer_response("The Eiffel Tower is in Berlin. [9]"),
    ]
    with patch.object(dspy_runtime.BUNKER_LM, "forward", side_effect=responses):
        with pytest.raises(BunkerGroundingError):
            rag(question="Where is the Eiffel Tower?")


def test_suggest_no_citation_returns_best_effort():
    """Missing citations retry softly but return the best effort without raising."""
    rag = _one_hop_rag(max_backtracks=1)

    responses = [
        _query_response("Where is the Eiffel Tower located?"),
        _notes_response('["The Eiffel Tower is located in Paris."]'),
        _answer_response("The Eiffel Tower is in Paris."),
        _answer_response("The Eiffel Tower is in Paris."),
    ]
    with patch.object(dspy_runtime.BUNKER_LM, "forward", side_effect=responses):
        result = rag(question="Where is the Eiffel Tower?")

    assert result.answer == "The Eiffel Tower is in Paris."
    assert result.grounded is False
    assert result.backtracks == 1
    assert result.citation_count == 0
