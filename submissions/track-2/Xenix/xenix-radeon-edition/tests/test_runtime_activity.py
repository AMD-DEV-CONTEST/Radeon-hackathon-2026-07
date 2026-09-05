import sqlite3
from pathlib import Path

import pytest

from xenix.services.runtime_activity import ApplicationActivityCoordinator, UpdateAdmissionError
from xenix.services.update_backup import create_update_backup


def test_update_is_blocked_while_work_is_active() -> None:
    coordinator = ApplicationActivityCoordinator()
    with coordinator.work("agent"):
        with pytest.raises(UpdateAdmissionError, match="agent"):
            coordinator.begin_update()
    coordinator.begin_update()
    with pytest.raises(UpdateAdmissionError, match="not accepting"):
        with coordinator.work("ml"):
            pass
    coordinator.cancel_update()
    assert coordinator.snapshot().accepting_work


def test_update_backup_is_valid_and_retained(tmp_path: Path) -> None:
    database = tmp_path / "xenix.db"
    with sqlite3.connect(database) as connection:
        connection.execute("CREATE TABLE sample(value TEXT)")
        connection.execute("INSERT INTO sample VALUES ('kept')")
    backup = create_update_backup(database, tmp_path / "backups", from_version="1.0.0", to_version="1.0.1")
    assert Path(backup.database).is_file()
    assert Path(backup.metadata).is_file()
    with sqlite3.connect(backup.database) as connection:
        assert connection.execute("SELECT value FROM sample").fetchone() == ("kept",)
