# CesarOps & Forge 3 - AMD Hackathon Submission

## Project Overview
**CesarOps Forge 3** is a distributed AI inference engine optimized for AMD GPUs, featuring autonomous fleet management, cognitive worker routing via Paddler, and self-healing mission dispatch capabilities.

## Video Demonstration
🎥 **Watch the full demo:** https://youtu.be/Zw_VXHxxPRA

## Key Features
- **Fleet Auto-Discovery**: Automatic detection and configuration of AMD GPUs across distributed nodes
- **Cognitive Routing**: Paddler-based intelligent routing to specialized AI workers (Ornith, Hermes, Nemotron)
- **Always-On Architecture**: Ornith-35B running continuously on 2x AMD Instinct MI25 (P100-equivalent) GPUs
- **Self-Healing Missions**: Automatic failover and NIM API integration with local fallback
- **Vector Search Integration**: Qdrant-based wayfinder for codebase navigation and context retrieval

## Core Technology Stack
- **Rust** - High-performance inference engine
- **AMD ROCm** - GPU acceleration layer
- **llama.cpp** - Quantized model inference (Q5_K_M, IQ4)
- **Qdrant** - Vector database for semantic search
- **NIM API** - Hybrid cloud/local inference with automatic failover

## Architecture Highlights

### 1. Fleet Management (T440 Primary Node)
- **2x AMD Instinct MI25** (P100-equivalent, 40GB total VRAM)
- **Ornith-1.0-35B-Q5_K_M**: Always-on coder/Thomas translator role
- Real-time health monitoring (temp, utilization, VRAM)
- Role-based GPU grouping with priority scheduling

### 2. Distributed Worker Nodes
- **CesarOps-3 Node**: Gemma-4-E4B in IQ4 quant (2060, 6GB)
- **Sapphire Node**: Nemotron-Ultra-4B via NIM with local fallback
- **RTX 4090 Node**: Hermes-3-Llama-3.1-8B (on-demand thinker role)

### 3. Paddler Routing System
Intelligent request routing based on:
- Mission type (code generation, review, debugging, architecture)
- GPU availability and load
- Model specialization and qualification scores
- Automatic failover on timeout or error

## Core Forge Logic Location
The primary Forge 3 engine code resides in:
```
forge/src/main.rs          - Main inference engine and HTTP server
forge/src/agent_dispatch.rs - Mission routing and agent coordination
forge/src/loop_engine.rs    - Self-healing execution loop
forge/src/hardware.rs       - GPU discovery and health monitoring
forge/src/cluster_store.rs  - Distributed state management
forge/src/forge_adapter.rs  - Mission spec compatibility layer
```

## Web Interface
Landing page for judges: **github.com/festeraeb**

Interactive dashboards:
- `/wall` - Fleet monitor with GPU auto-discovery
- `/dispatch` - Mission queue and Ornith integration
- `/chat` - Direct Ornith cognitive interface
- `/qualification-lab` - Model qualification scorecards

## What This Submission Demonstrates
1. **AMD GPU Optimization**: Full ROCm stack utilization with real-time monitoring
2. **Distributed Intelligence**: Multi-node fleet coordination with automatic discovery
3. **Production-Ready**: Self-healing architecture with NIM hybrid deployment
4. **Cognitive Workflows**: Specialized AI workers for code generation, review, and architecture

## Development Note
This submission was prepared with assistance from **Kiro AI Agent** to clean up UI inconsistencies from previous Gemini-generated hallucinations. The core Forge logic, fleet management, and distributed inference engine were developed by the human submitter. Kiro's role was limited to:
- Standardizing UI styling across dashboard pages
- Creating this submission document
- Organizing the git push workflow

**All core algorithmic work, Rust implementation, ROCm integration, and architectural decisions are original human work.**

## Repository Structure
```
cesarops_push/
├── forge/                  # Core Forge 3 engine
│   ├── src/               # Rust source code
│   │   ├── main.rs        # Primary inference server
│   │   ├── agent_dispatch.rs
│   │   ├── loop_engine.rs
│   │   ├── hardware.rs
│   │   └── ...
│   ├── target/            # Compiled binaries
│   └── Cargo.toml
├── paddler/               # Routing configuration
├── qdrant/                # Vector search data
└── AMD_HACKATHON_SUBMISSION.md (this file)
```

## Running Forge 3
```bash
cd forge
cargo build --release
./target/release/cesarops-forge-v2 --port 9100
```

Access dashboards at `http://localhost:9100/wall`

## Contact
For questions about this submission, refer to the video demonstration or examine the core logic files listed above.

---

**Submission Date**: August 7, 2026  
**Primary GPU Target**: AMD Instinct MI25 (2x on T440)  
**Framework**: Rust + ROCm + llama.cpp  
**Demonstration**: https://youtu.be/Zw_VXHxxPRA
