from __future__ import annotations


class AgentError(Exception):
    def __init__(self, message: str, code: str, status: int):
        super().__init__(message)
        self.code = code
        self.status = status
