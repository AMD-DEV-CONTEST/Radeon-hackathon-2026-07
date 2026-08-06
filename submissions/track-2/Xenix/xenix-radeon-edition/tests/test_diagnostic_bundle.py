import json
import sqlite3
import zipfile
import importlib.util
from pathlib import Path


def _load_bundle_main():
    script_path = Path(__file__).resolve().parents[1] / "scripts" / "create_diagnostic_bundle.py"
    spec = importlib.util.spec_from_file_location("create_diagnostic_bundle", script_path)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module.main


def test_diagnostic_bundle_contains_logs_and_metadata_without_raw_database(monkeypatch, tmp_path: Path) -> None:
    main = _load_bundle_main()
    runtime_home = tmp_path / "xenix-home"
    monkeypatch.setenv("XENIX_APP_HOME", str(runtime_home))
    (runtime_home / "logs").mkdir(parents=True)
    (runtime_home / "state").mkdir(parents=True)
    (runtime_home / "artifacts" / "ml-tasks" / "task-1").mkdir(parents=True)
    (runtime_home / "logs" / "xenix.log").write_text('{"event":"hello"}\n', encoding="utf-8")
    (runtime_home / "artifacts" / "ml-tasks" / "task-1" / "logs.jsonl").write_text(
        '{"level":"INFO","message":"task"}\n',
        encoding="utf-8",
    )
    db_path = runtime_home / "state" / "xenix.db"
    with sqlite3.connect(db_path) as connection:
        connection.execute("PRAGMA user_version=13")
        connection.execute("CREATE TABLE sample (id TEXT)")
        connection.execute("INSERT INTO sample (id) VALUES ('row-1')")
        connection.commit()

    output_path = tmp_path / "bundle.zip"
    assert main(["--output", str(output_path)]) == 0

    with zipfile.ZipFile(output_path) as bundle:
        names = set(bundle.namelist())
        assert "metadata.json" in names
        assert "logs/xenix.log" in names
        assert "artifacts/ml-tasks/task-1/logs.jsonl" in names
        assert "state/xenix.db" not in names
        metadata = json.loads(bundle.read("metadata.json").decode("utf-8"))

    assert metadata["runtime_home_class"] == "custom"
    assert metadata["sqlite"]["user_version"] == 13
    assert metadata["sqlite"]["table_counts"]["sample"] == 1
