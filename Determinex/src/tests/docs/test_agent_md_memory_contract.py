from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_shared_project_contract_exists_and_is_layered():
    text = read("PROJECT.md")

    assert "# Determinex Project Contract" in text  # renamed from Determinex 2026-07-02
    assert "Layer order" in text
    assert "Tool overlays" in text
    assert "Do not copy volatile campaign counts into this file" in text


def test_tool_specific_agent_docs_delegate_to_project_contract():
    for path in ("AGENTS.md", "CLAUDE.md", "GEMINI.md"):
        text = read(path)
        assert "PROJECT.md" in text
        assert "tool-specific" in text.lower()


def test_orientation_is_not_the_live_shared_contract():
    text = read("ORIENTATION.md")

    assert "PROJECT.md" in text
    assert "older orientation reference" in text
    assert "machine-readable ledger" in text


def test_ide_project_memory_companion_is_ingestible():
    text = read("docs/companions/COMPANION_DETERMINEX_PROJECT_MEMORY.md")

    assert text.startswith("---\n")
    assert "name: determinex-project-memory" in text
    assert "description: |" in text
    assert "depends:" in text
    assert text.count("\n## ") >= 8
    assert "does not prove answer correctness" in text
    assert "PROJECT.md" in text
