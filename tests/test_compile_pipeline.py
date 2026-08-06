"""Smoke test for the offline DSPy compilation pipeline.

``scripts/compile_bunker.py`` turns a ``data/bunker_train.jsonl`` trainset into
state-only JSON artifacts under ``artifacts/`` that the running app loads at
boot (never at inference time). This smoke test pins the build-time step so a
refactor cannot silently break artifact generation:

- ``load_trainset`` parses a tiny dummy trainset (3 examples, tests/fixtures).
- ``compile_bootstrap`` runs a real ``BootstrapFewShot`` compile with the LM
  and the vector store stubbed out (deterministic, no server on :8000 needed)
  and saves a state-only JSON artifact.
- The artifact is asserted to exist, be valid JSON, reload via ``program.load()``
  and have demos populated on every predictor.

Run with:

    pytest tests/test_compile_pipeline.py -v
"""

import json
import types
from pathlib import Path
from unittest import mock

import pytest

from src import dspy_runtime
from src.rag.multihop_rag import BunkerMultiHopRAG, make_chromadb_search
from scripts.compile_bunker import load_trainset

FIXTURES = Path(__file__).parent / "fixtures"
SMOKE_TRAINSET = FIXTURES / "bunker_train_smoke.jsonl"

QUERY_TEXT = (
    "[[ ## reasoning ## ]]\nFind the capital.\n\n"
    "[[ ## query ## ]]\nWhat is the capital of France?\n\n"
    "[[ ## completed ## ]]"
)
NOTES_TEXT = (
    "[[ ## reasoning ## ]]\nExtract the fact.\n\n"
    "[[ ## new_notes ## ]]\n[\"The Eiffel Tower is located in Paris.\"]\n\n"
    "[[ ## completed ## ]]"
)
ANSWER_TEXT = (
    "[[ ## reasoning ## ]]\nGather the grounded answer.\n\n"
    "[[ ## answer ## ]]\nThe Eiffel Tower is in Paris, the capital of France. [1]\n\n"
    "[[ ## completed ## ]]"
)
JUDGE_TEXT = (
    "[[ ## reasoning ## ]]\nThe answer is correct.\n\n"
    "[[ ## factually_correct ## ]]\nTrue\n\n"
    "[[ ## completed ## ]]"
)


def _fake_completion_response(text: str):
    """OpenAI chat-completion-shaped object for a stubbed LM.forward()."""
    message = types.SimpleNamespace(content=text, tool_calls=None)
    choice = types.SimpleNamespace(message=message, finish_reason="stop", logprobs=None)
    return types.SimpleNamespace(
        choices=[choice],
        model=dspy_runtime.BUNKER_LM.model,
        usage={"prompt_tokens": 5, "completion_tokens": 4, "total_tokens": 9},
        cache_hit=False,
        _hidden_params={},
    )


def _scripted_lm_forward(prompt=None, messages=None, **kwargs):
    """Return a parseable response for whichever predictor issued the call.

    Dispatch is content-aware (on the prompt/messages) rather than call-order
    based, so the compile loop can call the student any number of times in any
    order and every predictor still receives a valid output format.
    """
    contents = []
    if prompt:
        contents.append(prompt)
    for message in messages or []:
        contents.append(message.get("content", ""))
    prompt_text = "\n".join(contents)

    if "factually_correct" in prompt_text:
        return _fake_completion_response(JUDGE_TEXT)
    if "[[ ## new_notes ## ]]" in prompt_text:
        return _fake_completion_response(NOTES_TEXT)
    if "[[ ## answer ## ]]" in prompt_text:
        return _fake_completion_response(ANSWER_TEXT)
    return _fake_completion_response(QUERY_TEXT)


class _AlwaysRetrieves:
    """Fake store that returns passages for any query, like a loaded index."""

    def search(self, query: str, k: int = 5, **kwargs):
        return [
            {
                "id": f"p{i}",
                "text": "The Eiffel Tower is located in Paris, France.",
                "metadata": {"source": "travel.pdf"},
                "distance": 0.1,
            }
            for i in range(k)
        ]


def _always_pass_metric(example, pred, trace=None):
    """Deterministic metric: every bootstrapped example is retained."""
    return True


def _build_student():
    """A tiny uncompiled student: 1 hop, 2 docs, scripted store."""
    return BunkerMultiHopRAG(
        search=make_chromadb_search(_AlwaysRetrieves()),
        num_hops=1,
        num_docs=2,
        max_backtracks=1,
    )


def test_compile_script_runs_successfully(tmp_path, monkeypatch):
    """BootstrapFewShot compiles offline, saves valid JSON, reloads with demos."""
    trainset = load_trainset(SMOKE_TRAINSET)
    assert len(trainset) == 3

    artifact = tmp_path / "artifacts" / "bunker_rag_bootstrap_test.json"
    monkeypatch.setattr("scripts.compile_bunker.ARTIFACTS_DIR", artifact.parent)
    monkeypatch.setattr("scripts.compile_bunker.BOOTSTRAP_ARTIFACT", artifact)
    # The script builds a real vector store via build_student(); stub it out so
    # the smoke test needs no GPU/search service.
    monkeypatch.setattr(
        "scripts.compile_bunker.build_student", _build_student
    )
    # grounded_metric runs an LLM judge; pin a deterministic pass metric.
    monkeypatch.setattr(
        "scripts.compile_bunker.grounded_metric", _always_pass_metric
    )

    import scripts.compile_bunker as compile_bunker

    with mock.patch.object(
        dspy_runtime.BUNKER_LM, "forward", side_effect=_scripted_lm_forward
    ):
        compiled = compile_bunker.compile_bootstrap(trainset)

    # 1. The artifact is created on disk...
    assert artifact.is_file(), "BootstrapFewShot artifact was not written"

    # 2. ...is valid JSON...
    data = json.loads(artifact.read_text(encoding="utf-8"))
    assert data, "Artifact JSON is empty"

    # 3. ...and the compiled program already carries demos.
    assert compiled.predictors(), "Compiled program exposes no predictors"
    assert all(
        len(p.demos) > 0 for p in compiled.predictors()
    ), "BootstrapFewShot left a predictor without demos"

    # 4. A fresh program reloads the artifact via program.load() with demos.
    fresh = BunkerMultiHopRAG(search=None, num_hops=1, num_docs=2, max_backtracks=1)
    fresh.load(str(artifact))

    demo_counts = [len(p.demos) for p in fresh.predictors()]
    assert demo_counts and all(count > 0 for count in demo_counts), (
        f"Loaded program has empty demos: {demo_counts}"
    )


def test_compile_pipeline_skips_missing_trainset(tmp_path):
    """A missing trainset stops compilation instead of synthesizing data."""
    with pytest.raises(FileNotFoundError):
        load_trainset(tmp_path / "does_not_exist.jsonl")
