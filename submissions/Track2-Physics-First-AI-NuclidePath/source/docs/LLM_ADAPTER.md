# Local LLM Adapter

## Boundary

The local model is a planner, never a physics solver.

```text
composite scenario
  → OpenAICompatibleClient
  → LocalWorkflowPlanner (JSON list only)
  → EmergencyWorkflow validates required allow-listed steps
  → deterministic site/retrieval/transport/memory tools
  → verified report
```

The model cannot:

- change Kd, K+, velocity, porosity, density, dispersion, half-life or any other input;
- calculate or overwrite concentrations, retardation or travel time;
- invent source citations or uncertainty ranges;
- access an external network in local-only mode;
- control equipment, issue public alerts or recommend operational actions;
- bypass site, permission or transport validation.

## Full workflow planner

```python
from nuclear_agent.knowledge import LocalKnowledgeBase
from nuclear_agent.llm import OpenAICompatibleClient
from nuclear_agent.memory import LocalMemoryStore
from nuclear_agent.workflow import EmergencyWorkflow, LocalWorkflowPlanner

client = OpenAICompatibleClient(
    base_url="http://127.0.0.1:8000/v1",
    model="qwen35-9b-q8",
)
planner = LocalWorkflowPlanner(client)
workflow = EmergencyWorkflow(
    planner=planner,
    knowledge_base=LocalKnowledgeBase.from_directory("knowledge"),
    memory=LocalMemoryStore("results/memory.jsonl"),
)
result = workflow.run(case, session_id="demo")
```

The client uses `temperature=0`. The full planner must return exactly the required safe sequence:

```json
[
  "validate_permissions",
  "site_agent",
  "knowledge_retrieval",
  "environment_agent",
  "store_memory",
  "synthesize_report"
]
```

Malformed JSON, unknown steps and missing steps fail before tool execution.

## Offline fallback

`DeterministicWorkflowPlanner` returns the same sequence without an LLM. This path is the test/CI fallback and produces the same numerical `runs` for the same scenario.

The earlier three-step `LocalPlanner` and `Orchestrator` remain available as a minimal adapter example, but the submission demo uses `LocalWorkflowPlanner` and `EmergencyWorkflow`.

## Verified backend

The adapter has been exercised against Qwen3.5-9B Q8 through `llama.cpp` HIP/ROCm on AMD `gfx1100`. Runtime, hash and measured throughput are recorded in [AMD_LLM_BENCHMARK.md](AMD_LLM_BENCHMARK.md).
