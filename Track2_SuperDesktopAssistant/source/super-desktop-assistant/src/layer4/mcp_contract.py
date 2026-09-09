"""
Layer 4: 增强 MCP 契约定义（v2.0）

每个第4层 Worker 都遵循此契约：
- 输入：标准 JSON 请求
- 输出：结构化成功/失败响应，错误码包含 retryable 和 suggested_action
- 幂等性：同一请求重复执行应得到相同结果

v2.0 新增：
  - ErrorCode 枚举，带 retryable 标记和建议操作
  - 标准 MCPResponse 用 dataclass，统一错误上报格式
  - 按任务类型的超时建议
"""
from __future__ import annotations

import enum
from dataclasses import dataclass, field
from typing import Any


# ═══════════════════════════════════════════════════════════════
# 增强错误码体系
# ═══════════════════════════════════════════════════════════════

class ErrorCode(enum.Enum):
    """标准化 MCP 错误码 —— 每个错误码附带可重试标记和建议操作。"""

    # ── 通用 ──
    OK = ("OK", True, None)                              # 成功（非错误）
    UNKNOWN = ("E000", False, "检查日志获取详情")         # 未知错误

    # ── 资源类（不可重试） ──
    CUDA_OOM = ("E001", False, "降低分辨率或减少 batch size")
    DISK_FULL = ("E002", False, "清理磁盘空间后重试")
    MEMORY_EXCEEDED = ("E003", False, "减少输入长度或拆分任务")

    # ── 鉴权/配置类（不可重试） ──
    AUTH_FAILED = ("E100", False, "检查 API Key 是否正确配置")
    QUOTA_EXHAUSTED = ("E101", False, "充值或等待配额重置")
    MODEL_NOT_FOUND = ("E102", False, "检查模型名称是否正确，或切换到可用模型")
    INVALID_PARAM = ("E103", False, "检查参数范围是否合法")

    # ── 网络/超时类（可重试） ──
    TIMEOUT = ("E200", True, "增加超时时间或简化任务")
    RATE_LIMITED = ("E201", True, "降低请求频率，等待后重试")
    NETWORK_ERROR = ("E202", True, "检查网络连接后重试")
    SERVER_ERROR = ("E203", True, "服务端暂时故障，等待后重试")

    # ── 内容类（可重试但需调整） ──
    CONTENT_FILTERED = ("E300", True, "调整 prompt 中的敏感词后重试")
    INVALID_OUTPUT = ("E301", True, "调整参数或 prompt 后重试")
    EMPTY_RESULT = ("E302", True, "重试或调整 prompt")

    # ── 依赖类 ──
    DEPENDENCY_FAILED = ("E400", False, "等待上游任务成功后再执行")

    @property
    def code(self) -> str:
        return self.value[0]

    @property
    def retryable(self) -> bool:
        return self.value[1]

    @property
    def suggested_action(self) -> str | None:
        return self.value[2]

    @classmethod
    def from_code(cls, code_str: str) -> "ErrorCode":
        """从错误码字符串查找对应枚举。"""
        for ec in cls:
            if ec.code == code_str:
                return ec
        return cls.UNKNOWN

    @classmethod
    def from_error_string(cls, error_msg: str) -> "ErrorCode":
        """从错误消息自动分类。"""
        from ..api.errors import classify_error, is_permanent_error

        category = classify_error(error_msg)
        mapping = {
            "auth": cls.AUTH_FAILED,
            "quota": cls.QUOTA_EXHAUSTED,
            "model": cls.MODEL_NOT_FOUND,
            "rate_limit": cls.RATE_LIMITED,
            "timeout": cls.TIMEOUT,
            "network": cls.NETWORK_ERROR,
            "server_error": cls.SERVER_ERROR,
        }
        if category in mapping:
            return mapping[category]

        # 资源类检测
        msg_lower = error_msg.lower()
        if any(k in msg_lower for k in ("cuda", "out of memory", "oom", "vram")):
            return cls.CUDA_OOM
        if any(k in msg_lower for k in ("disk", "no space")):
            return cls.DISK_FULL
        if any(k in msg_lower for k in ("content filter", "content policy", "safety")):
            return cls.CONTENT_FILTERED

        return cls.UNKNOWN


# ═══════════════════════════════════════════════════════════════
# MCP 请求/响应结构
# ═══════════════════════════════════════════════════════════════

class MCPContractError(Exception):
    """MCP 契约违规异常。"""
    pass


@dataclass
class MCPError:
    """增强的错误信息结构。"""
    code: str                          # 错误码（如 "E001"）
    message: str                       # 人类可读描述
    retryable: bool = False            # 是否可安全重试
    suggested_action: str | None = None  # 建议的补救操作


@dataclass
class MCPResponse:
    """MCP 执行层标准响应。"""
    status: str                       # "success" | "error"
    data: Any = None                  # 成功时的返回数据
    error: MCPError | None = None     # 失败时的错误详情
    node_id: str = ""                 # 所属节点 ID（用于追踪）
    elapsed_ms: float = 0             # 执行耗时

    @classmethod
    def success(cls, data: Any, node_id: str = "", elapsed_ms: float = 0) -> "MCPResponse":
        return cls(status="success", data=data, node_id=node_id, elapsed_ms=elapsed_ms)

    @classmethod
    def failure(cls, error_code: ErrorCode, message: str = "",
                node_id: str = "", elapsed_ms: float = 0) -> "MCPResponse":
        return cls(
            status="error",
            error=MCPError(
                code=error_code.code,
                message=message or error_code.name,
                retryable=error_code.retryable,
                suggested_action=error_code.suggested_action,
            ),
            node_id=node_id,
            elapsed_ms=elapsed_ms,
        )


@dataclass
class MCPRequest:
    """MCP 执行层标准请求。"""
    action: str                       # 操作名（如 generate_image, chat, transcribe）
    params: dict = field(default_factory=dict)
    node_id: str = ""                 # 调用方节点 ID
    idempotency_key: str = ""         # 幂等键（同一请求重复执行应得相同结果）


# ═══════════════════════════════════════════════════════════════
# 各 Worker 类型的 JSON Schema
# ═══════════════════════════════════════════════════════════════

@dataclass
class MCPSchema:
    """MCP 操作的 JSON Schema 定义。"""
    action: str
    input_schema: dict
    output_schema: dict
    timeout_per_type: float = 30.0    # 按任务类型的建议超时（秒）


# ── 生图 Worker ──

IMAGE_GEN_SCHEMA = MCPSchema(
    action="generate_image",
    input_schema={
        "prompt": "string (required) - 正向提示词",
        "negative_prompt": "string - 负向提示词",
        "width": "int - 图片宽度，默认512",
        "height": "int - 图片高度，默认512",
        "steps": "int - 采样步数",
        "cfg_scale": "float - CFG scale",
        "seed": "int - 随机种子（幂等性：同 seed 应得同结果）",
        "idempotency_key": "string - 幂等键",
    },
    output_schema={
        "status": "success|error",
        "data": {"image_url": "string", "seed": "int"},
        "error": {"code": "string", "message": "string", "retryable": "bool", "suggested_action": "string"},
    },
    timeout_per_type=120.0,     # 生图超时较长
)

# ── LLM Worker ──

LLM_SCHEMA = MCPSchema(
    action="chat",
    input_schema={
        "messages": "list[dict] - 对话消息",
        "temperature": "float",
        "max_tokens": "int",
        "tools": "list[dict] - 可选，工具定义",
        "idempotency_key": "string - 幂等键",
    },
    output_schema={
        "status": "success|error",
        "data": {"content": "string", "tool_calls": "list", "usage": {}},
        "error": {"code": "string", "message": "string", "retryable": "bool", "suggested_action": "string"},
    },
    # BUG8 修复：与 executor._DEFAULT_TIMEOUT_BY_TYPE[LLM]=240s 对齐
    # （此前 30s vs 执行器 240s 的 8 倍差异误导按契约调超时的人）
    timeout_per_type=240.0,
)

# ── TTS Worker ──

TTS_SCHEMA = MCPSchema(
    action="text_to_speech",
    input_schema={
        "text": "string - 要合成的文本",
        "voice": "string - 音色",
        "speed": "float - 语速",
        "language": "string - 语言",
        "idempotency_key": "string - 幂等键",
    },
    output_schema={
        "status": "success|error",
        "data": {"audio_url": "string", "duration_ms": "int"},
        "error": {"code": "string", "message": "string", "retryable": "bool", "suggested_action": "string"},
    },
    timeout_per_type=20.0,
)

# ── STT Worker ──

STT_SCHEMA = MCPSchema(
    action="speech_to_text",
    input_schema={
        "audio_path": "string - 音频文件路径",
        "language": "string - 语言提示",
        "idempotency_key": "string - 幂等键",
    },
    output_schema={
        "status": "success|error",
        "data": {"text": "string", "language": "string"},
        "error": {"code": "string", "message": "string", "retryable": "bool", "suggested_action": "string"},
    },
    timeout_per_type=15.0,
)

# ── Schema 查找表 ──

_SCHEMA_BY_TYPE: dict[str, MCPSchema] = {
    "llm": LLM_SCHEMA,
    "image_gen": IMAGE_GEN_SCHEMA,
    "image_edit": IMAGE_GEN_SCHEMA,
    "tts": TTS_SCHEMA,
    "stt": STT_SCHEMA,
    "vision": LLM_SCHEMA,  # 视觉复用 LLM schema（多模态调用）
}


def get_timeout_for_type(node_type: str) -> float:
    """根据节点类型返回建议超时。"""
    schema = _SCHEMA_BY_TYPE.get(node_type)
    return schema.timeout_per_type if schema else 30.0


# ═══════════════════════════════════════════════════════════════
# 便捷工厂函数
# ═══════════════════════════════════════════════════════════════

def mcp_error_factory(error: Exception, node_id: str = "") -> MCPError:
    """从 Python Exception 自动生成 MCPError。"""
    msg = str(error)
    ec = ErrorCode.from_error_string(msg)
    return MCPError(
        code=ec.code,
        message=msg[:500],
        retryable=ec.retryable,
        suggested_action=ec.suggested_action,
    )


def is_retryable(error: MCPError | ErrorCode) -> bool:
    """判断错误是否可重试。"""
    if isinstance(error, MCPError):
        return error.retryable
    return error.retryable
