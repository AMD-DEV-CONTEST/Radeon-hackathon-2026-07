from pathlib import Path

import pytest

from radeon_home.mjcf_reference import resolve_reference_root


def test_resolve_explicit_reference_root(tmp_path: Path) -> None:
    package = tmp_path / "franka_fruit_pick"
    package.mkdir()
    (package / "grasp_demo.py").write_text("# fixture\n", encoding="utf-8")
    assert resolve_reference_root(tmp_path) == tmp_path.resolve()


def test_missing_reference_root_has_actionable_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "radeon_home.mjcf_reference._reference_candidates",
        lambda _explicit: [tmp_path],
    )
    with pytest.raises(FileNotFoundError, match="--reference-root"):
        resolve_reference_root(tmp_path)
