# Future is Robots

> **Status: VISION / PLANNED**
>
> This document describes future direction, not completed Hackathon
> capabilities.

## Direction

AlphaNoah currently provides a software-only Industrial Agent Runtime. It
accepts bounded problem context, invokes an explicitly selected AI Provider,
validates structured output, persists workflow state, and keeps human control
visible.

The longer-term direction is:

```text
Today
Industrial Agent

Future
Industrial Agent
    -> Sensors
    -> Vision
    -> Equipment Data
    -> Physical AI
```

This progression does not mean connecting a model response directly to a
machine. Physical systems require deterministic authorization, safety
interlocks, validated control interfaces, failure handling, and evidence.

## The Context Layer

Robots and industrial agents need more than a model. They need:

- **context** — the asset, location, process, operating condition, and current
  objective;
- **rules** — safety, quality, maintenance, and authorization constraints;
- **memory** — previous Events, decisions, actions, evidence, and outcomes;
- **operational experience** — enterprise-approved procedures and reviewed
  lessons from prior work.

AlphaNoah is intended to explore an intelligence and context layer connecting:

```text
Human
    + Industrial Environment
    + AI Agent
    + Future Robots
```

Humans remain the authority for consequential actions. The industrial context
layer should make it possible to identify what the system knew, which rules
applied, who approved an action, and what happened afterward.

## Current Foundation

The Public Hackathon Repository currently contains:

- a persisted Event and workflow Runtime;
- explicit state-transition rules;
- bounded Skill and JSON knowledge context;
- structured Provider output guards;
- mandatory human-review controls;
- SQLite audit history;
- read-only Digital Employee projections;
- an explicitly configured local Ollama path.

These are software foundations. They are not production robotics, sensor
integration, vision validation, equipment control, or safety-certified
automation.

## Planned Layers

### 1. Industrial context

Possible future work includes normalized asset identity, operating envelopes,
maintenance history, process state, and enterprise-approved procedures.

### 2. Sensor and vision inputs

Future adapters may accept reviewed telemetry, camera-derived observations, or
equipment data. Such inputs would need provenance, timestamps, quality checks,
privacy controls, and explicit missing-data behavior.

### 3. Specialized Digital Employees

Future Digital Employees could represent equipment maintenance, safety
inspection, or quality assistance. Each scenario would require its own Skills,
knowledge boundary, responsibility mapping, tests, and target-environment
validation.

### 4. Physical AI

Any movement from recommendations to physical action would require a separate
control architecture, including authorization, interlocks, safe-state
behavior, simulation, emergency stop, hardware-specific validation, and
applicable certification. A model response alone must never become an actuator
command.

## Engineering Principles

1. Keep the deployment and data boundary explicit.
2. Surround probabilistic inference with deterministic state and validation.
3. Preserve human authority for consequential actions.
4. Require implementation and target-host evidence before claiming support.
5. Keep industrial context independent of any single model or orchestration
   library.

The current purpose-built Runtime may later use mature Agent infrastructure
for generic orchestration or integration work. The intended long-term value is
the industrial context and capability layer, not a replacement for a general
Agent Framework.

## Non-Claims

This Vision does not claim that the Hackathon release provides:

- production sensors or camera ingestion;
- computer-vision analysis;
- robotics or autonomous equipment control;
- long-term experiential memory;
- safety-certified decisions;
- production fleet management.

Each item requires separate implementation, testing, operational review, and
target-hardware evidence.
