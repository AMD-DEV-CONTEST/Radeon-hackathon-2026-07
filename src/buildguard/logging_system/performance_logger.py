"""Performance JSONL logger."""

from buildguard.logging_system.jsonl_writer import JsonlWriter
from buildguard.schemas.performance import PerformanceRecord


class PerformanceLogger:
    def __init__(self, writer: JsonlWriter) -> None:
        self.writer = writer

    def log(self, record: PerformanceRecord) -> None:
        self.writer.write(record)

