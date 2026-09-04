import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from nuclear_agent.knowledge import LocalKnowledgeBase


def test_local_knowledge_retrieval_returns_ranked_citations(tmp_path):
    (tmp_path / "cesium.md").write_text(
        "# Cesium sorption\nPotassium competes with radiocesium for selective clay sites.\n"
        "Source: https://example.org/cesium\n"
    )
    (tmp_path / "unrelated.md").write_text(
        "# Unrelated\nThis document discusses weather observations.\n"
    )

    kb = LocalKnowledgeBase.from_directory(tmp_path)
    hits = kb.search("potassium competition radiocesium clay", limit=2)

    assert hits
    assert hits[0].document_id == "cesium"
    assert "Potassium competes" in hits[0].excerpt
    assert hits[0].source_path.endswith("cesium.md")
    assert hits[0].score > 0


def test_local_knowledge_retrieval_is_deterministic_and_returns_no_false_hit(tmp_path):
    (tmp_path / "transport.md").write_text("Advection dispersion groundwater transport.")
    kb = LocalKnowledgeBase.from_directory(tmp_path)

    assert kb.search("advection groundwater") == kb.search("advection groundwater")
    assert kb.search("completely absent vocabulary") == []
