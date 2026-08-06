from __future__ import annotations

import json
import logging
from typing import Any

from pydantic import BaseModel, Field

from agent_factory.agent_group_system.store import AgentGroupStore
from agent_factory.context_system.schema import CompressionPolicy
from agent_factory.context_system.token_counter import count_text_tokens
from agent_factory.runtime_kernel.model_operations.service import ModelOperationService


class GroupContextCheckpoint(BaseModel):
    objective: str = ""
    decisions: list[str] = Field(default_factory=list)
    findings: list[str] = Field(default_factory=list)
    open_questions: list[str] = Field(default_factory=list)
    artifacts: list[str] = Field(default_factory=list)
    summary: str = ""


class GroupContextCompactor:
    """Compiles versioned public group context and creates validated checkpoints."""

    def __init__(
        self,
        store: AgentGroupStore,
        model_service: ModelOperationService | None = None,
        logger: logging.Logger | None = None,
        compression_policy: CompressionPolicy | None = None,
    ) -> None:
        self.store = store
        self.model_service = model_service or ModelOperationService()
        self.logger = logger or logging.getLogger(__name__)
        self.compression_policy = compression_policy or CompressionPolicy()

    def render_since(self, group_id: str, version: int, *, through_version: int | None = None) -> tuple[str, int]:
        records = self.store.context_versions_after(group_id, version)
        parts: list[str] = []
        latest_version = version
        for record in records:
            if through_version is not None and int(record["version"]) > through_version:
                break
            latest_version = int(record["version"])
            kind = str(record.get("kind") or "")
            if kind == "snapshot":
                parts = [str(record.get("content") or "")]
                continue
            if kind != "delta":
                continue
            payload = _json_object(record.get("content"))
            content = str(payload.get("content") or "").strip()
            if content:
                parts.append(f"[{payload.get('speaker') or '用户'}] {content}")
        return "\n\n".join(part for part in parts if part.strip()), latest_version

    def maybe_compact(self, group_id: str, *, compression_policy: CompressionPolicy | None = None) -> int | None:
        policy = compression_policy or self.compression_policy
        current = self.store.get_group(group_id)
        current_version = int(current.get("current_context_version") or 0)
        rendered, _ = self.render_since(group_id, 0)
        token_count = int(count_text_tokens(rendered).token_count or 0)
        if token_count < policy.trigger_token_threshold:
            return None
        checkpoint = self._checkpoint(rendered)
        content = checkpoint.model_dump_json()
        compact_tokens = int(count_text_tokens(content).token_count or 0)
        return self.store.add_context_version(
            group_id,
            kind="snapshot",
            content=content,
            token_count=compact_tokens,
            from_version=current_version,
        )

    def _checkpoint(self, source: str) -> GroupContextCheckpoint:
        prompt = (
            "将以下 Agent 群聊公开上下文压缩为结构化工作检查点。保留用户约束、"
            "确认决策、有效结论、未解决问题和文件路径；不要编造信息，不要包含思考或工具原始输出。\n\n"
            f"{source}"
        )
        return self.model_service.structured_json(
            output_model=GroupContextCheckpoint,
            state=None,
            prebuilt_messages=[{"role": "user", "content": prompt}],
            model_role="task",
            max_attempts=2,
        )


def _json_object(value: Any) -> dict[str, Any]:
    try:
        parsed = json.loads(str(value or ""))
    except (TypeError, ValueError):
        return {}
    return parsed if isinstance(parsed, dict) else {}
