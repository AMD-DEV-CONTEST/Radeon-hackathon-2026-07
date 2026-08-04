from pathlib import Path

import pytest

from policyseal.security.key_store import MasterKeyStore


@pytest.fixture
def key_store(tmp_path: Path) -> MasterKeyStore:
    return MasterKeyStore(tmp_path / "secrets" / "master.key")
