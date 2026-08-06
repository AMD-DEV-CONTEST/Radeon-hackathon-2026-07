"""DSPy multi-hop RAG over Bunker's local ChromaDB vector store.

The module follows the official DSPy multi-hop search tutorial
(https://dspy.ai/tutorials/multihop_search/): a `generate_query`
ChainOfThought and an `append_notes` ChainOfThought alternate inside a
loop of `num_hops` iterations, each hop calling the local ChromaDB search
wrapper. The accumulated notes are passed to a final `GroundedAnswer`
ChainOfThought (https://dspy.ai/tutorials/rag/).

All retrieval stays local: the search function below queries Bunker's
`VectorStore` (ChromaDB with telemetry disabled), never a cloud service.
"""

import logging
import re
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

import dspy

logger = logging.getLogger(__name__)

DEFAULT_ARTIFACT_PATH = "artifacts/bunker_rag_mipro.json"


class BunkerGroundingError(Exception):
    """Raised when the final answer keeps citing passages that are not in context.

    Mirrors the hard-stop behaviour of ``dspy.Assert`` (which no longer exists
    in dspy 3.x): a hard grounding violation that persists after the configured
    number of backtracks halts the pipeline instead of returning bad output.
    """


def extract_citations(answer: str) -> List[int]:
    """Return the ``[pid]`` passage numbers cited in an answer, in order."""
    if not answer:
        return []
    return [int(pid) for pid in re.findall(r"\[(\d+)\]", answer)]


def make_chromadb_search(vector_store: Any) -> Callable[[str, int], List[str]]:
    """Expose Bunker's ChromaDB VectorStore as a DSPy-compatible search function.

    The multi-hop tutorial plugs plain Python retrieval code directly into
    the module (https://dspy.ai/tutorials/multihop_search/): a callable
    ``search(query: str, k: int) -> list[str]``. This wrapper adapts
    ``VectorStore.search(query, k=...)`` (which returns a list of dicts with
    ``"text"``/``"metadata"``/``"distance"``) into that plain-string shape.

    Args:
        vector_store: A VectorStore-like object exposing ``search(query, k=...)``.

    Returns:
        A ``search(query: str, k: int) -> List[str]`` callable for DSPy.
    """
    def search(query: str, k: int) -> List[str]:
        results = vector_store.search(query, k=k) if vector_store else []
        passages: List[str] = []
        for result in results or []:
            if isinstance(result, dict):
                text = result.get("text", "")
            else:
                text = getattr(result, "text", "") or getattr(result, "long_text", "")
            if text:
                passages.append(str(text))
        return passages
    return search


class GenerateQuery(dspy.Signature):
    """Given a claim and notes gathered so far, generate the next search query to find more evidence."""

    claim: str = dspy.InputField(desc="The user's question.")
    notes: str = dspy.InputField(desc="Evidence gathered so far, as a numbered list.")
    query: str = dspy.OutputField(desc="A specific search query for the next retrieval hop.")


class AppendNotes(dspy.Signature):
    """Given a claim, notes, and new search results, extract new notes from the results."""

    claim: str = dspy.InputField(desc="The user's question.")
    notes: str = dspy.InputField(desc="Evidence gathered so far, as a numbered list.")
    context: str = dspy.InputField(desc="Newly retrieved passages, as a numbered list.")
    new_notes: list[str] = dspy.OutputField(desc="New facts extracted from the new passages.")


class GroundedAnswer(dspy.Signature):
    """Answer questions with short factoid answers using only the provided context.

    Cite the passages you rely on in the answer using their [pid] numbers from
    the numbered context list, e.g. "[1]" for the first passage."""

    context: str = dspy.InputField(desc="Evidence notes accumulated across retrieval hops, as a numbered list.")
    question: str = dspy.InputField(desc="The user's question.")
    answer: str = dspy.OutputField(desc="A factual answer grounded in the context, citing supporting passages as [pid] numbers.")


class BunkerMultiHopRAG(dspy.Module):
    """Multi-hop retrieval-augmented generation over Bunker's local ChromaDB store.

    Mirrors the Hop module from https://dspy.ai/tutorials/multihop_search/:
    each hop generates a targeted query, retrieves ``num_docs`` passages from
    the local vector store, and appends new notes. After ``num_hops`` hops the
    accumulated notes are grounded into a final answer.

    The final answer is validated for grounding. Because dspy 3.x removed the
    ``dspy.Assert``/``dspy.Suggest`` primitives (see
    https://dspy.ai/learn/programming/7-assertions for the original semantics),
    the equivalent backtrack-and-retry behaviour is implemented natively here:

    * Hard check (``dspy.Assert`` equivalent): every ``[pid]`` cited in the
      answer must exist in the retrieved context. On violation, the answer
      module is re-invoked with a feedback message. If the violation persists
      after ``max_backtracks`` retries, ``BunkerGroundingError`` is raised.
    * Soft check (``dspy.Suggest`` equivalent): the answer is recommended to
      cite at least one passage. Violations retry with feedback but, after
      ``max_backtracks``, the best effort is returned without raising.

    Args:
        search: A ``search(query: str, k: int) -> list[str]`` callable
            (e.g. ``make_chromadb_search(vector_store)``).
        num_hops: Number of retrieval hops (default from RAGConfig).
        num_docs: Passages retrieved per hop (default from RAGConfig).
        max_backtracks: Max retries of the answer module after a grounding
            violation (default from RAGConfig).
    """

    def __init__(
        self,
        search: Optional[Callable[[str, int], List[str]]] = None,
        num_hops: int = 3,
        num_docs: int = 5,
        max_backtracks: int = 2,
    ):
        super().__init__()
        self.search = search
        self.num_hops = num_hops
        self.num_docs = num_docs
        self.max_backtracks = max_backtracks
        self.generate_query = dspy.ChainOfThought(GenerateQuery)
        self.append_notes = dspy.ChainOfThought(AppendNotes)
        self.answer_grounded = dspy.ChainOfThought(GroundedAnswer)

    @staticmethod
    def _numbered_notes(notes: List[str], feedback: Optional[str]) -> str:
        context = "\n".join(f"[{i}] {note}" for i, note in enumerate(notes, 1))
        if feedback:
            context += f"\n\n[feedback] {feedback}"
        return context

    def _grounding_feedback(self, invalid: List[int], num_notes: int) -> str:
        return (
            "Your previous answer cited passage [pid] numbers "
            f"{invalid} that are NOT in the context. Cite only existing passage "
            f"numbers [1] through [{num_notes}]."
        )

    def _presence_feedback(self) -> str:
        return (
            "Your previous answer did not cite any passages. Cite the passages "
            "you rely on using their [pid] numbers, e.g. [1]."
        )

    def _answer_with_grounding(self, question: str, notes: List[str], feedback: Optional[str]) -> dspy.Prediction:
        """Run the grounded answer module, passing retry feedback through the context."""
        return self.answer_grounded(
            question=question,
            context=self._numbered_notes(notes, feedback),
        )

    def forward(self, question: str) -> dspy.Prediction:
        notes: List[str] = []
        queries: List[str] = []
        contexts: List[List[str]] = []

        for _ in range(self.num_hops):
            query = self.generate_query(claim=question, notes=notes).query
            queries.append(query)
            context = self.search(query, k=self.num_docs) if self.search else []
            contexts.append(context)
            prediction = self.append_notes(claim=question, notes=notes, context=context)
            notes.extend(prediction.new_notes)

        # Graceful degradation: when no passages were retrieved at all, refuse
        # instead of letting the answer module hallucinate from an empty context.
        if not any(contexts):
            logger.warning(
                "No passages retrieved across %s hop(s); returning INSUFFICIENT_CONTEXT.",
                self.num_hops,
            )
            return dspy.Prediction(
                answer="INSUFFICIENT_CONTEXT",
                notes=notes,
                queries=queries,
                contexts=contexts,
                grounded=False,
                backtracks=0,
                citation_count=0,
            )

        # Grounding assertion with backtrack-and-retry (native dspy.Assert/Suggest
        # equivalents, since dspy 3.x removed those primitives).
        feedback: Optional[str] = None
        backtracks = 0
        grounded = False
        citations: List[int] = []
        answer = ""

        for attempt in range(self.max_backtracks + 1):
            prediction = self._answer_with_grounding(question=question, notes=notes, feedback=feedback)
            answer = prediction.answer
            citations = extract_citations(answer)
            invalid = [pid for pid in citations if pid < 1 or pid > len(notes)]

            if invalid:
                # Hard violation: cited passage does not exist in context.
                feedback = self._grounding_feedback(invalid, len(notes))
                hard_fail = True
            elif not citations:
                # Soft violation: no citations recommended.
                feedback = self._presence_feedback()
                hard_fail = False
            else:
                grounded = True
                hard_fail = False
                break
            if attempt < self.max_backtracks:
                backtracks += 1

        if not grounded:
            if hard_fail:
                raise BunkerGroundingError(
                    f"Answer still cites passages not present in the context after "
                    f"{self.max_backtracks} backtrack(s)."
                )
            logger.warning(
                "Answer cites no passages after %s backtrack(s); returning best effort.",
                self.max_backtracks,
            )

        return dspy.Prediction(
            answer=answer,
            notes=notes,
            queries=queries,
            contexts=contexts,
            grounded=grounded,
            backtracks=backtracks,
            citation_count=len(citations),
        )


def load_bunker_rag_program(
    search: Optional[Callable[[str, int], List[str]]] = None,
    num_hops: int = 3,
    num_docs: int = 5,
    max_backtracks: int = 2,
    artifact_path: str = DEFAULT_ARTIFACT_PATH,
) -> BunkerMultiHopRAG:
    """Build an uncompiled BunkerMultiHopRAG and apply a compiled artifact if present.

    Called at app boot. The optimizer never runs at inference time: this only
    loads the state-only JSON artifact produced by scripts/compile_bunker.py
    (https://dspy.ai/tutorials/saving/). When no artifact exists, the
    uncompiled program is returned with a warning.

    Args:
        search: Optional ``search(query, k)`` callable for retrieval.
        num_hops: Number of retrieval hops.
        num_docs: Passages retrieved per hop.
        max_backtracks: Max grounding retries.
        artifact_path: Path to the compiled state JSON to load.
    """
    program = BunkerMultiHopRAG(
        search=search,
        num_hops=num_hops,
        num_docs=num_docs,
        max_backtracks=max_backtracks,
    )
    path = Path(artifact_path)
    if path.is_file():
        logger.info("Loading compiled RAG artifact from %s", path)
        program.load(str(path))  # Module.load is in-place and returns None
    else:
        logger.warning(
            "No compiled RAG artifact at %s; using uncompiled program.", path
        )
    return program
