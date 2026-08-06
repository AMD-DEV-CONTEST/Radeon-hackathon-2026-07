# ForgeAI

**Track:** Track 2 – Development & Local Deployment of Private AI Agents

**Participant:** Abhishek Herbert Samuel

---

## Project Overview

ForgeAI is a private engineering intelligence platform that transforms software feature requests into evidence-backed Engineering Decision Packages (EDPs).

Instead of generating a single AI response, ForgeAI executes a deterministic multi-agent workflow that:

- Performs requirement discovery
- Requests clarifications when information is missing
- Retrieves project knowledge
- Generates an architecture proposal
- Performs an independent engineering critique
- Revises the proposal
- Validates outputs
- Produces a durable Engineering Decision Package with provenance

---

## Motivation

Modern software engineers spend significant time understanding requirements, reviewing documentation, validating assumptions, and producing implementation plans before writing code.

ForgeAI augments this process by structuring engineering reasoning into a transparent, reproducible workflow grounded in project evidence.

---

## Core Capabilities

- Multi-agent engineering workflow
- Clarification-driven discovery
- Project-aware retrieval
- Trusted evidence reconstruction
- Architecture generation
- Independent critique and revision
- Deterministic validation
- Engineering Decision Package generation
- JSON & Markdown export
- Complete provenance tracking

---

## Workflow

Feature Request

↓

Discovery

↓

Retrieval

↓

Evidence

↓

Solution

↓

Critique

↓

Revision

↓

Validation

↓

Engineering Decision Package

---

## Technology Stack

Backend

- Python 3.12
- FastAPI
- SQLite FTS5
- Pydantic

Frontend

- React
- TypeScript

LLM

- Provider-neutral OpenAI-compatible interface

---

## AMD AI Integration

ForgeAI uses a provider-neutral architecture capable of integrating OpenAI-compatible model providers.

The project specification describes the deployment approach and AMD-focused deployment considerations. The architecture is designed so that inference providers can be replaced without modifying the engineering workflow.

---

## Repository

https://github.com/AbhishekHerbertSamuel/forgeai

---

## Included Deliverables

- Project Specification (PDF)
- Presentation (PDF/PPT)
- Source Code Repository
- Demonstration Video

---

## Demo Video

<YouTube Unlisted Link>

---

Thank you for reviewing ForgeAI.
