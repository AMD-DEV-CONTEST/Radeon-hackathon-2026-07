from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from threading import RLock

from policyseal.security.fingerprints import KeyedFingerprinter
from policyseal.security.key_store import MasterKeyStore


class PseudonymCategory(StrEnum):
    PERSON = "Person"
    HOST = "Host"
    ACCOUNT = "Account"
    SUPPLIER = "Supplier"
    ASSET = "Asset"


@dataclass(frozen=True, slots=True)
class PseudonymRecord:
    category: PseudonymCategory
    value_hmac: str
    alias: str
    first_seen_order: int


class Pseudonymizer:
    def __init__(self, key_store: MasterKeyStore) -> None:
        self._fingerprints = KeyedFingerprinter(key_store)
        self._records: dict[
            str,
            dict[PseudonymCategory, dict[str, PseudonymRecord]],
        ] = {}
        self._lock = RLock()

    def alias(
        self,
        task_id: str,
        value: str,
        category: PseudonymCategory = PseudonymCategory.PERSON,
    ) -> str:
        if not task_id.strip() or not value:
            raise ValueError("task_id and pseudonymized value must not be blank")
        value_hmac = self._fingerprints.digest(
            f"pseudonym:{category.value}",
            value,
            scope=task_id,
        )
        with self._lock:
            by_category = self._records.setdefault(task_id, {}).setdefault(category, {})
            existing = by_category.get(value_hmac)
            if existing is not None:
                return existing.alias
            first_seen_order = len(by_category) + 1
            scope_token = self._fingerprints.digest("pseudonym-scope", task_id)[:4].upper()
            alias = f"{category.value}-{scope_token}-{first_seen_order:02d}"
            by_category[value_hmac] = PseudonymRecord(
                category=category,
                value_hmac=value_hmac,
                alias=alias,
                first_seen_order=first_seen_order,
            )
            return alias

    def snapshot(self, task_id: str) -> tuple[PseudonymRecord, ...]:
        with self._lock:
            records = self._records.get(task_id, {})
            flattened = (record for category in records.values() for record in category.values())
            return tuple(
                sorted(
                    flattened,
                    key=lambda item: (item.category.value, item.first_seen_order),
                )
            )

    def restore(self, task_id: str, records: tuple[PseudonymRecord, ...]) -> None:
        if not task_id.strip():
            raise ValueError("task_id must not be blank")
        with self._lock:
            restored: dict[PseudonymCategory, dict[str, PseudonymRecord]] = {}
            for record in records:
                by_category = restored.setdefault(record.category, {})
                if record.value_hmac in by_category:
                    raise ValueError("duplicate pseudonym fingerprint")
                if any(existing.alias == record.alias for existing in by_category.values()):
                    raise ValueError("duplicate pseudonym alias")
                by_category[record.value_hmac] = record
            self._records[task_id] = restored
