# ForgeAI

**AMD AI DevMaster Hackathon 2026**

**Track:** Track 2 – Development & Local Deployment of Private AI Agents

**Participant:** Abhishek Herbert Samuel

---

# Project Overview

ForgeAI is a private engineering intelligence platform that transforms software feature requests into evidence-backed Engineering Decision Packages (EDPs).

Instead of producing a single AI response, ForgeAI executes a deterministic multi-agent workflow that:

- Performs requirement discovery
- Requests clarifications when information is incomplete
- Retrieves project knowledge
- Selects trusted supporting evidence
- Generates an implementation-ready architecture proposal
- Performs an independent engineering critique
- Revises the proposed solution
- Validates workflow outputs
- Produces a durable Engineering Decision Package with complete provenance

---

# Motivation

Software engineers spend considerable time understanding requirements, reviewing documentation, validating assumptions, and planning implementations before writing code.

ForgeAI augments this engineering process by structuring AI reasoning into a transparent, evidence-backed, reproducible workflow that supports engineering decision-making rather than replacing it.

---

# Core Capabilities

- Deterministic multi-agent workflow
- Clarification-driven requirement discovery
- Project-aware document retrieval
- Trusted evidence reconstruction
- Architecture proposal generation
- Independent critique and revision
- Structured validation
- Engineering Decision Package generation
- JSON and Markdown export
- Complete provenance tracking

---

# Workflow

```
Feature Request
        │
        ▼
   Discovery
        │
        ▼
   Retrieval
        │
        ▼
    Evidence
        │
        ▼
    Solution
        │
        ▼
     Critique
        │
        ▼
     Revision
        │
        ▼
    Validation
        │
        ▼
Engineering Decision Package
```

---

# Technology Stack

### Backend

- Python 3.12
- FastAPI
- SQLite (FTS5)
- Pydantic

### Frontend

- React
- TypeScript

### AI Layer

- Provider-neutral OpenAI-compatible interface

---

# AMD AI Integration

ForgeAI is designed with a provider-neutral architecture that supports OpenAI-compatible inference providers.

The submitted project specification describes the local deployment approach, AMD deployment considerations, and future deployment pathways while preserving the same deterministic engineering workflow.

---

# Submission Materials

## Project Specification

https://github.com/AbhishekHerbertSamuel/Radeon-hackathon-2026-07/blob/main/Track2-AbhishekHerbertSamuel-ForgeAI/ForgeAI-Project-Specification-AMD-Track-2.pdf

## Presentation Deck

https://github.com/AbhishekHerbertSamuel/Radeon-hackathon-2026-07/blob/main/Track2-AbhishekHerbertSamuel-ForgeAI/ForgeAI_AMD_Track2_Pitch_Deck.pdf

## Source Code Repository

https://github.com/AbhishekHerbertSamuel/forgeai

## Demonstration Video

https://youtu.be/IrvKjZPcBGk

---

# Thank You

Thank you for taking the time to review ForgeAI. I hope you enjoy exploring the project and its engineering workflow.
