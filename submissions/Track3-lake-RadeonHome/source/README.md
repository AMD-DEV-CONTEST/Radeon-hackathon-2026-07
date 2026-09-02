# RadeonHome — Source Code

> Language-guided, failure-aware household mobile manipulation on AMD Radeon / ROCm.
> Full repository: [520lake/RadeonHome](https://github.com/520lake/RadeonHome)

## Architecture

```
Natural-language instruction ("take the apple to the kitchen table")
          │
          ▼
local_llm.py / local_qwen_server.py — Qwen3-4B on ROCm
          │
          ▼
language.py — constrained semantic task plan + allow-list validation
          │
          ▼
navigation.py — A* grid planner in 6×6m room
          │
          ▼
mobile_scene.py — planar-root MJCF mobile Franka in Genesis
mjcf_mobile_pipeline.py — physical controller entry point
mobile_grasp.py — grasp execution with official collision model
recovery.py — real-time slip detection + autonomous retry
          │
          ▼
rocm_telemetry.py — GPU utilization, VRAM, power sampling
dashboard.py — live web dashboard (RGB, depth, execution phase)
          │
          ▼
RGB + metric depth + MP4 + result JSON + ROCm telemetry
```

## Module Map

| Module | Lines | Role |
|---|---|---|
| `mjcf_mobile_pipeline.py` | 1,911 | Core mobile manipulation pipeline — docking, grasp, carry, place |
| `mobile_grasp.py` | 967 | Physical-contact grasp execution with official Franka MJCF model |
| `large_room_scene.py` | 274 | 6×6m room with semantic zones and obstacles |
| `mobile_scene.py` | 315 | Planar-root joint generation for mobile chassis |
| `navigation.py` | 120 | A* grid planner with obstacle dilation |
| `recovery.py` | 35 | Slip detection and recovery trigger |
| `recovery_evaluation.py` | 225 | Recovery success rate evaluation |
| `language.py` | 52 | Task schema validation and allow-list enforcement |
| `local_llm.py` | 199 | Qwen3-4B integration with explicit output constraints |
| `local_qwen_server.py` | 74 | vLLM server management for local Qwen |
| `orchestrator.py` | 104 | End-to-end pipeline from instruction to result |
| `spatial_tasks.py` | 160 | Semantic task definitions and spatial mappings |
| `semantic_world.py` | 62 | Semantic zone and object registration |
| `rocm_telemetry.py` | 170 | ROCm-SMI sampling, GPU metrics collection |
| `dashboard.py` | 480 | Live web dashboard with RGB/depth streaming |
| `live_runner.py` | 156 | CLI entry point for interactive execution |
| `models.py` | 30 | Pydantic task models |
| `policy.py` | 52 | Controller interface (deterministic) |
| `batch_evaluation.py` | 79 | Multi-seed batch runner |
| `mjcf_batch_evaluation.py` | 328 | MJCF-specific batch evaluation |
| `mjcf_reference.py` | 140 | Reference frame management |
| `ablation_summary.py` | 117 | Matched-seed ablation report generator |
| `evaluation_report.py` | 117 | Evaluation report builder |
| `cli.py` | 33 | CLI entry points |
| `scene.py` | 190 | Base scene utilities |
| `__init__.py` | 4 | Package init |

## Tests

| Test File | What it covers |
|---|---|
| `test_mjcf_mobile_pipeline.py` | End-to-end pipeline validation |
| `test_mjcf_batch_evaluation.py` | Batch evaluation correctness |
| `test_mjcf_reference.py` | Reference frame transforms |
| `test_navigation.py` | A* planner path validity |
| `test_language.py` | Task schema validation |
| `test_local_llm.py` | LLM output parsing |
| `test_orchestrator.py` | Pipeline orchestration |
| `test_policy.py` | Controller interface contracts |
| `test_recovery_evaluation.py` | Recovery evaluation metrics |
| `test_rocm_telemetry.py` | Telemetry collection |
| `test_spatial_tasks.py` | Spatial task definitions |
| `test_batch_evaluation.py` | Batch runner correctness |
| `test_evaluation_report.py` | Report generation |
| `test_ablation_summary.py` | Ablation summary generation |
| `test_live_runner.py` | Live runner interface |

## Security Boundary

The language model (`local_llm.py`, `language.py`) **never emits joint commands or coordinates**.
An explicit allow-list in `language.py` validates every model-selected action, object, target,
and safety constraint before the deterministic controller can execute it. The LLM produces only
a structured task schema; all physical control is deterministic.
