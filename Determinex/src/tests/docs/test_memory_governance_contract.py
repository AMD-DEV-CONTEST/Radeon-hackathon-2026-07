from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_memory_schema_tracks_source_and_chunk_provenance():
    db_rs = read("frontend/src-tauri/src/db.rs")

    assert "CREATE TABLE IF NOT EXISTS memory_sources" in db_rs
    assert "CREATE TABLE IF NOT EXISTS memory_chunks" in db_rs
    for field in (
        "source_path",
        "source_sha256",
        "source_type",
        "authority",
        "proof_status",
        "chunk_sha256",
        "chunk_index",
        "knowledge_rowid",
    ):
        assert field in db_rs


def test_companion_seeder_uses_hash_manifest_instead_of_row_count_guard():
    seeder = read("frontend/src-tauri/src/companion_seeder.rs")

    assert "source_sha256" in seeder
    assert "companion_manifest_matches" in seeder
    assert "clear_companion_memory" in seeder
    assert "memory_sources" in seeder
    assert "memory_chunks" in seeder
    assert "DELETE FROM vss_companion" in seeder
    assert "DELETE FROM knowledge_companion" in seeder
    assert "SELECT COUNT(*) FROM knowledge_companion" not in seeder


def test_memory_health_command_is_registered():
    lib_rs = read("frontend/src-tauri/src/lib.rs")
    health_rs = read("frontend/src-tauri/src/memory_health.rs")

    assert "mod memory_health;" in lib_rs
    assert "memory_health::get_memory_health" in lib_rs
    assert "#[tauri::command]\npub fn get_memory_health" in health_rs
    assert "knowledge_companion_rows" in health_rs
    assert "memory_sources" in health_rs
    assert "stale_sources" in health_rs


def test_stale_companion_boundary_test_no_longer_targets_removed_ui():
    test_rs = read("frontend/src-tauri/tests/companion_rag_tauri_command_boundary.rs")

    assert "OmniscienceHarvester.tsx" not in test_rs
    assert "CompanionRagReportPanel.tsx" in test_rs
    assert "memory_health.rs" in test_rs


def test_memory_operational_tools_exist():
    scorecard = read("scripts/memory_scorecard.py")
    inbox = read("scripts/memory_learning_inbox.py")

    assert "MemoryScorecard" in scorecard
    assert "mojibake" in scorecard.lower()
    assert "secret" in scorecard.lower()
    assert "training_eligible" in inbox
    assert "pending" in inbox
    assert "validate" in inbox


def test_project_contract_names_verifiable_memory_gates():
    project = read("PROJECT.md")

    assert "memory_sources" in project
    assert "memory_chunks" in project
    assert "scripts/memory_scorecard.py" in project
    assert "scripts/memory_learning_inbox.py" in project
    assert "source hash changes" in project
