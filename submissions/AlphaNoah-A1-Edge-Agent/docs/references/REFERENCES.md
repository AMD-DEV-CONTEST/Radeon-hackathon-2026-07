# External Technical References

Document status: curated reference registry for architecture and experiment documentation.

Last link review: 2026-07-23.

## Citation and Attribution Policy

This file records external sources, the ideas AlphaNoah A1 draws from, the project-specific adaptation, and the implementation boundary. A reference does not imply endorsement, code reuse, compatibility, or a runtime dependency.

Use these terms consistently:

- **Inspired by**: an external design influenced the architecture.
- **Adapted into**: AlphaNoah translated a pattern into its industrial maintenance context.
- **Implemented**: reserved for behavior present in the repository and supported by execution evidence.
- **Future research**: not implemented and not part of the current capability claim.

For HoloAgent-0, the correct description is **inspired by selected architecture patterns**, not **based on HoloAgent-0**. AlphaNoah must not imply that HoloAgent-0 code, models, data, or robot capabilities are included.

## 1. Embodied Agent Architecture

### HoloAgent-0

Status: **Closed — academic reference only.**

| Reference type | Official source |
|---|---|
| Paper | [HoloAgent-0: A Unified Embodied Agent Framework with 3D Spatial Memory](https://arxiv.org/abs/2606.23565) |
| Project page | [HoloAgent-0 official project page](https://horizonrobotics.github.io/robot_lab/holoagent/) |
| Project repository | [HorizonRobotics/HoloAgent](https://github.com/HorizonRobotics/HoloAgent) |

No source code, model, data, media or derived implementation is incorporated.
Future use of a specific component triggers a new pre-integration license audit.
Citation does not grant permission to copy paper figures, README images, code,
models or data. See
[ADR-0005](../decisions/ADR-0005-reference-only-use-of-holoagent.md).

#### Inspired by

- closed-loop execution rather than action generation alone;
- memory-centric execution;
- typed and observable Skills;
- monitoring and verification;
- failure recovery and re-planning;
- separation of Runtime, Memory, Skill, and Verification responsibilities.

#### Adapted into AlphaNoah A1

| HoloAgent-0 design idea | AlphaNoah A1 adaptation |
|---|---|
| Embodied runtime | deterministic A1 Maintenance Runtime |
| Spatial and temporal context | asset-scoped graph memory and work-order trace |
| Embodied Skills | typed maintenance software Skills |
| Monitoring and verification | repair-result verification |
| Robot recovery and re-planning | bounded retry, work-order reopen, or escalation |
| Physical grounding | QR-bound `asset_id` |

The detailed engineering comparison is maintained in [Design Inspirations](../research/DESIGN_INSPIRATIONS.md).

#### Not implemented in AlphaNoah A1 v0.1

- ROS2;
- 3D mapping or spatial navigation;
- robotic arm or mobile robot control;
- VLA models;
- robot motion planning;
- multi-robot coordination;
- HoloAgent-0 code, model, or data integration.

## 2. Agent Framework References

### Framework-independence statement

> AlphaNoah A1 v0.1 does not depend on LangChain or LangGraph. It only adopts selected engineering patterns.

**Architectural reference only; not currently installed or required at runtime.**

The domain model and deterministic state transitions remain framework-independent. The presence of these references must not be rewritten as “Powered by LangChain,” “Powered by LangGraph,” or “Built with LangChain/LangGraph.”

### LangChain

| Official source | Pattern of interest | AlphaNoah adaptation |
|---|---|---|
| [Structured output](https://docs.langchain.com/oss/python/langchain/structured-output) | schema-driven structured responses and validation | validate model-produced incident or assessment drafts before deterministic code uses them |
| [Tools](https://docs.langchain.com/oss/python/langchain/tools) | explicit tool interfaces and structured input/output | typed Skill contracts with declared schemas, effects, status, and evidence |

Patterns of interest:

- Structured Output;
- Tool Interface;
- Schema Validation;
- bounded repair for invalid model formatting;
- separation of model inference from deterministic execution.

These are design references only. AlphaNoah does not import LangChain types into its domain objects.

Documentation access date: 2026-07-23. These are rolling documentation pages, not
a declaration of an installed package version.

### LangGraph

| Official source | Pattern of interest | AlphaNoah adaptation |
|---|---|---|
| [Graph API overview](https://docs.langchain.com/oss/python/langgraph/graph-api) | State Graph, nodes, edges, and conditional transitions | explicit work-order states and deterministic transition guards |
| [Persistence](https://docs.langchain.com/oss/python/langgraph/persistence) | persisted state and checkpoints | planned local task checkpoints with auditable state |
| [Interrupts](https://docs.langchain.com/oss/python/langgraph/interrupts) | Interrupt, Human-in-the-loop, and Resume | explicit human approval gates and controlled continuation |

Patterns of interest:

- State Graph;
- Persistence;
- Checkpoint;
- Interrupt;
- Human-in-the-loop;
- Resume;
- failure recovery.

These are engineering references only. AlphaNoah v0.1 plans a lightweight deterministic state machine rather than a LangGraph execution path.

Documentation access date: 2026-07-23. If either package is later evaluated, label
it: **Experimental dependency, not part of the current formal runtime path.**

## 3. AMD Runtime References

| Topic | Official source | Use in AlphaNoah documentation |
|---|---|---|
| ROCm 7.2 Ryzen Linux compatibility | [ROCm 7.2 native Linux matrix](https://rocm.docs.amd.com/projects/radeon-ryzen/en/docs-7.2/docs/compatibility/compatibilityryz/native_linux/native_linux_compatibility.html) | verify `gfx1151`, Ryzen AI Max+ 395 and the validated PyTorch/OS combinations |
| ROCm 7.2.0 operating-system matrix | [ROCm 7.2.0 system requirements](https://rocm.docs.amd.com/projects/install-on-linux/en/docs-7.2.0/reference/system-requirements.html) | compare the reported Ubuntu and kernel combination with the version-specific matrix |
| ROCm 7.2.1 changes | [ROCm 7.2.1 release](https://github.com/ROCm/ROCm/releases/tag/rocm-7.2.1) | distinguish support added after the reported 7.2.0 installation |
| AMD GPU architecture and target names | [AMD GPU architecture specifications](https://rocm.docs.amd.com/en/latest/reference/gpu-arch-specs.html) | verify Radeon 8060S, `gfx1151` and 40 compute units |
| AMD processor/product specification | [AMD Ryzen AI Max+ 395](https://www.amd.com/en/products/processors/laptop/ryzen/ai-300-series/amd-ryzen-ai-max-plus-395.html) | verify official processor/GPU product characteristics, not the audited unit's installed memory |
| ROCm licensing | [ROCm component license table](https://rocm.docs.amd.com/en/docs-7.1.1/about/license.html) | avoid assigning one repository-wide license to the multi-component ROCm stack |
| Ollama `v0.20.3` release | [Official release](https://github.com/ollama/ollama/releases/tag/v0.20.3) | anchor the reported installed version |
| Ollama `v0.20.3` API schema | [Versioned OpenAPI file](https://github.com/ollama/ollama/blob/v0.20.3/docs/openapi.yaml) | verify request fields and documented endpoints without relying on rolling docs |
| Ollama `v0.20.3` CLI | [Versioned CLI documentation](https://github.com/ollama/ollama/blob/v0.20.3/docs/cli.mdx) | verify model inventory and local environment audit commands |
| Ollama `v0.20.3` compatibility/capabilities | [OpenAI compatibility](https://github.com/ollama/ollama/blob/v0.20.3/docs/api/openai-compatibility.mdx), [streaming](https://github.com/ollama/ollama/blob/v0.20.3/docs/api/streaming.mdx), [structured outputs](https://github.com/ollama/ollama/blob/v0.20.3/docs/capabilities/structured-outputs.mdx), [tool calling](https://github.com/ollama/ollama/blob/v0.20.3/docs/capabilities/tool-calling.mdx), [vision](https://github.com/ollama/ollama/blob/v0.20.3/docs/capabilities/vision.mdx) | define what must still be tested locally rather than treating upstream feature availability as machine evidence |

Official “latest” documentation can change after an experiment is run. Every experiment record must therefore include:

- access date;
- installed software versions;
- exact hardware identity;
- the specific documentation URL used;
- a saved, non-sensitive raw-output reference or checksum where practical.

Runtime documentation is a reference source, not benchmark evidence. Measured claims must come from the templates in [Experiments](../experiments/EXPERIMENT_RECORD_GUIDE.md).

## 4. Release Review Items

Before a public release, a human reviewer must:

- verify the HoloAgent-0 title, author list, publication status, and preferred formal citation;
- consult the separate HoloAgent-0 audit and confirm license/attribution requirements before reusing any HoloAgent-0 code or assets;
- pin the LangChain and LangGraph documentation version or access date used by an ADR;
- match ROCm documentation to the exact installed ROCm release rather than relying only on the mutable `latest` pages;
- verify Ollama version-specific API and CLI behavior on the audited machine;
- add third-party license notices if any external code, data, diagrams, or media are later incorporated.

Links alone do not grant permission to copy external material.
