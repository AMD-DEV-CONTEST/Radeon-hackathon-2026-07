# GPU Guardian AI

## Agentic AI System Health Assistant powered by AMD ROCm

GPU Guardian AI is an AI-powered infrastructure health assistant that combines real-time system telemetry, deterministic diagnostics, and a locally deployed Large Language Model (LLM) to explain system behavior in natural language while leveraging AMD Radeon GPUs through ROCm.

---
# AMD Radeon AI Hackathon 2026

**Track:** Development & Local Deployment of Private AI Agents (Agentic AI)

GPU Guardian AI demonstrates how Agentic AI can simplify infrastructure monitoring by transforming raw system telemetry into meaningful operational insights.

Instead of requiring users to manually interpret CPU usage, GPU metrics, memory statistics, or system reports, the assistant understands natural language questions and provides concise, context-aware explanations.

---
## Demo Video

Repository Location:

demo/GPU_Guardian_AI_Demo.mp4

Uploaded to Youtube :
https://www.youtube.com/watch?v=bFPeMgYMlH8

## Docs

## Documentation

- `docs/GPU_Guardian_AI_Hackathon_Presentation.pdf`
- `docs/GPU_Guardian_AI_Hackathon_Presentation.png`


# Application Preview

> Replace these placeholders with screenshots from your final demo.

## Startup Screen

![Startup](images/startup.png)

## Interactive CLI

![CLI](images/cli.png)

## Overall Health Report

![Overall Health](images/overall.png)

---

# Problem Statement

Modern infrastructure monitoring tools expose thousands of performance metrics but still require significant expertise to interpret them.

Typical challenges include:

- Understanding GPU utilization
- Diagnosing CPU bottlenecks
- Identifying resource contention
- Explaining overall system health
- Translating raw telemetry into actionable recommendations

System administrators often spend valuable time correlating multiple dashboards before identifying the root cause of an issue.

GPU Guardian AI addresses this challenge by acting as an intelligent AI assistant capable of reasoning over infrastructure telemetry and responding in natural language.

---

# Solution Overview

GPU Guardian AI combines:

- Real-time telemetry collection
- Intelligent diagnosis engine
- Rule-based deterministic responses
- Context-aware LLM reasoning
- Agent orchestration
- AMD ROCm accelerated local inference

The system intelligently decides when deterministic reasoning is sufficient and when LLM reasoning is actually required, minimizing hallucinations while improving response quality.

---

# Key Features

## Agentic AI Workflow

- Supervisor Agent
- Intent Classification
- Context-aware Prompt Builder
- Local LLM Inference
- Rule-based Response Engine

---

## Infrastructure Monitoring

- GPU Monitoring
- CPU Monitoring
- Memory Monitoring
- Disk Monitoring
- Network Monitoring
- ROCm Detection

---

## Intelligent Diagnostics

GPU Guardian AI automatically identifies:

- GPU Health
- CPU Health
- Memory Health
- Disk Health
- Network Health
- Overall System Health

---

## Professional CLI Experience

- Live hardware dashboard
- Colorized terminal interface
- Structured reports
- Natural language interaction
- Real-time telemetry summary

---

## AI Capabilities

GPU Guardian AI understands questions such as:

- Why is my GPU idle?
- How is my CPU?
- Is my memory healthy?
- Explain my overall system health.
- What should I do?
- Is ROCm installed?
- Is my network healthy?

---

# Hybrid AI Architecture

GPU Guardian AI intelligently selects the most appropriate reasoning engine.

Simple monitoring questions are answered using deterministic rules.

Complex reasoning questions are answered using the local Large Language Model.

```

```text
User Question
      |
      V
Intent Classifier
      |
      +----------------------------+
      |                            |
      V                            V

Rule Engine                 Context Builder
(Deterministic)                  |
                                 V

                         Local LLM (Qwen2.5)

                                 |
                                 V

                         Final Response
```

Benefits:

- Faster responses
- Zero hallucinations for factual questions
- Lower GPU utilization
- Predictable monitoring responses

Examples:

- GPU Status
- CPU Status
- Memory Status
- Disk Status
- Network Status
- ROCm Detection
- Overall System Health

---

# Context-aware LLM

Complex reasoning questions use:

- Intent Classification
- Context Filtering
- Optimized Prompt Engineering

Instead of sending the complete health report to the model, GPU Guardian AI only sends the relevant sections required to answer the user's question.

Benefits include:

- Improved accuracy
- Better response quality
- Lower token usage
- Faster inference

---

# System Architecture

```text
                        User
                         |
                         V

                 Supervisor Agent
                         |
                         V

              Intent Classification
                         |
                         V

                 Context Builder
                         |
          +-------------------------------+
          |                               |
          V                               V

 Rule Response Engine               Local LLM
  (Deterministic)               Qwen2.5-3B-Instruct

          |                               |
          +---------------+---------------+
                          |
                          V

                   Final Response
                          ^
                          |
           Intelligent Diagnosis Engine
                          ^
                          |
      GPU   CPU   Memory   Disk   Network
                          ^
                          |
                   ROCm Telemetry
```

---

# AI Workflow

```text
User Question
      |
      V

Intent Classifier
      |
      +------------------------+
      |                        |
      V                        V

Rule Engine             Context Builder
      |                        |
      |                        V
      |                 Local LLM
      |                        |
      +------------+-----------+
                   |
                   V

             Final Response
```
# Technology Stack

## Artificial Intelligence

- Qwen2.5-3B-Instruct
- Hugging Face Transformers
- PyTorch

---

## AMD Technologies

- AMD Radeon GPU
- ROCm 7.2
- ROCm Runtime
- ROCm SMI

---

## Python Libraries

- Transformers
- Accelerate
- Torch
- psutil
- Gradio

---

# AMD ROCm Integration

GPU Guardian AI performs all AI inference locally using AMD ROCm.

Capabilities include:

- GPU Detection
- ROCm Runtime Validation
- GPU Telemetry Collection
- GPU Health Analysis
- Local LLM Inference

The project executes entirely on AMD Radeon GPUs without relying on external cloud inference APIs.

---

# Project Structure

```text
gpu-guardian-ai/

├── README.md
├── requirements.txt
├── demo/
│   └── GPU_Guardian_AI_Demo.mp4
├── docs/
│   ├── GPU_Guardian_AI_Hackathon_Presentation.pdf
│   └── GPU_Guardian_AI_Hackathon_Presentation.png
└── src/
    ├── main.py                 # CLI application entry point
    ├── app.py                  # Gradio dashboard
    │
    ├── config/
    │   ├── __init__.py
    │   └── settings.py         # Project configuration
    │
    ├── agents/
    │   ├── __init__.py
    │   └── supervisor.py       # Main orchestration agent
    │
    ├── llm/
    │   ├── __init__.py
    │   ├── loader.py           # Loads local LLM
    │   └── inference.py        # LLM inference pipeline
    │
    ├── tools/
    │   ├── __init__.py
    │   ├── gpu_tool.py
    │   ├── cpu_tool.py
    │   ├── memory_tool.py
    │   ├── disk_tool.py
    │   ├── network_tool.py
    │   │
    │   ├── health_tool.py
    │   ├── cpu_health_tool.py
    │   ├── memory_health_tool.py
    │   ├── disk_health_tool.py
    │   ├── network_health_tool.py
    │   ├── system_health_tool.py
    │   │
    │   ├── diagnosis_tool.py
    │   ├── recommendation_tool.py
    │   ├── insight_tool.py
    │   ├── rule_response_tool.py
    │   └── question_classifier.py
    │
    └── utils/
        ├── __init__.py
        ├── banner.py
        ├── dashboard.py
        ├── colors.py
        ├── context_builder.py
        ├── intent_classifier.py
        ├── question_type.py
        └── report_formatter.py

```

---

# Installation

```bash
git clone https://github.com/vishardsankhyan/gpu-guardian-ai.git

cd gpu-guardian-ai

python -m venv gpu_guardian_env

source gpu_guardian_env/bin/activate

pip install -r requirements.txt
```

---

# Running the Application

## Interactive CLI

```bash
python src/main.py
```

or use the demo launcher

```bash
alias initiate_guardian="python src/main.py"

initiate_guardian
```

---

## Gradio Dashboard

```bash
python src/app.py
```

---

# Sample Session

```text
GPU: Idle | CPU: Healthy | Memory: Healthy | Disk: Healthy | Network: Healthy

GPU Guardian AI > Why is my GPU idle?

GPU Summary
────────────────────────────────────────

Your GPU is currently idle (0% utilization).

Reason
────────────────────────────────────────

No AI inference workload is currently running.

Status
────────────────────────────────────────

Healthy

Recommendation
────────────────────────────────────────

No action required.
```

---

# Example Questions

- Explain my system health.
- Why is my GPU idle?
- How is my CPU?
- Is my memory healthy?
- Is my disk healthy?
- Is my network healthy?
- Is ROCm installed?
- What should I do?
- Give me recommendations.
- Summarize my system health.

---

# Project Highlights

- Agentic AI Architecture
- Hybrid Rule Engine + Local LLM
- Intent-aware Context Filtering
- Deterministic Response Engine
- Local LLM Inference (Qwen2.5-3B)
- AMD ROCm GPU Acceleration
- Real-time Hardware Monitoring
- Interactive CLI Dashboard
- Explainable AI Diagnostics
- Colorized Terminal Interface
- Modular & Extensible Architecture
- Zero Cloud Inference

---

# Current Limitations

The project includes a Gradio-based monitoring dashboard (`src/app.py`).

During development, the AMD Radeon Hackathon cloud environment restricted localhost port forwarding, disabled SSH tunneling, and did not provide Jupyter proxy forwarding.

As a result, the web dashboard could not be demonstrated inside the hosted environment, although it runs correctly in a standard local Python environment.

---

# Future Roadmap

- Multi-agent collaboration
- Predictive failure detection
- Historical trend analysis
- Log analysis
- RAG-based troubleshooting
- Multi-node monitoring
- Automatic remediation
- Alert generation
- Exportable health reports
- Dashboard enhancements
- Support for additional hardware accelerators

---

# Acknowledgements

This project was developed for the **AMD Radeon AI Hackathon 2026** using AMD Radeon GPUs and ROCm.

Special thanks to the AMD Developer Relations team for providing the GPU cloud environment and supporting open AI development on AMD hardware.

---

# Author

**Vishard Sankhyan**

GPU Guardian AI • AMD Radeon AI Hackathon 2026

---

## License

This project is intended for educational, research, and hackathon demonstration purposes.


