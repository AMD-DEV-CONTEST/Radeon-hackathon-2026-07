import shutil
from pathlib import Path

from scripts.security import generate_sbom

ROOT = Path(__file__).resolve().parents[1]


def test_generate_sbom_uses_determinex_artifact_names():
    out_dir = ROOT / "assurance" / "tmp" / "test_generate_sbom_branding"
    if out_dir.exists():
        shutil.rmtree(out_dir)
    try:
        paths = generate_sbom.run(output_dir=out_dir)

        assert paths["spdx"].name == "determinex-python.spdx.json"
        assert paths["cyclonedx"].name == "determinex-python.cyclonedx.json"
        assert paths["spdx"].exists()
        assert paths["cyclonedx"].exists()
    finally:
        if out_dir.exists():
            shutil.rmtree(out_dir)


def test_generate_sbom_metadata_is_determinex_branded():
    spdx = generate_sbom.generate_spdx([])
    cyclonedx = generate_sbom.generate_cyclonedx([])

    assert spdx["name"].startswith("determinex-python-")
    assert "determinex" in spdx["documentNamespace"]
    assert spdx["creationInfo"]["creators"] == ["Tool: determinex-generate-sbom"]
    assert cyclonedx["metadata"]["component"]["name"] == "determinex-python"
