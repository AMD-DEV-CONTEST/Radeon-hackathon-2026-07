# NEXUS Architecture

## Overview

NEXUS (The Causal Reality Agent Swarm) is an intelligent AI system that maintains a living causal model of your development environment and uses specialized agents to predict, debug, and optimize outcomes before they happen.

## Core Components

### 1. Inference Engine (`nexus/inference/`)

The ROCm-optimized inference engine manages multiple LLMs running in parallel on AMD Radeon GPUs.

**Key Features:**
- Multi-model management (LLaMA 70B, Qwen2.5-Coder 32B, Phi-4 14B)
- ROCm/HIP acceleration with Flash Attention 2
- Asynchronous parallel inference across 8+ streams
- Dynamic quantization (int4/int8/fp16/fp32)
- KV-cache sharing for memory efficiency

**Architecture:**
```
NexusInferenceEngine
├── ModelInstance (reasoning) - LLaMA 70B int4
├── ModelInstance (code) - Qwen2.5-Coder 32B fp16
└── ModelInstance (fast) - Phi-4 14B int4
    │
    ├── ROCm/HIP Backend
    ├── Flash Attention 2
    ├── BitsAndBytes Quantization
    └── Async Execution Streams (8x)
```

**Performance Targets:**
- Fast agent: <100ms latency
- Code analysis: <500ms latency
- Deep reasoning: <2s latency
- Parallel 8-agent swarm: <1s total (overlapped)

### 2. Causal Graph Engine (`nexus/graph/`)

The causal graph tracks all events and their relationships in a directed multigraph.

**Node Types:**
- `CODE_CHANGE`: Source code modifications
- `FILE_EDIT`: File system changes
- `GIT_COMMIT`: Version control events
- `DEPENDENCY_UPDATE`: Package changes
- `TEST_RUN` / `TEST_FAILURE`: Test execution
- `CONFIG_CHANGE`: Configuration updates
- `AGENT_ACTION` / `USER_ACTION`: Actions taken

**Edge Types:**
- `CAUSES`: Direct causation
- `DEPENDS_ON`: Dependencies
- `BREAKS`: Breaking changes
- `FIXES`: Bug fixes
- `TRIGGERS`: Event triggers

**Key Operations:**
- `trace_backward()`: Find root causes
- `trace_forward()`: Predict consequences
- `calculate_blast_radius()`: Impact analysis
- `find_root_causes()`: Multi-path root cause analysis

**Data Structure:**
```python
CausalGraph
├── NetworkX MultiDiGraph (nodes + edges)
├── Node Index (fast lookup by ID)
└── Time Index (sorted for temporal queries)
```

### 3. Agent Framework (`nexus/agents/`)

Specialized AI agents that perform different aspects of debugging and analysis.

#### Base Agent (`BaseAgent`)
- Abstract class for all agents
- Handles inference, error handling, timing
- Task-based execution model

#### Temporal Analyst Agent
**Purpose:** Traces backward through causal history to find root causes

**Capabilities:**
- Causal path traversal
- Root cause identification
- Timeline reconstruction
- Natural language explanation

**Model:** `reasoning` (LLaMA 70B)

#### Code Archaeologist Agent
**Purpose:** Deep code analysis and pattern recognition

**Capabilities:**
- Code pattern search
- Similar issue detection
- Historical context analysis
- Function/class usage tracking

**Model:** `code` (Qwen2.5-Coder 32B)

#### Fix Simulator Agent
**Purpose:** Simulates multiple fix strategies in parallel

**Capabilities:**
- Generate fix strategies
- Simulate outcomes
- Predict success probability
- Calculate blast radius
- Risk assessment
- Multi-criteria ranking

**Model:** `reasoning` (LLaMA 70B)

**Simulation Process:**
```
Problem → Generate N fix strategies
         ↓
    Parallel Simulation (4 branches)
         ↓
    [Branch A] [Branch B] [Branch C] [Branch D]
         ↓
    Outcome Prediction for each
         ↓
    Rank by: confidence × (1 / blast_radius) × (1 / risk)
         ↓
    Return ranked recommendations
```

### 4. Orchestrator (`nexus/core/orchestrator.py`)

The master coordinator that manages all subsystems and workflows.

**Main Workflow (`debug_problem()`):**

```
User Problem
     ↓
Phase 1: Temporal Analysis
     │    └─ Temporal Analyst Agent
     │        ├─ Trace causal history
     │        └─ Find root causes
     ↓
Phase 2: Code Archaeology  
     │    └─ Code Archaeologist Agent
     │        ├─ Search patterns
     │        └─ Find context
     ↓
Phase 3: Fix Simulation
     │    └─ Fix Simulator Agent
     │        ├─ Generate strategies
     │        ├─ Simulate outcomes
     │        └─ Rank solutions
     ↓
Generate Report + Recommendation
```

**Responsibilities:**
- Initialize all subsystems
- Manage agent lifecycle
- Coordinate multi-agent workflows
- Maintain causal graph
- Generate reports

### 5. Configuration (`nexus/core/config.py`)

Hierarchical configuration using Pydantic.

**Structure:**
```
NexusConfig
├── InferenceConfig
│   ├── device (hip/cuda/cpu)
│   ├── model paths
│   ├── quantization settings
│   └── ROCm parameters
├── GraphConfig
│   ├── storage backend
│   ├── max nodes/history
│   └── GPU acceleration
├── MonitoringConfig
│   ├── watch patterns
│   └── ignore patterns
└── AgentConfig
    ├── max concurrent agents
    └── enabled agent types
```

## Data Flow

### 1. Event Recording Flow
```
File Change → Monitor → Create Node → Add to Graph → Link Edges
```

### 2. Debug Flow
```
User Query
    ↓
Create Problem Node
    ↓
Launch Agent Swarm (parallel)
    │
    ├─ Temporal Analyst → Causal Graph → Root Causes
    ├─ Code Archaeologist → Code Search → Patterns
    └─ Fix Simulator → Simulate Branches → Rankings
    │
Aggregate Results → Generate Report → Present to User
```

### 3. Inference Flow
```
Agent Task
    ↓
Build Prompt
    ↓
Inference Engine
    │
    ├─ Select Model (reasoning/code/fast)
    ├─ Acquire Semaphore (concurrency limit)
    ├─ Tokenize Input
    ├─ GPU Inference (ROCm/HIP)
    │   ├─ Flash Attention 2
    │   └─ KV Cache
    ├─ Decode Output
    └─ Return Result
    │
Back to Agent → Process Result → Complete Task
```

## ROCm Optimization Strategy

### Memory Optimization
- **Quantization**: int4 for large models (70B), fp16 for medium (32B)
- **KV Cache Sharing**: Shared context across agent calls
- **Memory Fraction**: 90% GPU memory allocation
- **Gradient-Free**: Inference-only mode saves memory

### Compute Optimization
- **Flash Attention 2**: 3x speedup on attention operations
- **Kernel Fusion**: Combine operations where possible
- **Async Streams**: 8 parallel execution streams
- **Batching**: Dynamic batching for parallel agents

### RDNA3-Specific
- **Wavefront Scheduling**: Optimized for RDNA compute units
- **Infinity Cache**: Memory hierarchy optimization
- **Memory Coalescing**: Efficient VRAM access patterns

### Performance Targets
| Metric | Target | How Achieved |
|--------|--------|--------------|
| Single agent latency | <100ms | Phi-4 int4, flash attention |
| 8-agent swarm | <1s | Parallel streams, KV cache |
| VRAM usage | <20GB | Quantization, memory sharing |
| GPU utilization | >85% | Async execution, batching |
| Tokens/sec | 50+ | Flash attention, quantization |

## Extensibility

### Adding New Agents

```python
from nexus.agents.base import BaseAgent

class MyCustomAgent(BaseAgent):
    def __init__(self, agent_id, inference_engine):
        super().__init__(agent_id, inference_engine, model_type="fast")
    
    async def execute(self, task):
        # Your agent logic
        prompt = f"Custom task: {task.description}"
        result = await self._infer(prompt)
        
        return AgentResult(
            task_id=task.id,
            agent_id=self.agent_id,
            success=True,
            output=result.text,
        )
```

### Adding New Node Types

```python
from nexus.graph import NodeType

# Extend the enum
class CustomNodeType(NodeType):
    MY_EVENT = "my_event"

# Create and add nodes
node = CausalNode(
    id="custom_1",
    type=CustomNodeType.MY_EVENT,
    timestamp=datetime.now(),
    data={"key": "value"},
)
causal_graph.add_node(node)
```

## Future Enhancements

### MVP → Production Path

1. **Monitoring Layer**
   - Real-time file system monitoring (watchdog)
   - Git hook integration
   - IDE plugin integration

2. **Advanced Graph Algorithms**
   - GPU-accelerated graph traversal (HIP kernels)
   - Pattern matching with graph neural networks
   - Temporal prediction models

3. **Adaptive Agent Generation**
   - Dynamic agent synthesis based on problem domain
   - Knowledge injection from documentation
   - Self-improving agents

4. **Web Dashboard**
   - Real-time causal graph visualization (D3.js)
   - Agent activity monitoring
   - Performance metrics
   - Interactive debugging

5. **Multi-Project Support**
   - Cross-project causal analysis
   - Shared knowledge base
   - Team collaboration features

## Testing Strategy

### Unit Tests
- Individual components (agents, graph, inference)
- Mock inference for fast testing
- Graph algorithm correctness

### Integration Tests
- End-to-end workflows
- Agent coordination
- Causal graph operations

### Performance Tests
- ROCm vs CPU benchmarks
- Scalability tests (graph size, agent count)
- Memory usage profiling
- Latency measurements

### Benchmark Suite
See `scripts/benchmark_rocm.py` for:
- Single model inference
- Parallel agent execution
- Memory efficiency
- Throughput measurements
