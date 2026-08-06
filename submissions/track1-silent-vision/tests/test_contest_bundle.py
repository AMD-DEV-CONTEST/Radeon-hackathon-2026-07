import re
import subprocess
import sys
from pathlib import Path

import pytest
from pypdf import PdfReader

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.build_contest_bundle import build_bundle

MARKDOWN_LINK = re.compile(r"\[[^\]]*\]\(([^)]+)\)")
POSTER_SCENE_RELATIVE_PATHS = (
    Path("submission/assets/poster/post-surgery.png"),
    Path("submission/assets/poster/rehabilitation.png"),
    Path("submission/assets/poster/accessible-communication.png"),
    Path("submission/assets/poster/silent-control-input.png"),
)


def _public_markdown_files(bundle: Path) -> list[Path]:
    files = [bundle / "README.md"]
    files.extend(sorted(bundle.joinpath("docs").rglob("*.md")))
    files.extend(sorted(bundle.joinpath("submission").rglob("*.md")))
    return files


def _repository_relative_link_targets(markdown: Path) -> list[Path]:
    targets: list[Path] = []
    for raw_target in MARKDOWN_LINK.findall(markdown.read_text(encoding="utf-8")):
        target = raw_target.strip("<>").split("#", maxsplit=1)[0]
        if not target or "://" in target or target.startswith("mailto:"):
            continue
        targets.append((markdown.parent / target).resolve())
    return targets


def test_bundle_contains_complete_runtime_and_public_materials(tmp_path):
    target = tmp_path / "submissions" / "track1-silent-vision"

    copied = build_bundle(Path.cwd(), target)

    assert target.joinpath("backend/main.py").exists()
    assert target.joinpath("command/phrase_catalog.json").exists()
    assert target.joinpath("frontend/websocket.js").exists()
    assert target.joinpath("README.md").exists()
    assert target.joinpath("docs/runbooks/amd-real-mode.md").exists()
    assert target.joinpath("docs/submission/project-profile-source.md").exists()
    assert target.joinpath("scripts/generate_submission_assets.py").exists()
    assert target.joinpath("submission/Silent-Vision-Project-Profile.pdf").exists()
    assert target.joinpath("submission/Silent-Vision-Poster.pdf").exists()
    assert target.joinpath("submission/Silent-Vision-Poster.png").exists()
    assert all(target.joinpath(path).is_file() for path in POSTER_SCENE_RELATIVE_PATHS)
    assert target.joinpath("submission/demo-video-script.md").exists()
    assert copied


def test_bundle_rebuilds_poster_from_repository_owned_assets(tmp_path):
    target = tmp_path / "submissions" / "track1-silent-vision"
    build_bundle(Path.cwd(), target)
    rebuilt = target / "rebuilt-poster.pdf"
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "from pathlib import Path; "
                "from scripts.generate_submission_assets import build_poster_pdf; "
                "build_poster_pdf(Path('rebuilt-poster.pdf'))"
            ),
        ],
        cwd=target,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert rebuilt.is_file()
    reader = PdfReader(rebuilt)
    assert len(reader.pages) == 1
    text = reader.pages[0].extract_text() or ""
    assert "A VOICE WITHOUT SOUND." in text
    assert "PERSONALIZED FIXED-PHRASE PROTOTYPE" in text


def test_bundle_public_markdown_links_resolve_inside_bundle(tmp_path):
    target = tmp_path / "submissions" / "track1-silent-vision"

    build_bundle(Path.cwd(), target)

    bundle_root = target.resolve()
    broken: list[str] = []
    escaped: list[str] = []
    for markdown in _public_markdown_files(target):
        for link_target in _repository_relative_link_targets(markdown):
            try:
                link_target.relative_to(bundle_root)
            except ValueError:
                escaped.append(f"{markdown.relative_to(target)} -> {link_target}")
                continue
            if not link_target.exists():
                broken.append(f"{markdown.relative_to(target)} -> {link_target}")

    assert not escaped
    assert not broken


def test_bundle_carries_the_bilingual_language_routing_copy(tmp_path):
    target = tmp_path / "submissions" / "track1-silent-vision"

    build_bundle(Path.cwd(), target)

    public_copy = "\n".join(
        (target / path).read_text(encoding="utf-8")
        for path in [
            Path("README.md"),
            Path("submission/README.md"),
            Path("submission/demo-video-script.md"),
            Path("submission/pull-request-description.md"),
        ]
    ).lower()
    assert "你好，请帮我打开灯" in public_copy
    assert "你吃饭了吗？" in public_copy
    assert "hello, please turn on the light." in public_copy
    assert "have you eaten?" in public_copy
    assert "user selects the language" in public_copy
    assert "selected-language softmax" in public_copy
    assert "two chinese phrases" not in public_copy


def test_bundle_excludes_internal_and_sensitive_paths(tmp_path):
    target = tmp_path / "bundle"

    build_bundle(Path.cwd(), target)

    assert not target.joinpath("docs/superpowers").exists()
    assert not target.joinpath(".env").exists()
    assert not target.joinpath("models").exists()
    assert not target.joinpath(".git").exists()
    assert not any(path.suffix in {".pt", ".webm"} for path in target.rglob("*"))
    assert not any(path.is_symlink() for path in target.rglob("*"))


def test_bundle_rejects_an_allowlisted_symlink(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    (source / "README.md").write_text("# Safe source\n", encoding="utf-8")
    (source / "agent").mkdir()
    (source / "agent" / "linked.py").symlink_to(source / "README.md")

    with pytest.raises(ValueError, match="symlink"):
        build_bundle(source, tmp_path / "bundle")


def test_bundle_excludes_secrets_inside_an_allowlisted_directory(tmp_path):
    source = tmp_path / "source"
    secret = source / "backend" / "secrets" / "token.txt"
    secret.parent.mkdir(parents=True)
    secret.write_text("do not publish", encoding="utf-8")

    build_bundle(source, tmp_path / "bundle")

    assert not (tmp_path / "bundle" / "backend" / "secrets" / "token.txt").exists()


def test_bundle_rejects_a_symlink_destination(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    (source / "README.md").write_text("# Safe source\n", encoding="utf-8")
    destination_target = tmp_path / "destination-target"
    destination_target.mkdir()
    destination = tmp_path / "bundle"
    destination.symlink_to(destination_target, target_is_directory=True)

    with pytest.raises(ValueError, match="symlink"):
        build_bundle(source, destination)


def test_bundle_rejects_destination_beneath_a_symlinked_ancestor(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    (source / "README.md").write_text("# Safe source\n", encoding="utf-8")
    victim = tmp_path / "victim"
    victim.mkdir()
    sentinel = victim / "keep.txt"
    sentinel.write_text("keep", encoding="utf-8")
    alias = tmp_path / "alias"
    alias.symlink_to(victim, target_is_directory=True)

    with pytest.raises(ValueError, match="symlink"):
        build_bundle(source, alias / "bundle")

    assert sentinel.read_text(encoding="utf-8") == "keep"


def test_bundle_rejects_source_beneath_a_symlinked_ancestor(tmp_path):
    real_parent = tmp_path / "real-parent"
    source = real_parent / "source"
    source.mkdir(parents=True)
    (source / "README.md").write_text("# Safe source\n", encoding="utf-8")
    alias = tmp_path / "alias"
    alias.symlink_to(real_parent, target_is_directory=True)

    with pytest.raises(ValueError, match="symlink"):
        build_bundle(alias / "source", tmp_path / "bundle")


def test_bundle_rejects_a_broken_root_allowlist_symlink(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    (source / "README.md").symlink_to(source / "missing-readme.md")

    with pytest.raises(ValueError, match="symlink"):
        build_bundle(source, tmp_path / "bundle")


@pytest.mark.parametrize("destination_kind", ["same", "ancestor", "descendant"])
def test_bundle_rejects_destination_that_overlaps_source(tmp_path, destination_kind):
    source = tmp_path / "source"
    backend = source / "backend"
    backend.mkdir(parents=True)
    sentinel = backend / "keep.txt"
    sentinel.write_text("keep", encoding="utf-8")

    destinations = {
        "same": source,
        "ancestor": tmp_path,
        "descendant": backend,
    }
    with pytest.raises(ValueError, match="overlap"):
        build_bundle(source, destinations[destination_kind])

    assert sentinel.read_text(encoding="utf-8") == "keep"
