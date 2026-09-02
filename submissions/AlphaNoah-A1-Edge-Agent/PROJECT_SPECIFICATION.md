# AlphaNoah A1 Edge Agent — Project Specification

- **Hackathon Track:** Track 2 — Development & Local Deployment of Private AI Agents
- **Team:** AlphaNoah
- **Participant:** 陈彬 (Chen Bin)
- **Role:** Project Lead and Primary Developer

## 1. Project Overview

AlphaNoah A1 Edge Agent is a local-first industrial AI workflow for equipment
troubleshooting. It converts a bounded equipment problem report into local AI
analysis, a structured preliminary diagnosis, recommended actions, and a
mandatory human-review state.

The AI Provider performs advisory analysis. Deterministic Runtime logic owns
Event intake, capability selection, workflow state, output validation,
persistence, and the human-review boundary. AlphaNoah does not generate
device-control commands or perform physical repair.

## 2. Application Scenario

AlphaNoah is designed as an industrial equipment troubleshooting workflow. An
operator reports a bounded equipment problem, the local Runtime selects the
applicable troubleshooting capability and reviewed knowledge context, and a
local AI Provider returns a structured preliminary analysis for validation and
human review.

The Hackathon demonstration uses air-conditioner troubleshooting as a bounded
validation scenario. This controlled validation asset demonstrates the
workflow without defining the complete product scope. AlphaNoah is not limited
to air conditioners as a product concept, but no additional equipment scenario
is claimed as verified in this submission.

## 3. Agent Architecture

```text
Operator
  ↓
Local User Interface
  ↓
Bounded Event
  ↓
AlphaNoah Runtime
  ├── Capability Resolution
  ├── Knowledge Context
  ├── SQLite State & Audit
  └── Local AI Provider
  ↓
Structured Result
  ↓
Runtime Validation
  ↓
Human Review
```

The Runtime is the deterministic control boundary. It resolves a capability,
assembles bounded and reviewed context, calls the explicitly configured local
AI Provider, validates the returned structured contract, persists state and
audit history in SQLite, and exposes the result for human review.

## 4. Core Capabilities

The verified Hackathon capabilities are:

- Event intake
- Deterministic capability resolution
- Reviewed local knowledge context
- Local AI structured analysis
- Output validation
- SQLite audit trail
- Human review workflow
- Read-only Digital Employee projection

The Digital Employee view is a human-understandable projection of persisted
Runtime facts. It is not an autonomous worker or a second workflow engine.

## 5. Model and Local Deployment

The submitted local inference path was validated with the following
environment:

| Component | Validated configuration |
|---|---|
| Processor | AMD Ryzen AI Max+ 395 |
| Graphics | AMD Radeon 8060S |
| GPU target | `gfx1151` |
| Compute stack | ROCm 7.2 |
| Local model service | Ollama 0.20.3 |
| Model | `qwen3.5:9b` |

The demonstrated inference path runs locally through Ollama. Provider
selection is explicit, and an unavailable configured Provider does not
silently fall back to a synthetic Fake provider.

This is an integration validation record, not a performance benchmark.

## 6. AMD Radeon Adaptation / Optimization Description

The AMD Radeon integration focuses on making the local inference path bounded,
predictable, and reviewable. The engineering choices include:

- **Bounded context input:** only the applicable Event, capability, and
  reviewed troubleshooting knowledge are sent for analysis.
- **Deterministic capability selection:** Runtime logic selects the capability
  before inference instead of asking the model to discover an open-ended tool
  path.
- **Fixed structured output contract:** the Provider response must satisfy a
  predefined schema before the workflow can advance.
- **Local inference path:** Ollama serves `qwen3.5:9b` locally on the validated
  AMD Radeon / ROCm environment.
- **Reduced unnecessary model exploration:** the task, context, and expected
  output are constrained to the current troubleshooting Event.

These choices describe integration and workflow engineering. No comparative
performance benchmark is claimed.

## 7. Scope and Limitations

The Hackathon submission does not include or claim:

- Automatic repair
- Device control
- Autonomous operation
- Production sensor integration
- Production fleet management

The demonstrated diagnosis is preliminary and advisory. It cannot confirm a
physical root cause, replace an on-site inspection, or authorize an equipment
action. Human review remains mandatory.
