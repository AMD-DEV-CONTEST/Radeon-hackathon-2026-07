import re
from pathlib import Path

import pdfplumber
import pytest
from PIL import Image
from pypdf import PdfReader

ROOT = Path(__file__).resolve().parents[1]
CONTEST_PREFIX = "submissions/track1-silent-vision/"
MARKDOWN_LINK = re.compile(r"\[[^\]]*\]\(([^)]+)\)")
SCRIPT_REFERENCE = re.compile(r"(?<![\w/])(scripts/[A-Za-z0-9_.-]+)")
POSTER_SCENE_PATHS = (
    ROOT / "submission/assets/poster/post-surgery.png",
    ROOT / "submission/assets/poster/rehabilitation.png",
    ROOT / "submission/assets/poster/accessible-communication.png",
    ROOT / "submission/assets/poster/silent-control-input.png",
)


def _relative_markdown_links(path: Path) -> list[Path]:
    targets: list[Path] = []
    for raw_target in MARKDOWN_LINK.findall(path.read_text(encoding="utf-8")):
        target = raw_target.strip("<>").split("#", maxsplit=1)[0]
        if not target or "://" in target or target.startswith("mailto:"):
            continue
        targets.append(path.parent / target)
    return targets


def _pdf_text(path: Path) -> str:
    return "\n".join(page.extract_text() or "" for page in PdfReader(path).pages)


@pytest.mark.parametrize("path", [ROOT / "README.md", ROOT / "submission/README.md"])
def test_public_markdown_links_resolve(path):
    links = _relative_markdown_links(path)

    assert links
    assert all(link.exists() for link in links)


def test_readme_references_existing_scripts():
    text = (ROOT / "README.md").read_text(encoding="utf-8")
    scripts = {ROOT / match for match in SCRIPT_REFERENCE.findall(text)}

    assert scripts
    assert all(script.is_file() for script in scripts)


def test_amd_runbook_requires_unrelated_clips_in_both_languages():
    text = (ROOT / "docs/runbooks/amd-real-mode.md").read_text(encoding="utf-8")

    assert "15 unrelated clips spanning both zh and en" in text


def test_submission_copy_avoids_unverified_marketing_claims():
    paths = [
        ROOT / "README.md",
        *ROOT.joinpath("submission").glob("*.md"),
        *ROOT.joinpath("docs/submission").glob("*.md"),
    ]
    banned = {
        "revolutionary",
        "game-changing",
        "cutting-edge",
        "next-generation",
        "harness the power of ai",
    }
    combined = "\n".join(
        path.read_text(encoding="utf-8").lower() for path in paths if path.exists()
    )

    assert not any(phrase in combined for phrase in banned)


def test_public_copy_describes_the_four_phrase_bilingual_catalog():
    """Fails if public copy regresses to the former two-Chinese-phrase scope."""
    paths = [
        ROOT / "README.md",
        ROOT / "submission/README.md",
        ROOT / "submission/demo-video-script.md",
        ROOT / "submission/pull-request-description.md",
    ]
    combined = "\n".join(path.read_text(encoding="utf-8").lower() for path in paths)

    assert "你好，请帮我打开灯" in combined
    assert "你吃饭了吗？" in combined
    assert "hello, please turn on the light." in combined
    assert "have you eaten?" in combined
    assert "four-phrase bilingual catalog" in combined
    assert "user selects the language" in combined
    assert "selected-language softmax" in combined
    assert "two chinese phrases" not in combined


def test_pr_description_contest_paths_resolve_to_public_materials():
    text = (ROOT / "submission/pull-request-description.md").read_text(
        encoding="utf-8"
    )
    relative_paths = {
        match
        for match in re.findall(rf"`{re.escape(CONTEST_PREFIX)}([^`]+)`", text)
    }

    assert relative_paths
    assert all(ROOT.joinpath(path).exists() for path in relative_paths)


def test_profile_and_poster_pdf_structure():
    profile_path = ROOT / "submission/Silent-Vision-Project-Profile.pdf"
    poster_path = ROOT / "submission/Silent-Vision-Poster.pdf"
    profile = PdfReader(profile_path)
    poster = PdfReader(poster_path)

    assert len(profile.pages) == 6
    assert len(poster.pages) == 1
    assert profile.metadata.title == "Silent Vision Project Profile"
    assert poster.metadata.title == "Silent Vision Poster"
    assert profile.metadata.author == poster.metadata.author == "Jixin Fang"
    assert all((page.extract_text() or "").strip() for page in profile.pages)
    assert (poster.pages[0].extract_text() or "").strip()

    profile_box = profile.pages[0].mediabox
    poster_box = poster.pages[0].mediabox
    assert float(profile_box.width) == pytest.approx(595.276, abs=0.01)
    assert float(profile_box.height) == pytest.approx(841.89, abs=0.01)
    assert float(poster_box.width) == pytest.approx(841.89, abs=0.01)
    assert float(poster_box.height) == pytest.approx(1190.55, abs=0.01)


def test_profile_assets_describe_bilingual_language_routing():
    source = (ROOT / "docs/submission/project-profile-source.md").read_text(encoding="utf-8")
    generated = _pdf_text(ROOT / "submission/Silent-Vision-Project-Profile.pdf")
    for text in (source, generated):
        assert "你好，请帮我打开灯" in text
        assert "你吃饭了吗？" in text
        assert "Hello, please turn on the light." in text
        assert "Have you eaten?" in text
        assert "user selects the language" in text.lower()
        assert "selected-language softmax" in text.lower()
        assert "no bilingual accuracy" in text.lower()


def test_poster_assets_use_the_approved_human_centered_copy():
    source = (ROOT / "docs/submission/poster-copy.md").read_text(encoding="utf-8")
    generated = _pdf_text(ROOT / "submission/Silent-Vision-Poster.pdf")
    required = {
        "SILENT VISION",
        "PERSONALIZED FIXED-PHRASE PROTOTYPE",
        "A VOICE WITHOUT SOUND.",
        "Visual communication for people who can form words but cannot speak them aloud.",
        "POST-SURGERY",
        "REHABILITATION",
        "ACCESSIBLE COMMUNICATION",
        "SILENT CONTROL INPUT",
        "Four registered phrases · Chinese + English · Exact phrase or safe UNKNOWN",
        "Camera-only · No audio capture · ROCm PyTorch on AMD Radeon",
    }
    forbidden = {"Please turn on the light.", "Have you eaten?", "directly controls"}
    for text in (source, generated):
        assert all(phrase in text for phrase in required)
        assert not any(phrase in text for phrase in forbidden)


def test_poster_uses_four_large_scene_images_instead_of_report_cards():
    with pdfplumber.open(ROOT / "submission/Silent-Vision-Poster.pdf") as pdf:
        page = pdf.pages[0]
        large_images = [
            image
            for image in page.images
            if image["width"] >= page.width * 0.45
            and image["height"] >= page.height * 0.25
        ]
    assert len(large_images) == 4


def test_poster_png_is_a_full_size_a3_render():
    with Image.open(ROOT / "submission/Silent-Vision-Poster.png") as poster:
        width, height = poster.size

        assert poster.format == "PNG"
        assert width >= 1700
        assert height >= 2400
        assert height / width == pytest.approx(2**0.5, rel=0.01)


def test_poster_scene_sources_are_repository_owned_landscape_pngs():
    for path in POSTER_SCENE_PATHS:
        assert path.is_file(), path
        with Image.open(path) as image:
            width, height = image.size
            assert image.format == "PNG"
            assert image.mode in {"RGB", "RGBA"}
            assert width >= 1400
            assert height >= 900
            assert width / height == pytest.approx(1.5, rel=0.12)
