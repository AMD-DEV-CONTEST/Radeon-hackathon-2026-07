from pathlib import Path
from types import SimpleNamespace

import pytest

from radeonvla.publish_hf import (
    _assert_repo_namespaces,
    _card_body,
    _model_evidence_uploads,
    _read_release_card,
    _validate_pairs,
    parse_args,
)


def test_public_publish_requires_explicit_confirmation() -> None:
    args = parse_args(
        [
            "--dataset-repo",
            "visiobot/data",
            "--dataset-root",
            "datasets/data",
            "--public",
        ]
    )
    with pytest.raises(ValueError, match="confirm-public-release"):
        _validate_pairs(args)


def test_publish_pairs_and_namespace_are_fail_closed() -> None:
    args = parse_args(["--model-repo", "visiobot/model", "--policy-path", "model", "--private"])
    _validate_pairs(args)
    identity = {"name": "owner", "orgs": [{"name": "visiobot"}]}
    _assert_repo_namespaces(identity, ["owner/data", "visiobot/model"])
    with pytest.raises(PermissionError, match="other"):
        _assert_repo_namespaces(identity, ["other/data"])


def test_card_body_preserves_only_markdown_body() -> None:
    markdown = "---\nlicense: cc-by-4.0\n---\n\n# Dataset\n"
    assert _card_body(markdown) == "\n# Dataset\n"


def test_pre_release_card_requires_explicit_draft_mode(tmp_path: Path) -> None:
    card = tmp_path / "README.md"
    card.write_text("> Release status: pre-release.\n", encoding="utf-8")
    with pytest.raises(ValueError, match="pre-release"):
        _read_release_card(card, allow_draft=False)
    assert _read_release_card(card, allow_draft=True).startswith("> Release status")


def test_publish_requires_at_least_one_complete_pair() -> None:
    args = SimpleNamespace(
        dataset_repo=None,
        dataset_root=None,
        model_repo=None,
        policy_path=None,
        private=True,
        confirm_public_release=False,
    )
    with pytest.raises(ValueError, match="Provide a dataset pair"):
        _validate_pairs(args)


def test_model_evidence_is_repeatable() -> None:
    args = parse_args(
        [
            "--model-repo",
            "visiobot/model",
            "--policy-path",
            "model",
            "--model-evidence",
            "first.json",
            "--model-evidence",
            "second.json",
        ]
    )
    assert args.model_evidence == [Path("first.json"), Path("second.json")]


def test_model_evidence_is_validated_before_upload(tmp_path: Path) -> None:
    first = tmp_path / "first" / "evaluation.json"
    second = tmp_path / "second" / "evaluation.json"
    first.parent.mkdir()
    second.parent.mkdir()
    first.write_text("{}", encoding="utf-8")
    second.write_text("{}", encoding="utf-8")
    assert _model_evidence_uploads([first]) == [(first, "evaluation/evaluation.json")]
    with pytest.raises(ValueError, match="Duplicate"):
        _model_evidence_uploads([first, second])
    with pytest.raises(FileNotFoundError, match="missing.json"):
        _model_evidence_uploads([tmp_path / "missing.json"])
