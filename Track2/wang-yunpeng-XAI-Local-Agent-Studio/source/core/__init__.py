"""XAI 核心引擎（参考实现 / 模型无关）。

本包是 XAI 架构的"大脑参考实现"，用 Python 写成、可独立运行与测试，直接证明
蓝图（Guardian/Reason/Meta/Runner/KB/Orchestrator/Distill/ControlLoop）成立。
真实落地时，各模块对应 Rust crate：
  guardian   -> xai-grok-guardian
  reason     -> xai-grok-reason
  meta       -> xai-grok-meta
  runner     -> xai-grok-runner
  kb         -> xai-grok-kb
  orchestrator -> xai-grok-orchestra
  distill    -> xai-grok-distill
  control_loop -> xai-grok-control
"""

from .model_backend import ModelBackend, StubBackend, ModelResponse
from .deepseek_backend import DeepSeekBackend
from .guardian import (Action, RiskLevel, classify, approve, ApprovalResult,
                       GovernancePolicy, ApprovalQueue, before_tool_call,
                       PermissionTier, PermissionPolicy, needs_secondary_confirmation, guard)
from .cognition.reasoner import thinking_budget, thinking_protocol, self_refine, multi_trajectory, Budget
from .meta import BrierCalibrator, reflect, L8Auditor, ReflectResult, AuditDim
from .runner import Runner, RunState, StepResult
from .kb import KnowledgeBase, Chunk
from .orchestrator import Orchestrator, Node, Graph
from .distill import Distiller, SkillSpec, GepaEvolver, EvolutionTrace
from .control_loop import ControlLoop, LoopResult, A2UIEvent
from .models.router import ModelRouter, ModelProfile
from .skills import SkillRegistry, Skill
from .memory import MemorySystem, UnifiedMemoryPool
from .cognition.intent_router import IntentType, IntentResult, IntentRouter, route_task
from .openclaw_gateway import (
    GatewayCapability, Gateway, ActionResult,
    DesktopAdapter, BrowserAdapter, DocAdapter, ScheduleAdapter, MCPAdapter, OfficeAdapter,
    StubDesktopAdapter, StubBrowserAdapter, StubDocAdapter, StubScheduleAdapter,
    StubMCPAdapter, StubOfficeAdapter, default_gateway,
)
from .grok_build_engine import (
    CodeResult, RepoParser, RefactorTool, GitTool, TerminalTool, VulnScanner, TestGenTool,
    StubRepoParser, StubRefactorTool, StubGitTool, StubTerminalTool, StubVulnScanner, StubTestGenTool,
    CodeEngine, default_engine,
)
from .workflow_bridge import execute_workflow, topo_order

__all__ = [
    "ModelBackend", "StubBackend", "ModelResponse", "DeepSeekBackend",
    "Action", "RiskLevel", "classify", "approve", "ApprovalResult",
    "GovernancePolicy", "ApprovalQueue", "before_tool_call",
    "thinking_budget", "thinking_protocol", "self_refine", "multi_trajectory", "Budget",
    "BrierCalibrator", "reflect", "L8Auditor", "ReflectResult", "AuditDim",
    "Runner", "RunState", "StepResult",
    "KnowledgeBase", "Chunk",
    "Orchestrator", "Node", "Graph",
    "Distiller", "SkillSpec", "GepaEvolver", "EvolutionTrace",
    "ControlLoop", "LoopResult", "A2UIEvent",
    "ModelRouter", "ModelProfile",
    "SkillRegistry", "Skill",
    "MemorySystem",
    "IntentType", "IntentResult", "IntentRouter", "route_task",
    "GatewayCapability", "Gateway", "ActionResult",
    "DesktopAdapter", "BrowserAdapter", "DocAdapter", "ScheduleAdapter", "MCPAdapter", "OfficeAdapter",
    "StubDesktopAdapter", "StubBrowserAdapter", "StubDocAdapter", "StubScheduleAdapter",
    "StubMCPAdapter", "StubOfficeAdapter", "default_gateway",
    "CodeResult", "RepoParser", "RefactorTool", "GitTool", "TerminalTool", "VulnScanner", "TestGenTool",
    "StubRepoParser", "StubRefactorTool", "StubGitTool", "StubTerminalTool", "StubVulnScanner", "StubTestGenTool",
    "CodeEngine", "default_engine",
    "UnifiedMemoryPool",
    "PermissionTier", "PermissionPolicy", "needs_secondary_confirmation", "guard",
    "execute_workflow", "topo_order",
]
