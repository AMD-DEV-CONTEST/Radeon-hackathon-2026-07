# AMD AI DevMaster Track 2 compliance

## Compliance matrix

| Requirement | Implementation | Evidence |
|---|---|---|
| AMD Radeon + ROCm | Qwen2.5-VL and Mask R-CNN use PyTorch HIP | `scripts/check_environment.py`, runtime metrics |
| Fully local core inference | Local checkpoints only; missing cache fails closed | `src/vision/vlm_inference.py` |
| Scenario task execution | Photography analysis, shooting plan, structured pose guidance, execution card | Web and CLI demos |
| Tool invocation | Neutral registry, manifest, timed calls, structured summaries | `src/agent/tool_registry.py`, `tool_calls` |
| Multi-step planning | Router → Analyzer → Checker → Planner → Critic → bounded refinement → Renderer | `src/agent/orchestrator.py`, `agent_trace` |
| Permission control | Per-tool permission declarations and deny-by-default policy | `src/agent/permissions.py`, `permission_audit` |
| Privacy | No external AI API, network denied, no persistent memory, temporary uploads deleted | `privacy`, `src/web.py` |
| Stability/performance | Automated tests and repeated full-Agent GPU benchmark | `scripts/benchmark_agent.py` |

Verified on Radeon Cloud: **47/47 tests passed**. One complete local
Qwen2.5-VL-3B + Mask R-CNN execution-card run took **33.043 s**, with **7.318
GiB** maximum allocated VRAM and **2.078 s** deterministic card rendering. The
result records that no image-generation model was used.

## Minimum functional requirements selected

### 1. Tool invocation

The Agent exposes a framework-neutral tool manifest. Every invocation:

1. resolves a registered tool definition;
2. checks required permissions;
3. records safe input metadata without image bytes or prompt content;
4. executes the local handler;
5. records device, status, output summary, and duration.

### 2. Multi-step task planning

The Planner converts grounded visual evidence into calibrated distance,
shooting angle, camera height, framing, lighting, subject direction, execution
sequence, fallbacks, and success checks. It deliberately omits inferred
left/right/front/back camera position. The Critic can trigger one bounded repair
but cannot invent new visual observations.

### 3. Permission control and privacy protection

Default policy:

| Permission | Decision |
|---|---|
| `read_uploaded_image` | allow for the current request |
| `gpu_inference` | allow locally |
| `write_temporary_result` | allow locally |
| `external_network` | deny |
| `persistent_storage` | deny |
| `generated_replacement_image` | deny |

The web handler removes uploaded images and rendered temporary cards in a
`finally` block. The reference thumbnail and person contour never leave the
local runtime; no generative image model is invoked.

## Reproduction

```bash
source /workspace/venv/bin/activate
cd /workspace/AI-Photographer-Agent

python scripts/check_environment.py
python -m unittest discover -s tests -v

python scripts/benchmark_agent.py \
  --image /workspace/b69343b9c09aadfa684347124910121c.JPG \
  --image demo/web_single_portrait_source.jpg \
  --runs 10 \
  --output demo/full_agent_benchmark.json
```

## Framework neutrality

The project uses open-source Transformers and PyTorch ROCm for inference and a
small internal registry for orchestration. The tool contracts are plain Python
and JSON, so the project does not depend on a closed Agent platform and can be
adapted to LangGraph, AutoGen, CrewAI, or another neutral orchestrator later
without changing core tools.
