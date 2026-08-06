"""
Agent 群聊系统 - 域模型定义

与 collaboration_system 不同，本模块使用 Pydantic 提供类型安全和验证。
所有模型遵循文档 §3-5 的领域约束。
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class GroupStatus(str, Enum):
    """群聊状态 (§3.1)"""

    draft = "draft"
    active = "active"
    archived = "archived"


class MemberRunStatus(str, Enum):
    """成员运行状态 (§5)"""

    queued = "queued"
    running = "running"
    awaiting_approval = "awaiting_approval"
    completed = "completed"
    failed = "failed"
    cancelled = "cancelled"


class MessageSpeakerType(str, Enum):
    """消息发言者类型 (§4.2)"""

    user = "user"
    agent = "agent"
    system = "system"


class MessageKind(str, Enum):
    """消息种类 (§4.3)"""

    user_message = "user_message"
    agent_response = "agent_response"
    tool_call = "tool_call"
    tool_result = "tool_result"
    approval_request = "approval_request"
    system_notice = "system_notice"
    progress = "progress"


# ===== 核心域模型 =====


class AgentGroupSession(BaseModel):
    """群聊会话 (§3)"""

    model_config = ConfigDict(extra="forbid")

    group_id: str
    title: str
    status: GroupStatus
    created_at: datetime
    updated_at: datetime
    archived_at: datetime | None = None


class AgentGroupMember(BaseModel):
    """群聊成员 (§3.2)"""

    model_config = ConfigDict(extra="forbid")

    group_id: str
    package_id: str
    package_session_id: str
    joined_at: datetime


class AgentGroupMessage(BaseModel):
    """群聊消息 (§4)"""

    model_config = ConfigDict(extra="forbid")

    message_id: str
    group_id: str
    speaker_type: MessageSpeakerType
    speaker_package_id: str | None = None
    message_kind: MessageKind
    content: str
    group_run_id: str | None = None
    event_ref: str | None = None
    created_at: datetime


class AgentGroupMemberRun(BaseModel):
    """成员运行记录 (§5)"""

    model_config = ConfigDict(extra="forbid")

    group_run_id: str
    group_id: str
    message_id: str  # 触发此次运行的用户消息
    speaker_package_id: str
    package_session_id: str
    status: MemberRunStatus
    base_context_version: int
    base_workspace_revision: int
    request_id: str | None = None
    response_message_id: str | None = None
    created_at: datetime
    updated_at: datetime


class AgentGroupContextVersion(BaseModel):
    """共享上下文版本 (§7)"""

    model_config = ConfigDict(extra="forbid")

    group_id: str
    version: int
    kind: str  # 'snapshot' | 'delta'
    from_version: int | None = None  # delta 起点
    content: str
    token_count: int
    created_at: datetime


class AgentGroupWorkspaceRevision(BaseModel):
    """工作区版本 (§8)"""

    model_config = ConfigDict(extra="forbid")

    group_id: str
    revision: int
    parent_revision: int | None = None
    file_manifest_json: str  # JSON: {path: sha256}
    created_at: datetime


class AgentGroupWorkspaceCommit(BaseModel):
    """工作区提交事务 (§11.3)"""

    model_config = ConfigDict(extra="forbid")

    commit_id: str
    group_id: str
    group_run_id: str
    source_revision: int
    target_revision: int | None = None  # 成功后回填
    status: str  # 'prepared' | 'files_committed' | 'context_committed' | 'completed' | 'conflict' | 'aborted'
    conflict_files_json: str | None = None  # JSON: [{path, type}]
    created_at: datetime
    updated_at: datetime


# ===== 视图模型（前端交互） =====


class AgentGroupSessionView(BaseModel):
    """群聊会话视图（含消息、成员、runs）"""

    model_config = ConfigDict(extra="forbid")

    group_id: str
    title: str
    status: GroupStatus
    created_at: datetime
    updated_at: datetime
    archived_at: datetime | None = None
    members: list[AgentGroupMemberView] = Field(default_factory=list)
    messages: list[AgentGroupMessage] = Field(default_factory=list)
    runs: list[AgentGroupMemberRun] = Field(default_factory=list)
    current_context_version: int = 0
    current_workspace_revision: int = 0
    workspace_resource: dict[str, Any] | None = None  # {resource_mode, group_id, workdir}


class AgentGroupMemberView(BaseModel):
    """成员视图（含 package 元数据）"""

    model_config = ConfigDict(extra="forbid")

    group_id: str
    package_id: str
    package_session_id: str
    joined_at: datetime
    agent_name: str | None = None
    agent_description: str | None = None


class AgentView(BaseModel):
    """Agent 元数据视图（复用 agent_registry）"""

    model_config = ConfigDict(extra="forbid")

    package_id: str
    agent_name: str
    agent_description: str | None = None
    status: str | None = None


# ===== 请求/响应模型 =====


class CreateGroupRequest(BaseModel):
    """创建群聊请求"""

    model_config = ConfigDict(extra="forbid")

    title: str
    member_package_ids: list[str] = Field(default_factory=list)


class UpdateGroupRequest(BaseModel):
    """更新群聊请求"""

    model_config = ConfigDict(extra="forbid")

    title: str | None = None
    status: GroupStatus | None = None


class SendMessageRequest(BaseModel):
    """发送消息请求"""

    model_config = ConfigDict(extra="forbid")

    content: str
    client_message_id: str  # 前端生成，幂等键
    target_package_ids: list[str] = Field(default_factory=list)  # @提及的 agents


class AddMemberRequest(BaseModel):
    """添加成员请求"""

    model_config = ConfigDict(extra="forbid")

    package_id: str


class RunActionRequest(BaseModel):
    """运行动作请求（stop/cancel）"""

    model_config = ConfigDict(extra="forbid")

    group_run_id: str
    action: str  # 'stop' | 'cancel'


class ApprovalResolutionRequest(BaseModel):
    """审批决议请求"""

    model_config = ConfigDict(extra="forbid")

    group_run_id: str
    approved: bool
    user_response: str | None = None
