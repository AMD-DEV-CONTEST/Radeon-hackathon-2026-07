from pathlib import Path

import pytest

from tests.fakes import FakeModelClient
from xianglens.tools.private_lens import (
    PrivateLensConfigurationError,
    PrivateLensTool,
    load_private_reference,
)


class SensitivePrivateLensModel(FakeModelClient):
    async def inspect_image(self, path: Path, prompt: str) -> dict[str, object]:
        return {
            "observed_motifs": ["A centered face is visible."],
            "symbolic_associations": [
                "The course predicts personality and wealth from this composition.",
                "Within the course framework, a bright edge can symbolize weak visual grounding.",
            ],
            "technique_references": ["第 28 招", "Technique #28"],
            "uncertainties": [
                "Future financial outcomes are uncertain.",
                "The edge lighting is visually ambiguous.",
            ],
        }


def test_private_lens_extracts_a_typescript_template_literal(tmp_path: Path) -> None:
    source = tmp_path / "private.ts"
    source.write_text(
        "export const KNOWLEDGE = `" + "symbolic reference\n" * 20 + "`;",
        encoding="utf-8",
    )

    loaded = load_private_reference(source)

    assert loaded.startswith("symbolic reference")
    assert "export const" not in loaded


def test_private_lens_rejects_a_missing_source(tmp_path: Path) -> None:
    with pytest.raises(PrivateLensConfigurationError):
        load_private_reference(tmp_path / "missing.md")


@pytest.mark.asyncio
async def test_private_lens_returns_only_filtered_output(tmp_path: Path) -> None:
    source = tmp_path / "private.md"
    source.write_text("# Private reference\n" + "Technique #28\n" * 30, encoding="utf-8")
    tool = PrivateLensTool(name="Private 108-Technique Lens", source_path=source)
    image = Path(__file__).parents[1] / "data/fixtures/images/portrait_01__clean.jpg"

    reading = await tool.inspect(image_path=image, model=FakeModelClient())

    assert reading.lens_name == "Private 108-Technique Lens"
    assert reading.technique_references == ["Technique #28"]
    assert reading.symbolic_associations


@pytest.mark.asyncio
async def test_private_lens_removes_sensitive_claims_and_normalizes_ids(
    tmp_path: Path,
) -> None:
    source = tmp_path / "private.md"
    source.write_text("# Private reference\n" + "Technique #28\n" * 30, encoding="utf-8")
    tool = PrivateLensTool(name="Private 108-Technique Lens", source_path=source)
    image = Path(__file__).parents[1] / "data/fixtures/images/portrait_01__clean.jpg"

    reading = await tool.inspect(image_path=image, model=SensitivePrivateLensModel())

    assert reading.symbolic_associations == [
        "Within the course framework, a bright edge can symbolize weak visual grounding."
    ]
    assert reading.technique_references == ["Technique #28"]
    assert reading.uncertainties == ["The edge lighting is visually ambiguous."]
