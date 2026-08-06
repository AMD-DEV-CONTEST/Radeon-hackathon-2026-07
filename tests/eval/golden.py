"""Golden devset for the DSPy RAG quality-regression harness.

Each ``dspy.Example`` carries ``context``, ``question`` and
``expected_answer``. Only ``question`` is marked as an input: the program
(``BunkerMultiHopRAG``) is invoked with just the question, while ``context``
and ``expected_answer`` stay as metadata for ``grounded_metric``.
"""

import dspy

BUNKER_GOLDEN = [
    dspy.Example(
        context=(
            "[1] The Eiffel Tower is an iron lattice tower on the Champ de Mars "
            "in Paris, France.\n"
            "[2] Paris is the capital of France."
        ),
        question="Where is the Eiffel Tower located?",
        expected_answer="Paris",
    ).with_inputs("question"),
    dspy.Example(
        context=(
            "[1] Paris is the capital and largest city of France.\n"
            "[2] The River Seine runs through the centre of Paris."
        ),
        question="What is the capital of France?",
        expected_answer="Paris",
    ).with_inputs("question"),
    dspy.Example(
        context=(
            "[1] Qwen3 is an open-source family of language models released by "
            "Alibaba.\n"
            "[2] Qwen3-0.6B is a small 0.6-billion-parameter model."
        ),
        question="Which company released the Qwen3 family of language models?",
        expected_answer="Alibaba",
    ).with_inputs("question"),
]
