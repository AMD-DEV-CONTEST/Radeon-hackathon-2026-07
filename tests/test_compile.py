import json
from pathlib import Path

import pytest

from src.rag.multihop_rag import BunkerMultiHopRAG, load_bunker_rag_program
from scripts.compile_bunker import load_trainset

FIXTURES = Path(__file__).parent / "fixtures"
DUMMY_ARTIFACT = FIXTURES / "bunker_rag_dummy.json"


def test_loads_dummy_artifact_and_applies_demos():
    """Loading the saved state artifact populates each predictor's demos."""
    program = BunkerMultiHopRAG(search=None, num_hops=1, num_docs=1, max_backtracks=2)
    assert DUMMY_ARTIFACT.is_file()

    program.load(str(DUMMY_ARTIFACT))

    demo_counts = [len(p.demos) for p in program.predictors()]
    assert demo_counts and all(count > 0 for count in demo_counts)


def test_load_bunker_rag_program_applies_artifact(tmp_path):
    """The boot helper loads a compiled artifact into an uncompiled program."""
    artifact = tmp_path / "bunker_rag_mipro.json"
    source = BunkerMultiHopRAG(search=None, num_hops=1, num_docs=1)
    source.generate_query.predict.demos = [
        {"claim": "q", "notes": [], "query": "qr"}
    ]
    source.save(str(artifact))

    program = load_bunker_rag_program(
        num_hops=1, num_docs=1, max_backtracks=2, artifact_path=str(artifact)
    )

    assert len(program.predictors()[0].demos) == 1
    assert program.generate_query.predict.demos[0]["query"] == "qr"


def test_load_bunker_rag_program_falls_back_without_artifact(tmp_path):
    """Missing artifact returns the uncompiled program (no load applied)."""
    program = load_bunker_rag_program(
        num_hops=2,
        num_docs=3,
        max_backtracks=1,
        artifact_path=str(tmp_path / "missing.json"),
    )

    assert program.num_hops == 2
    assert program.num_docs == 3
    assert all(len(p.demos) == 0 for p in program.predictors())


def test_load_trainset_parses_jsonl(tmp_path):
    """load_trainset reads question/answer pairs with optional context."""
    path = tmp_path / "bunker_train.jsonl"
    path.write_text(
        json.dumps({"question": "Q1", "answer": "A1", "context": "C1"}) + "\n"
        + json.dumps({"question": "Q2", "answer": "A2"}) + "\n",
        encoding="utf-8",
    )

    trainset = load_trainset(path)

    assert len(trainset) == 2
    assert trainset[0].question == "Q1"
    assert trainset[0].answer == "A1"
    assert trainset[0].context == "C1"
    assert trainset[1].context == ""
    assert set(trainset[0].inputs().keys()) == {"question"}


def test_load_trainset_requires_file(tmp_path):
    """Missing training data stops compilation instead of generating synthetic data."""
    with pytest.raises(FileNotFoundError):
        load_trainset(tmp_path / "missing.jsonl")
