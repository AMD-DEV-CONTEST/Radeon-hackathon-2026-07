# XAI V2 Architecture

## 核心理念

**V1 核心问题**：`engine_xai.py` 1820 行上帝类，chat/workflow/memory/coordination/slash/approval/GEPA 全部耦合在一个 class 里。新增一个节点类型要改 if-else，改一行要全量回归。

**V2 解法**：六边形架构。内核是纯数据流（IR → Planner → Executor），外围是适配器（LLM/MCP/Skill/记忆），扩展靠插件注册，不再改内核。

---

## 1. 顶层模块划分

```
xai/
├── core/                    # 内核：纯逻辑，零 IO 依赖
│   ├── ir.py                # 类型定义（Pydantic）
│   ├── planner.py           # DAG 拓扑排序 + 层级分组
│   ├── executor.py          # 节点执行引擎
│   ├── registry.py          # 节点类型注册表
│   └── observer.py          # 进度事件流
│
├── nodes/                   # 节点实现（插件式）
│   ├── base.py              # BaseNode 抽象
│   ├── chat.py, input.py, output.py
│   ├── condition.py, loop.py, batch.py
│   ├── router.py, react.py, skill.py
│   ├── exec.py, mcp.py, agent.py
│   └── __init__.py          # 自动注册
│
├── adapters/                # 外部能力适配（可替换）
│   ├── llm.py               # LLM 适配接口
│   ├── mcp_gateway.py       # MCP 协议网关
│   ├── skill_runner.py      # Skill 执行器
│   └── memory_store.py      # 记忆读写
│
├── services/                # 业务服务层
│   ├── chat_service.py      # ControlLoop 五阶段
│   ├── coordination.py      # 多 Agent 调度
│   ├── gepa.py              # 自进化触发器
│   └── settings.py          # 配置管理
│
├── api/                     # HTTP/SSE 接口层
│   └── server.py            # FastAPI 路由
│
└── cli.py                   # 命令行入口
```

## 2. 核心契约

### 2.1 IR 类型系统

```python
from pydantic import BaseModel
from typing import Literal, Optional, Any

class NodeConfig(BaseModel):
    prompt: str = ""
    value: str = ""
    command: str = ""
    # 由各节点类型自行扩展

class WorkflowNode(BaseModel):
    id: str
    type: str          # "chat" | "condition" | "loop" | "batch" | ...
    label: str = ""
    config: NodeConfig = NodeConfig()

class WorkflowEdge(BaseModel):
    source: str
    target: str

class WorkflowIR(BaseModel):
    nodes: list[WorkflowNode]
    edges: list[WorkflowEdge]

class NodeResult(BaseModel):
    node_id: str
    status: Literal["running", "done", "error", "skipped"]
    output: str = ""
    error: Optional[str] = None
    duration_ms: float = 0
```

### 2.2 节点注册表

```python
class BaseNode(ABC):
    kind: str                          # 注册 key
    label: str
    backend_type: str

    @abstractmethod
    async def execute(self, config: NodeConfig, upstream: str, ctx: ExecutionContext) -> NodeResult:
        ...

class NodeRegistry:
    _nodes: dict[str, type[BaseNode]] = {}

    @classmethod
    def register(cls, node_cls: type[BaseNode]):
        cls._nodes[node_cls.kind] = node_cls

    @classmethod
    def get(cls, kind: str) -> type[BaseNode]:
        return cls._nodes[kind]
```

新增节点类型只需继承 BaseNode + 加 `@NodeRegistry.register` 注解，不动内核。

### 2.3 执行引擎

```python
class WorkflowExecutor:
    def __init__(self, registry: NodeRegistry, settings: ExecutionSettings):
        ...

    async def execute(self, ir: WorkflowIR) -> AsyncGenerator[NodeResult, None]:
        # 1. Planner: 拓扑排序 + 层级分组
        levels = self.planner.plan(ir)
        # 2. Executor: 逐层并行执行
        for level in levels:
            async with TaskGroup() as tg:
                for node in level:
                    tg.create_task(self._run_node(node, upstreams))
            # 3. Observer: 每节点完成后 yield 事件
        # 4. 返回最终结果流
```

### 2.4 LLM 适配接口

```python
class LLMAdapter(ABC):
    @abstractmethod
    async def infer(self, prompt: str, system: str = "", max_tokens: int = 2000) -> str:
        ...
```

HermesAdapter / DeepSeekAdapter / 任何新模型只需实现这个接口。

## 3. 数据流

```
用户输入
  │
  ▼
ChatService (ControlLoop)
  ├─ Reason  → LLMAdapter.infer()
  ├─ Meta    → 意图分类
  ├─ Guardian → 安全检查
  ├─ Execute → 路由到 workflow / code / browser / memory
  └─ Observe → 写记忆 + GEPA 触发
       │
       ▼
  WorkflowExecutor
    ├─ Planner → DAG 分层
    ├─ Executor → 并行执行节点
    │    └─ 每个节点调 NodeRegistry.get(type).execute()
    └─ Observer → SSE 事件流
```

## 4. V1→V2 迁移策略

| 阶段 | 内容 | 可独立验证 |
|---|---|---|
| **P0 抽离 IR** | 从 engine_xai.py 抽离 WorkflowNode/Edge 类型定义到 `core/ir.py` | `py_compile` |
| **P0 抽离 Registry** | `_run_wf_node` 的 if-else 改为 dict dispatch + NodeRegistry | 10 种节点全量回归 |
| **P0 抽离 Executor** | `run_workflow` 抽离到 `core/executor.py` | 并行调度/条件分支测试 |
| **P1 抽离 Planner** | 拓扑排序逻辑独立 | 回路检测测试 |
| **P1 接口化适配器** | LLM/MCP/Skill 适配器定义 ABC，HermesAdapter 实现 | 替换模型不碰内核 |
| **P2 节点插件化** | 每种节点拆为独立文件，NodeRegistry 自动注册 | 新增节点不加 if-else |
| **P2 统一记忆层** | memory.py + memory_core.py 合并，定义 MemoryStore 接口 | 记忆统计/检索测试 |
| **P3 Pydantic 全量类型** | 所有 dict 改为 TypedDict → Pydantic model | tsc/mypy 零错误 |

每个阶段产出独立可验证，不依赖后续阶段。
