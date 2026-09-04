from pathlib import Path

from policyseal.evals.assets import load_eval_assets


def test_p0_eval_asset_counts_are_frozen() -> None:
    assets = load_eval_assets()

    assert len(assets.scenarios) == 30
    assert assets.scenario_status_counts == {
        "block": 8,
        "processing_failed": 2,
        "require_approval": 8,
        "safe": 12,
    }
    assert len(assets.semantic_snippets) == 60
    assert len(assets.retrieval_questions) == 20
    assert len(assets.copilot_dialogues) == 6
    assert all(len(dialogue.turns) == 3 for dialogue in assets.copilot_dialogues)


def test_goldens_are_independent_from_application_output() -> None:
    authoring_paths = [
        Path("src/policyseal/evals/assets.py"),
        Path("scripts/validate_evals.py"),
    ]
    source = "\n".join(path.read_text(encoding="utf-8") for path in authoring_paths)

    assert "policyseal.documents" not in source
    assert "policyseal.policy.evaluator" not in source
    assert "policyseal.application" not in source
    assert "policyseal.agent" not in source


def test_high_risk_snippets_never_use_unclassified_as_the_answer() -> None:
    assets = load_eval_assets()
    high_risk = [snippet for snippet in assets.semantic_snippets if snippet.risk.value == "high"]

    assert high_risk
    assert all(snippet.expected_category.value != "unclassified" for snippet in high_risk)
