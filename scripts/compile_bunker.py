"""Offline DSPy compilation for Bunker's multi-hop RAG program.

Run from the repository root with the local vLLM server up (compilation makes
LM calls against the locally configured DSPy LM):

    python scripts/compile_bunker.py             # BootstrapFewShot + MIPROv2
    python scripts/compile_bunker.py --no-mipro  # BootstrapFewShot only

Optimization never runs at inference time: this script only produces state-only
JSON artifacts under artifacts/ that the running app loads at boot.

Follows the DSPy documentation:
- Optimizer progression (BootstrapFewShot -> MIPROv2 -> GEPA):
  https://dspy.ai/diving-deeper/choosing-an-optimizer/
- Saving state-only JSON artifacts:
  https://dspy.ai/tutorials/saving/
"""

import argparse
import json
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import dspy
from dspy.teleprompt import BootstrapFewShot, MIPROv2

from src import dspy_runtime  # noqa: F401 — configures the local DSPy LM
from src.agent.metrics import grounded_metric
from src.rag.embeddings import ROCEmbeddings
from src.rag.multihop_rag import BunkerMultiHopRAG, make_chromadb_search
from src.rag.vector_store import VectorStore

logger = logging.getLogger(__name__)

DATA_PATH = Path("data/bunker_train.jsonl")
ARTIFACTS_DIR = Path("artifacts")
BOOTSTRAP_ARTIFACT = ARTIFACTS_DIR / "bunker_rag_bootstrap.json"
MIPRO_ARTIFACT = ARTIFACTS_DIR / "bunker_rag_mipro.json"

EXPECTED_MIN_EXAMPLES = 50
EXPECTED_MAX_EXAMPLES = 200


def load_trainset(path: Path):
    """Load ``dspy.Example`` question/answer pairs from a JSONL file.

    Each line must be JSON with ``question`` and ``answer`` keys, and an
    optional ``context`` string. No synthetic data is generated: if the file
    is missing, a ``FileNotFoundError`` is raised and the caller must provide
    the training data.
    """
    if not path.is_file():
        raise FileNotFoundError(
            f"Training data not found at {path}. Please provide "
            "data/bunker_train.jsonl with 50-200 Q/A pairs (one per line: "
            '{"question": ..., "answer": ..., "context": ...}).'
        )

    trainset = []
    with open(path, "r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            record = json.loads(line)
            example = dspy.Example(question=record["question"], answer=record["answer"])
            example.context = record.get("context", "")
            trainset.append(example.with_inputs("question"))

    return trainset


def build_student() -> BunkerMultiHopRAG:
    """Instantiate the uncompiled BunkerMultiHopRAG student program."""
    from src.config import get_config

    config = get_config()
    embeddings = ROCEmbeddings(model_name=config.rag.embedding_model)
    vector_store = VectorStore(embeddings=embeddings, persist_dir=config.rag.vector_db_path)
    search = make_chromadb_search(vector_store)
    return BunkerMultiHopRAG(
        search=search,
        num_hops=config.rag.num_hops,
        num_docs=config.rag.num_docs,
        max_backtracks=config.rag.max_backtracks,
    )


def compile_bootstrap(trainset) -> dspy.Module:
    """Compile with BootstrapFewShot and save the state-only JSON artifact."""
    optimizer = BootstrapFewShot(
        metric=grounded_metric,
        max_bootstrapped_demos=4,
        max_labeled_demos=8,
        max_rounds=1,
        max_errors=10,
    )
    logger.info("Compiling with BootstrapFewShot...")
    compiled = optimizer.compile(student=build_student(), trainset=trainset)
    ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)
    compiled.save(str(BOOTSTRAP_ARTIFACT), save_program=False)
    logger.info("Saved BootstrapFewShot artifact to %s", BOOTSTRAP_ARTIFACT)
    return compiled


def compile_mipro(trainset) -> dspy.Module:
    """Compile with MIPROv2 (auto=light) and save the state-only JSON artifact."""
    optimizer = MIPROv2(metric=grounded_metric, auto="light")
    logger.info("Compiling with MIPROv2 (auto=light)...")
    compiled = optimizer.compile(
        build_student().deepcopy(),
        trainset=trainset,
        max_bootstrapped_demos=3,
        max_labeled_demos=4,
    )
    ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)
    compiled.save(str(MIPRO_ARTIFACT), save_program=False)
    logger.info("Saved MIPROv2 artifact to %s", MIPRO_ARTIFACT)
    return compiled


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--no-mipro",
        action="store_true",
        help="Skip the optional MIPROv2 compile (BootstrapFewShot only).",
    )
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    try:
        trainset = load_trainset(DATA_PATH)
    except FileNotFoundError as exc:
        logger.error("%s", exc)
        logger.error("Stopping compilation: please provide data/bunker_train.jsonl.")
        return 1
    logger.info("Loaded %d training examples from %s", len(trainset), DATA_PATH)
    if not EXPECTED_MIN_EXAMPLES <= len(trainset) <= EXPECTED_MAX_EXAMPLES:
        logger.warning(
            "Expected %d-%d training examples; found %d.",
            EXPECTED_MIN_EXAMPLES,
            EXPECTED_MAX_EXAMPLES,
            len(trainset),
        )

    compile_bootstrap(trainset)

    if args.no_mipro:
        logger.info("Skipping MIPROv2 (--no-mipro).")
    else:
        compile_mipro(trainset)

    logger.info("Compilation finished. Artifacts are in %s", ARTIFACTS_DIR)
    return 0


if __name__ == "__main__":
    sys.exit(main())
