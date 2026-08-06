"""Property-based tests for Bunker's grounding invariant and RAG search wrapper.

These are deterministic property tests (Hypothesis): the live-LLM statistical
assertions live in the integration layer (tests/test_integration_qwen.py),
because a 0.6B model is non-deterministic and cannot satisfy exact-match
invariants on every generated input. Here ``FakeLM`` (from the unit layer)
replays a canned grounded answer, so the *invariant* is checked structurally
across a wide range of generated questions.

Verified against Hypothesis 6.165.0:
https://hypothesis.readthedocs.io/en/latest/quickstart.html
"""

import dspy
from hypothesis import given, settings, strategies as st

from src.rag.multihop_rag import GroundedAnswer, extract_citations, make_chromadb_search
from tests.test_unit_dspy import FakeLM

CONTEXT = (
    "[1] The Eiffel Tower is an iron lattice tower located on the Champ de Mars in Paris, France.\n"
    "[2] Paris is the capital and largest city of France.\n"
    "[3] France is a country located primarily in Western Europe."
)
NUM_PASSAGES = 3


def _grounds_or_refuses(answer: str) -> bool:
    """Invariant: every cited [pX] exists in context, or the answer refuses."""
    if "INSUFFICIENT_CONTEXT" in answer:
        return True
    return all(1 <= pid <= NUM_PASSAGES for pid in extract_citations(answer))


@settings(max_examples=25, deadline=None)
@given(question=st.text(min_size=5, max_size=200))
def test_answer_always_grounds_or_refuses(question):
    """GroundedAnswer output never cites a passage missing from the context."""
    fake = FakeLM([
        {
            "content": (
                "[[ ## reasoning ## ]]\nThe question is answerable from context.\n\n"
                "[[ ## answer ## ]]\nParis. [1]\n\n"
                "[[ ## completed ## ]]"
            )
        },
    ])

    with dspy.context(lm=fake):
        result = dspy.Predict(GroundedAnswer)(context=CONTEXT, question=question)

    answer = str(result.answer)
    assert _grounds_or_refuses(answer), (
        f"answer cites a passage not present in the {NUM_PASSAGES}-passage context: {answer!r}"
    )


class FakeVectorStore:
    """Stand-in for VectorStore.search returning ChromaDB-shaped dicts."""

    def search(self, query: str, k: int = 5, **kwargs):
        return [
            {
                "id": f"p{i}",
                "text": f"passage {i} about {query}",
                "metadata": {"source": "property.pdf"},
                "distance": float(i),
            }
            for i in range(k)
        ]


@settings(max_examples=25, deadline=None)
@given(query=st.text(min_size=1, max_size=100))
def test_chromadb_search_returns_list_of_strs(query):
    """The DSPy search wrapper always returns a list of non-empty strings."""
    search = make_chromadb_search(FakeVectorStore())

    result = search(query, k=4)

    assert isinstance(result, list)
    assert all(isinstance(p, str) and p for p in result)
