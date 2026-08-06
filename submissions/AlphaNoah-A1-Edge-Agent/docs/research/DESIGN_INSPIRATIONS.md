# Design Inspirations and AlphaNoah Engineering Adaptation

Phase note (2026-07-23): this is a historical provenance/reference document.
Current implementation claims are maintained in
[AlphaNoah System Overview](../architecture/ALPHANOAH_SYSTEM_OVERVIEW.md).

> **AlphaNoah A1 Edge Agent** — *An AMD ROCm-powered industrial asset maintenance edge agent.*

## 1. Purpose

This document records where the architecture ideas came from, how AlphaNoah adapts them to industrial asset maintenance, what the hackathon v0.1 intends to implement, and what remains unimplemented.

AlphaNoah A1 does not reproduce a complete robot system, modify a foundation model or claim ownership of patterns established by prior research and Agent frameworks. Its project-level contribution is the constrained engineering combination of physical asset identity, typed operational Skills, closed-loop verification, explainable event memory and local AMD ROCm inference.

The distinctions used throughout this document are:

- **Inspired by**: an external idea shaped the design direction.
- **Adapted into**: A1 maps the idea into a different system-level maintenance concept.
- **Implemented in v0.1**: reserved for behavior that exists and has execution evidence. At the time of this document, no Runtime capability qualifies because the repository contains documentation and structure only.
- **Future research**: a direction that is outside the hackathon implementation boundary and has no delivery claim.

No long passage from an external paper or framework is reproduced here. Primary-source links and their attribution boundary are centralized in [External Technical References](../references/REFERENCES.md).

## 2. Inspiration: HoloAgent-0

### 2.1 Ideas used as inspiration

The task-provided HoloAgent-0 summary motivates these high-level principles:

- **Closed-loop first**: success requires monitoring an outcome, not merely generating an action.
- **Memory-centric execution**: decisions use structured current and historical context.
- **Typed and observable skills**: capabilities have contracts, status and evidence.
- **Monitoring and verification**: expected results are checked explicitly.
- **Failure recovery and re-planning**: failure returns the system to a controlled recovery path.
- **Separation of concerns**: runtime, memory, Skill and monitoring have distinct responsibilities.

A1 uses these as architectural inspiration for an industrial maintenance information workflow. It does not claim to reproduce embodied execution.

### 2.2 Engineering mapping

| HoloAgent-0 concept | AlphaNoah A1 adaptation | Adaptation boundary |
|---|---|---|
| Embodied AgentOS | A1 Maintenance Runtime | Information and workflow runtime, not a robot OS |
| Spatial Memory | Asset Graph Memory | Device relationships and identity, not a 3D world map |
| Temporal Memory | Work-order and recovery trace | Persisted maintenance events and transitions |
| Embodied Skills | Typed maintenance Skills | Schema-bound software operations, not motor primitives |
| Monitoring & Verification | Repair-result verification | Human observations and deterministic criteria |
| Robot re-planning | Ticket retry, reopen or escalation | Bounded state-machine recovery, not open-ended planning |
| Physical object grounding | QR-bound asset identity | QR resolves `asset_id`; no localization stack |

### 2.3 Explicitly not implemented

AlphaNoah A1 v0.1 does not implement:

- ROS2;
- 3D spatial maps;
- robot navigation;
- robotic arm manipulation;
- VLA models;
- robot motion control;
- multi-robot coordination;
- embodied control.

The phrase “closed-loop” refers to maintenance result verification and work-order recovery, not physical robot control.

## 3. Inspiration: Early Grey-Space / Phantom Memory Ideas

### 3.1 System-engineering ideas retained

The early Grey-Space / Phantom Memory ideas are treated as conceptual prompts for a system memory design:

- layered memory rather than one unbounded context;
- surprise-driven retention translated into explainable event importance;
- tombstone-style archival that preserves a pointer to raw evidence;
- hydration of dormant records only when relevant;
- context isolation between physical assets;
- rhythm-aware maintenance as a future interval recommendation.

### 3.2 Engineering mapping

| Early concept | A1 system-level adaptation | Planned status |
|---|---|---|
| Surprise | Event Importance Score | Explainable deterministic factors; design only |
| L1/L2/L3 memory | Active task / recent events / long-term experience | Planned layered local stores |
| Tombstone | Summary, keywords and raw-record pointer | Planned compact inactive record |
| Hydration | Restore a complete historical maintenance event | Planned guarded retrieval |
| Context shift | QR-bound machine context isolation | Planned `asset_id` scope guard |
| Rhythm gate | Adaptive maintenance or inspection interval | Future research, outside initial demo |

The Event Importance Score uses Severity, Recurrence, Downtime Impact, Safety Impact, Novelty and Experience Value. Deterministic code calculates and explains it from validated facts and policy-versioned weights.

> A1's Event Importance Score is an explainable system-level score, not model-internal Surprise Attention.

### 3.3 Explicitly not implemented

The design does not implement or claim:

- Transformer modifications;
- Attention modifications;
- KV Cache movement across VRAM, RAM and SSD;
- gradient-reversible memory;
- new model training;
- parameter-level long-term memory;
- vLLM kernel changes.

Tombstone and hydration are record-management terms in A1. They do not describe changes to model weights, Attention or inference memory management.

## 4. Engineering References: LangChain and LangGraph

> A1 v0.1 does not use LangChain or LangGraph as a critical execution-path dependency, but it adapts useful engineering patterns established in Agent orchestration ecosystems.

### 4.1 Patterns informed by LangChain

- typed Tool definitions;
- schema-driven structured output;
- explicit input/output contracts;
- model-output validation;
- bounded format repair and retry;
- separation of model inference from deterministic tool effects.

In A1 these appear as typed maintenance Skills, schema-validated Incident/Assessment drafts, one format retry and deterministic state/write operations.

### 4.2 Patterns informed by LangGraph

- explicit workflow state;
- nodes and transitions;
- conditional branches;
- persistent checkpoints;
- human-in-the-loop interruption;
- resume after approval;
- task recovery after service restart;
- failure recovery;
- conditional replanning.

In A1 these appear as named work-order states, Skill steps, SQLite checkpoints, `waiting_information`/`waiting_confirmation`, and bounded close/reopen/escalate branches.

### 4.3 Lightweight v0.1 adaptation

The planned hackathon implementation uses:

- a deterministic Python state machine;
- Pydantic schemas;
- typed Skill interfaces;
- SQLite persistence;
- explicit approval gates;
- bounded retry;
- stable failure states;
- auditable transitions.

These components are planned, not yet implemented in this repository.

### 4.4 Why the frameworks are not introduced now

- the workflow is deliberately small;
- maintenance states and gates can be enumerated;
- behavior must be predictable, testable and auditable;
- the two-week schedule favors a smaller dependency surface;
- tool-calling reliability of the pinned local Ollama model still needs a recorded benchmark;
- the demo should expose the AlphaNoah maintenance Runtime rather than present a framework assembly.

### 4.5 Future LangGraph evaluation triggers

Evaluate a formal LangGraph adapter only when:

- work orders need to remain active across days;
- multiple asynchronous approval points exist;
- exact service-restart recovery becomes hard to maintain;
- multiple Skills require parallel execution and joins;
- compensation and rollback become complex;
- workflow branches grow materially;
- visual workflow operations become a requirement;
- custom state-machine maintenance cost exceeds adapter cost.

The domain objects must remain framework-independent even if a trigger is met.

The correct wording is:

```text
Inspired by LangChain and LangGraph patterns
```

It is not:

```text
Built with LangChain or LangGraph
```

## 5. AlphaNoah's Combined Adaptation

```text
QR Asset Identity
+
Asset Graph Memory
+
Typed Maintenance Skills
+
Closed-loop Verification
+
Importance-driven Event Memory
+
AMD ROCm Local Inference
```

> AlphaNoah A1 combines physical asset identity, typed operational Skills, closed-loop verification and importance-driven event memory in a local AMD ROCm edge runtime.

The combination is specific to the A1 maintenance scenario and constraints. The individual building blocks are not presented as first inventions by AlphaNoah.

The possible extension from these current software contracts to an embodied system is a **future direction**, not a v0.1 capability. See Future Is Robots? — From Enterprise Agent to Embodied Robot.

## 6. Engineering Translation Summary

| External inspiration or established pattern | A1 engineering translation | Deterministic control | Human boundary |
|---|---|---|---|
| Closed-loop Agent behavior | repair-result verification and reopen | verification criteria and transition guards | supplies physical outcome |
| Typed tools | typed maintenance Skill contracts | schema/precondition/effect checks | approves gated effects |
| Persistent Agent state | SQLite task/work-order checkpoints | state machine and idempotency | resumes approval/repair interaction |
| Memory hierarchy | asset-scoped L1/L2/L3 + raw archive | ranking, provenance and promotion policy | validates experience |
| Failure replanning | bounded retry, reopen or escalation | attempt budget and recovery table | selects/approves high-impact path |
| Physical grounding | QR to `asset_id` | identity validation and scope filters | confirms visible target |
| Local model service | replaceable `LocalModelProvider` | timeout, schema and health policy | does not delegate authority to model |

## 7. Planned v0.1 Scope

The architecture plans to demonstrate:

- one simulated QR-bound packaging machine (`PACK-003`);
- one local incident-understanding path through Ollama/ROCm;
- local retrieval from simulated history and simulated SOP material;
- typed Skill status and evidence;
- one human approval interruption;
- success and verification-failure branches;
- local event-memory update only after verification;
- AMD GPU/runtime/latency evidence and `Cloud API Calls: 0`.

## 8. Current Actual Scope

Historical baseline before the 2026-07-23 implementation:

- the repository contains the project skeleton and architecture documents;
- the AMD/Ollama observations are supplied single-machine audit results, not rerun here;
- no Agent runtime, Skill implementation, SQLite schema, QR resolver, memory engine, Provider adapter, demo UI or model is implemented in this repository;
- no LangChain, LangGraph, ROS2, vLLM or model-training dependency has been added.

Current state: the repository now implements an AlphaNoah-owned deterministic
runtime, one food-SOP Skill, SQLite persistence, human review, task/evidence/review
objects and an audit timeline. It still has no LangChain, LangGraph, HoloAgent,
ROCm Provider, robot or model-training dependency.

## 9. Reference Review Before Release

The official project and documentation links are maintained in [External Technical References](../references/REFERENCES.md). Before public release, a human reviewer should still:

- verify the preferred formal HoloAgent-0 citation, author list, and publication status;
- add the provenance or internal authorship note appropriate for the early Grey-Space / Phantom Memory ideas;
- record access dates or pinned versions for mutable LangChain and LangGraph documentation;
- confirm all required license and attribution notices.

Do not invent citation numbers or imply endorsement by those projects.
