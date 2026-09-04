from __future__ import annotations

import os
from pathlib import Path

import pytest

from policyseal.security.fingerprints import KeyedFingerprinter
from policyseal.security.key_store import KeyStoreError, MasterKeyStore
from policyseal.security.pseudonyms import PseudonymCategory, Pseudonymizer


def test_master_key_is_atomic_private_and_stable(key_store: MasterKeyStore) -> None:
    first = key_store.load_or_create()
    second = MasterKeyStore(key_store.path).load_or_create()

    assert len(first) == 32
    assert first == second
    assert key_store.path.stat().st_mode & 0o777 == 0o600


def test_master_key_rejects_wrong_size_or_permissions(tmp_path: Path) -> None:
    path = tmp_path / "master.key"
    path.write_bytes(b"short")
    path.chmod(0o644)

    with pytest.raises(KeyStoreError):
        MasterKeyStore(path).load_or_create()


def test_hmac_is_purpose_separated_and_constant_time_comparable(
    key_store: MasterKeyStore,
) -> None:
    service = KeyedFingerprinter(key_store)
    first = service.digest("audit-value", "synthetic-secret", scope="task-a")

    assert first == service.digest("audit-value", "synthetic-secret", scope="task-a")
    assert first != service.digest("alias-value", "synthetic-secret", scope="task-a")
    assert first != service.digest("audit-value", "synthetic-secret", scope="task-b")
    assert service.matches(first, "audit-value", "synthetic-secret", scope="task-a")
    assert not service.matches(first, "audit-value", "different", scope="task-a")
    assert "synthetic-secret" not in first


def test_alias_is_stable_within_task_and_unlinkable_between_tasks(
    key_store: MasterKeyStore,
) -> None:
    service = Pseudonymizer(key_store)

    assert service.alias("task-a", "alice") == service.alias("task-a", "alice")
    assert service.alias("task-a", "alice") != service.alias("task-b", "alice")
    assert "alice" not in service.alias("task-a", "alice").lower()


def test_aliases_use_category_and_first_seen_order_without_raw_values(
    key_store: MasterKeyStore,
) -> None:
    service = Pseudonymizer(key_store)

    first = service.alias("task-a", "fin-app-07", PseudonymCategory.HOST)
    second = service.alias("task-a", "db-app-02", PseudonymCategory.HOST)
    person = service.alias("task-a", "Elena Park", PseudonymCategory.PERSON)
    snapshot = service.snapshot("task-a")

    assert first.startswith("Host-") and first.endswith("-01")
    assert second.startswith("Host-") and second.endswith("-02")
    assert person.startswith("Person-") and person.endswith("-01")
    serialized = repr(snapshot)
    assert "fin-app-07" not in serialized
    assert "db-app-02" not in serialized
    assert "Elena Park" not in serialized


@pytest.mark.skipif(os.name != "posix", reason="POSIX permission contract")
def test_existing_private_key_keeps_mode_0600(key_store: MasterKeyStore) -> None:
    key_store.load_or_create()
    key_store.path.chmod(0o600)

    MasterKeyStore(key_store.path).load_or_create()

    assert key_store.path.stat().st_mode & 0o777 == 0o600
