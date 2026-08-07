# 🚀 CesarOps Forge 3 - AMD Hackathon Submission

> **Built with AMD Instinct MI25 GPUs | Optimized for ROCm**

## 🎥 Video Demonstration
**Watch the full system in action:** https://youtu.be/Zw_VXHxxPRA

## 📌 Quick Links
- **Landing Page**: github.com/festeraeb
- **Main Repository**: https://github.com/cesarops1/Cesarops-Inverence-engine
- **Branch**: `forge-v3-amd-integration`

## 🎯 What is Forge 3?

Forge 3 is a **distributed AI inference engine** built from the ground up for AMD GPUs. It features:

- ✅ **Real-time GPU fleet auto-discovery** across distributed nodes
- ✅ **Intelligent cognitive routing** via Paddler to specialized AI workers
- ✅ **Always-on architecture** with Ornith-35B on 2x AMD Instinct MI25
- ✅ **Self-healing mission dispatch** with automatic failover
- ✅ **Hybrid NIM/local inference** for production reliability

## 💻 Core Technology

| Component | Technology | Purpose |
|-----------|-----------|---------|
| **Engine** | Rust | High-performance inference server |
| **GPU Layer** | AMD ROCm | Hardware acceleration |
| **Inference** | llama.cpp | Quantized model execution |
| **Vector DB** | Qdrant | Semantic code search (Wayfinder) |
| **Routing** | Paddler | Cognitive worker orchestration |

## 🏗️ Architecture Overview

### Primary Node: T440
- **2x AMD Instinct MI25** (P100-equivalent, 40GB VRAM)
- **Ornith-1.0-35B** in Q5_K_M quantization
- Role: Always-on coder / "Thomas Translator"
- Status: ✅ Continuous operation

### Distributed Workers
- **CesarOps-3**: Gemma-4-E4B (IQ4) on RTX 2060
- **Sapphire**: Nemotron-Ultra-4B via NIM API + local fallback
- **RTX 4090**: Hermes-3-Llama-3.1-8B (on-demand)

### Paddler Routing Intelligence
Routes requests based on:
1. **Mission type**: code_generation, review, debugging, architecture
2. **GPU availability**: Real-time health and load monitoring
3. **Model qualification**: Evidence-based capability scoring
4. **Fallback logic**: Automatic failover on timeout/error

## 📂 Where's The Code?

**Core Forge Engine:**
```
forge/src/
├── main.rs              # Primary inference HTTP server
├── agent_dispatch.rs    # Mission routing & agent coordination
├── loop_engine.rs       # Self-healing execution loop
├── hardware.rs          # GPU discovery & health monitoring
├── cluster_store.rs     # Distributed state management
└── forge_adapter.rs     # Mission spec compatibility
```

**Web Dashboards:**
```
forge/src/
├── wall.html           # Fleet monitor with GPU auto-discovery
├── dispatch.html       # Mission queue & Ornith integration
├── chat.html          # Direct Ornith cognitive interface
└── qualification_lab.html  # Model qualification scorecards
```

## 🚀 Quick Start

```bash
# Clone the repository
git clone https://github.com/cesarops1/Cesarops-Inverence-engine.git
cd Cesarops-Inverence-engine
git checkout forge-v3-amd-integration

# Build Forge 3
cd forge
cargo build --release

# Run the inference server
./target/release/cesarops-forge-v2 --port 9100

# Access web interface
open https://cesarops.com/wall
```

## 🎬 Video Highlights

The demonstration video shows:
1. **Fleet auto-discovery** detecting AMD GPUs across nodes
2. **Real-time monitoring** of temperature, utilization, VRAM
3. **Mission dispatch** routing to Ornith on T440
4. **Qualification lab** showing model performance scorecards
5. **Paddler routing** with automatic failover logic

## 🧠 Why This Matters

This isn't just another LLM wrapper. Forge 3 demonstrates:

- **Production-grade architecture**: Self-healing, monitored, distributed
- **AMD-first optimization**: Built specifically for Instinct MI25/ROCm
- **Real engineering**: Fleet management, vector search, cognitive routing
- **Proven in production**: Already handling real workloads on T440

## 📝 Development Notes

**Primary Development**: Human engineer with deep systems background
**AI Assistance**: Kiro agent (via Kiro IDE) for UI standardization only

The core Forge logic, Rust implementation, ROCm integration, distributed architecture, and all algorithmic work are **100% original human engineering**. AI assistance was limited to:
- Cleaning up UI styling inconsistencies from a previous Gemini session
- Creating submission documentation
- Git workflow organization

**Previous Issue**: Gemini Pro hallucinated a complete fake wall.html page with simulated data during an earlier session. This has been corrected and the real implementation is shown in the video.

## 🏆 AMD Hackathon Relevance

This project showcases:
- ✅ Real AMD GPU utilization (Instinct MI25 / P100-equivalent)
- ✅ ROCm stack integration
- ✅ Distributed inference optimization
- ✅ Production-ready architecture
- ✅ Novel cognitive routing approach
- ✅ Self-healing and auto-discovery capabilities

## 📧 Contact

Questions? Watch the video or examine the core source files listed above.

---

**Submission Date**: August 7, 2026  
**AMD Hardware**: 2x Instinct MI25 (T440 primary node)  
**Video**: https://youtu.be/Zw_VXHxxPRA  
**Landing**: github.com/festeraeb
