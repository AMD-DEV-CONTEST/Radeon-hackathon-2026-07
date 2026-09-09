"""
Layer 4: 基础执行层（Worker/Executor）

通过 MCP 协议封装的原子能力服务，每个实例是独立的进程/容器。
- 无自主决策权
- 无上下文管理
- 输入输出标准化（增强 MCP 契约）
- 幂等性保证
"""

from .mcp_contract import (
    ErrorCode,
    MCPError,
    MCPRequest,
    MCPResponse,
    MCPSchema,
    IMAGE_GEN_SCHEMA,
    TTS_SCHEMA,
    MCPContractError,
    mcp_error_factory,
    is_retryable,
    get_timeout_for_type,
)
