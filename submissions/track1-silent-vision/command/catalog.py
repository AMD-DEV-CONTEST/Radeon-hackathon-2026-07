import hashlib
import json
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path

from command.labels import CommandIntent


@dataclass(frozen=True)
class PhraseEntry:
    phrase_id: str
    text: str
    language: str
    intent: CommandIntent
    enabled: bool = True


@dataclass(frozen=True)
class PhraseCatalog:
    entries: tuple[PhraseEntry, ...]

    @classmethod
    def from_records(cls, records: list[dict]) -> "PhraseCatalog":
        entries: list[PhraseEntry] = []
        ids: set[str] = set()
        texts: set[str] = set()
        for record in records:
            phrase_id = str(record.get("phraseId", "")).strip()
            text = str(record.get("text", "")).strip()
            language = str(record.get("language", "")).strip()
            if not record.get("enabled", True):
                continue
            if not phrase_id or not text:
                raise ValueError("blank phraseId or text")
            if language not in {"zh", "en"}:
                raise ValueError(f"unsupported language: {language}")
            try:
                intent = CommandIntent(str(record["intent"]))
            except (KeyError, ValueError) as exc:
                raise ValueError(f"unknown intent: {record.get('intent')}") from exc
            if intent is CommandIntent.UNKNOWN:
                raise ValueError("UNKNOWN cannot be an enabled phrase class")
            normalized = normalize_phrase(text)
            if phrase_id in ids:
                raise ValueError(f"duplicate phraseId: {phrase_id}")
            if normalized in texts:
                raise ValueError(f"duplicate normalized phrase text: {text}")
            ids.add(phrase_id)
            texts.add(normalized)
            entries.append(PhraseEntry(phrase_id, text, language, intent, True))
        if not entries:
            raise ValueError("catalog has no enabled phrases")
        return cls(tuple(entries))

    def by_id(self, phrase_id: str) -> PhraseEntry:
        for entry in self.entries:
            if entry.phrase_id == phrase_id:
                return entry
        raise ValueError("unknown phraseId")


def normalize_phrase(text: str) -> str:
    normalized = unicodedata.normalize("NFKC", text).strip()
    return re.sub(r"\s+", " ", normalized).lower()


def load_phrase_catalog(path: Path) -> PhraseCatalog:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("schemaVersion") != "silent-vision.phrase-catalog.v1":
        raise ValueError("unsupported phrase catalog schema")
    return PhraseCatalog.from_records(payload["phrases"])


def catalog_sha256(catalog: PhraseCatalog) -> str:
    records = catalog_records(catalog)
    encoded = json.dumps(
        records, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode()
    return hashlib.sha256(encoded).hexdigest()


def catalog_records(catalog: PhraseCatalog) -> list[dict[str, object]]:
    return [
        {
            "phraseId": entry.phrase_id,
            "text": entry.text,
            "language": entry.language,
            "intent": entry.intent.value,
            "enabled": entry.enabled,
        }
        for entry in catalog.entries
    ]
