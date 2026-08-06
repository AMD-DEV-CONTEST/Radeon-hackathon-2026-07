"""Security audit JSONL logger."""

from buildguard.logging_system.jsonl_writer import JsonlWriter
from buildguard.schemas.tools import AuditRecord


class AuditLogger:
    def __init__(self, writer: JsonlWriter) -> None:
        self.writer = writer

    def log(self, record: AuditRecord) -> None:
        self.writer.write(record)
        self.writer.flush()

