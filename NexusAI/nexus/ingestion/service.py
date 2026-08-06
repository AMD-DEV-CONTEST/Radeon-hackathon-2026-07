import hashlib
from dataclasses import dataclass
from nexus.ingestion.chunker import chunk_text
from nexus.ingestion.parsers import parse_bytes

@dataclass
class IngestionResult:
    filename: str
    source_type: str
    checksum: str
    text: str
    chunks: list[str]

def ingest(filename: str, content: bytes) -> IngestionResult:
    text = parse_bytes(filename, content)
    checksum = hashlib.sha256(content).hexdigest()
    source_type = filename.rsplit(".", 1)[-1].lower() if "." in filename else "unknown"
    return IngestionResult(
        filename=filename,
        source_type=source_type,
        checksum=checksum,
        text=text,
        chunks=chunk_text(text),
    )
