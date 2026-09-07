from __future__ import annotations

from radeonvla.download_artifacts import ARTIFACTS, main


def test_public_artifact_registry_is_pinned_and_unambiguous() -> None:
    assert set(ARTIFACTS) == {
        "physical-1k",
        "physical-2k",
        "model-20k",
        "model-50k",
        "model-200k",
        "evaluation-videos",
    }
    assert len({spec.destination for spec in ARTIFACTS.values()}) == len(ARTIFACTS)
    for spec in ARTIFACTS.values():
        assert len(spec.revision) == 40
        assert set(spec.revision) <= set("0123456789abcdef")
        assert spec.repo_id.startswith("a3124371940/")


def test_dry_run_has_no_filesystem_or_network_side_effects(tmp_path, capsys) -> None:
    root = tmp_path / "release"
    result = main(
        [
            "--artifact",
            "physical-2k",
            "model-20k",
            "--root",
            str(root),
            "--dry-run",
        ]
    )
    output = capsys.readouterr().out
    assert result == 0
    assert "physical-2k" in output
    assert "model-20k" in output
    assert not root.exists()
