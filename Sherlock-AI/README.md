# Sherlock AI

> **Find the Cause. Fix the Future.**

Sherlock AI is an evidence-driven, localized diagnostic platform designed for Windows systems. Traditional AI troubleshooting assistants often generate hallucinated fixes immediately upon receiving a user report. Sherlock AI flips this paradigm by adhering to a core engineering principle: **Investigate first, reason second.** 

Before making any assertions or recommending system changes, Sherlock AI formulates an investigation plan, executes diagnostic probes on local system hardware, gathers hard evidence, and structures a verifiable audit trail for system health analysis.

---

## Overview

When modern operating systems run slowly or exhibit unexpected behavior, users typically paste vague symptoms (e.g., "my PC is freezing") into LLM chat interfaces. Standard LLMs respond with generic, unverified lists of fixes without knowing the system's actual hardware state.

Sherlock AI acts as an autonomous diagnostic investigator. It receives a plain-language complaint, maps the reported symptoms to potential system subsystems, triggers dedicated diagnostic tools to gather system metrics, and constructs a structured evidence bundle. In its current implementation, it establishes the foundation for evidence-driven diagnostics by running deterministically on CPU and Memory subsystems, setting the stage for local LLM-based reasoning and AMD hardware acceleration.

---

## Problem Statement

1. **Hallucination in AI Diagnostics:** Generic LLMs offer speculative recommendations without ground-truth system telemetry.
2. **Context Blindness:** Standard chatbots lack direct visibility into real-time physical memory pressure, CPU core throttling, or system load metrics.
3. **Privacy Concerns:** Sending full system state dumps to cloud-hosted LLM endpoints exposes sensitive background process data and system configuration metadata.

---

## Why Sherlock AI is Different

* **Evidence-Driven Pipeline:** AI reasoning is strictly gated behind deterministic diagnostic probing. No recommendation is made without telemetry backing.
* **Non-Invasive Observation:** Collects structured system metrics via lightweight Python system interfaces without requiring permanent background agent daemons.
* **Local-First Architecture:** Designed from the ground up to execute diagnostics and reasoning locally, minimizing latency and protecting system privacy.
* **Modular Tooling:** Diagnostic modules are decoupled, allowing new probes (Disk, Network, GPU, Battery) to be registered without altering core orchestration logic.

---

## Features (Current MVP)

* **Keyword-Driven Investigation Planner:** Parses initial user reports to generate targeted subsystem investigation plans.
* **Deterministic Tool Manager:** Orchestrates parallel execution of system probes and normalizes output into a unified evidence format.
* **CPU Diagnostic Module:** Collects physical/logical core counts, real-time core utilization percentage, current clock frequency, and maximum rated frequency.
* **Memory Diagnostic Module:** Analyzes total RAM, available RAM, active memory consumption percentage, and virtual memory (swap) allocation.
* **Minimalist Developer UI:** High-contrast black, white, and gold React interface built with Tailwind CSS for clean telemetry visualization and evidence card tracking.
* **Rest API Backend:** FastAPI powered backend with full endpoint typing, RESTful request routing, and integrated Pytest test suites.

---

## Current Architecture
                          +-----------------------+
                       |  User Complaint (UI)  |
                       +-----------+-----------+
                                   |
                                   v
                       +-----------------------+
                       | FastAPI REST Interface|
                       +-----------+-----------+
                                   |
                                   v
                       +-----------------------+
                       | InvestigationPlanner  |
                       +-----------+-----------+
                                   |
                                   v
                       +-----------------------+
                       |      ToolManager      |
                       +-----------+-----------+
                                   |
                  +----------------+----------------+
                  |                                 |
                  v                                 v
        +-------------------+             +-------------------+
        |      CPUTool      |             |    MemoryTool     |
        | Cores/Usage/Freq  |             | RAM/Swap/Avail    |
        +---------+---------+             +---------+---------+
                  |                                 |
                  +----------------+----------------+
                                   |
                                   v
                       +-----------------------+
                       | Evidence Collection   |
                       +-----------+-----------+
                                   |
                                   v
                       +-----------------------+
                       | Investigation Report  |
                       +-----------------------+


---

## Folder Structure

```
sherlock-ai/
├── backend/
│   ├── app/
│   │   ├── api/
│   │   │   └── endpoints.py
│   │   ├── core/
│   │   │   └── config.py
│   │   ├── models/
│   │   │   └── evidence.py
│   │   ├── services/
│   │   │   ├── planner.py
│   │   │   └── tool_manager.py
│   │   ├── tools/
│   │   │   ├── base.py
│   │   │   ├── cpu_tool.py
│   │   │   └── memory_tool.py
│   │   └── main.py
│   ├── tests/
│   │   ├── test_planner.py
│   │   └── test_tools.py
│   ├── pytest.ini
│   └── requirements.txt
├── frontend/
│   ├── src/
│   │   ├── assets/
│   │   ├── components/
│   │   │   ├── EvidenceCard.tsx
│   │   │   ├── InvestigationForm.tsx
│   │   │   └── ResultsPanel.tsx
│   │   ├── types/
│   │   │   └── index.ts
│   │   ├── App.tsx
│   │   ├── index.css
│   │   └── main.tsx
│   ├── package.json
│   ├── tailwind.config.js
│   ├── tsconfig.json
│   └── vite.config.ts
├── .gitignore
├── LICENSE
└── README.md
```

---

## Technology Stack

### Frontend
* **Framework:** React 18 with TypeScript
* **Build Tool:** Vite
* **Styling:** Tailwind CSS (Custom Dark/Gold theme)
* **HTTP Client:** Native Fetch API

### Backend
* **Language:** Python 3.10+
* **Framework:** FastAPI
* **Data Validation:** Pydantic v2
* **System Metrics Interface:** `psutil`
* **Testing:** Pytest

---

## Installation & Setup

### Prerequisites
* Windows 10/11
* Python 3.10 or higher
* Node.js v18 or higher
* npm v9 or higher

### 1. Backend Setup

```bash
# Navigate to backend directory
cd backend

# Create virtual environment
python -m venv venv

# Activate virtual environment (Windows PowerShell)
.\venv\Scripts\Activate.ps1

# Install dependencies
pip install -r requirements.txt

# Run backend unit tests
pytest

# Start FastAPI development server
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000