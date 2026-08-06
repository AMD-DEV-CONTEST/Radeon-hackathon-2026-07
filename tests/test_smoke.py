"""Offline smoke tests — no API keys or running Neo4j required.

These run in CI on every push/PR to guarantee the package at least imports
cleanly and the key logic works without external services.
"""

import importlib


def test_package_imports():
    """All core modules must import without side effects."""
    modules = [
        "config.settings",
        "utils.logger",
        "utils.exception",
        "utils.timing",
        "database.neo4j_client",
        "database.schema_loader",
        "agents.graph_agent",
        "agents.tools.cypher_generator",
        "agents.tools.cypher_templates",
        "agents.tools.db_executor",
        "agents.tools.result_interpreter",
        "audio.stt_client",
        "audio.recorder",
        "audio.player",
        "audio.vad",
        "tts.kokoro_tts",
    ]
    for mod in modules:
        importlib.import_module(mod)


def test_mock_cypher_generation():
    """The offline fallback generator should produce a valid read-only query."""
    from agents.tools.cypher_generator import _mock_generate

    cypher = _mock_generate("Keanu Reeves 演过哪些电影？", _db_schema="")
    assert "MATCH" in cypher
    assert "ACTED_IN" in cypher
    assert "Keanu Reeves" in cypher
    # Safety: never allow write clauses in generated queries.
    assert "CREATE" not in cypher
    assert "DELETE" not in cypher
    assert "MERGE" not in cypher


def test_mock_cypher_generation_director():
    """A director question should resolve to a DIRECTED pattern."""
    from agents.tools.cypher_generator import _mock_generate

    cypher = _mock_generate("Who directed The Matrix?", _db_schema="")
    assert "DIRECTED" in cypher
