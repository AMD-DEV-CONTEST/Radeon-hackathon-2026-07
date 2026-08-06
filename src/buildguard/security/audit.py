"""Complete tool execution audit trail."""

from collections.abc import Callable

from buildguard.logging_system.jsonl_writer import JsonlWriter
from buildguard.tools.schemas import ToolAuditEntry


class ToolAuditLogger:
    def __init__(
        self,
        writer: JsonlWriter,
        sink: Callable[[ToolAuditEntry], object] | None = None,
    ) -> None:
        self.writer = writer
        self.sink = sink

    def record(self, entry: ToolAuditEntry) -> None:
        self.writer.write(entry)
        self.writer.flush()
        if self.sink is not None:
            self.sink(entry)
