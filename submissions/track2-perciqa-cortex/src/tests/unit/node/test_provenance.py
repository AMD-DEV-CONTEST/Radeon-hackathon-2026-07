from pathlib import Path

from cortex.node.provenance import ProvenanceGraph


def test_add_citation_persists_and_reloads(tmp_path: Path) -> None:
    db = tmp_path / "p.sqlite"
    g = ProvenanceGraph(db)
    g.add_citation("insight-1", "finding-a")
    g.add_citation("insight-1", "finding-b")
    assert set(g.cited_by("finding-a")) == {"insight-1"}
    assert g.descendants("finding-a") == ["insight-1"]
    assert set(g.ancestors("insight-1")) == {"finding-a", "finding-b"}
    g.close()
    g2 = ProvenanceGraph(db)
    assert set(g2.cited_by("finding-a")) == {"insight-1"}
    g2.add_citation("insight-2", "insight-1")
    assert g2.graph_version > 0
    g2.close()


def test_descendants_bfs_chain(tmp_path: Path) -> None:
    g = ProvenanceGraph(tmp_path / "p.sqlite")
    for parent, child in [("a", "b"), ("b", "c"), ("c", "d")]:
        g.add_citation(child, parent)  # derived -> cited
    assert g.descendants("a") == ["b", "c", "d"]
    g.close()


def test_graph_version_increments(tmp_path: Path) -> None:
    g = ProvenanceGraph(tmp_path / "p.sqlite")
    v0 = g.graph_version
    g.add_citation("x", "y")
    assert g.graph_version == v0 + 1
