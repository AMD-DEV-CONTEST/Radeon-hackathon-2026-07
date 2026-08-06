# Project Specification: SentinelDesk

**Track:** Track 2: Agentic AI (AMD AI DevMaster Hackathon)

## 1. Project Overview
SentinelDesk is a fully local, autonomous AI copilot that assists users with system tasks while running entirely on-device. By utilizing PyTorch tailored for AMD ROCm, it guarantees privacy, zero latency to external servers, and maximum utilization of AMD Radeon hardware.

## 2. Architecture Diagram

```mermaid
graph TD
    User([User]) <-->|Text Input/Output| MainOrchestrator[Main Orchestrator (main.py)]
    MainOrchestrator <-->|Retrieve/Store Context| ChromaDB[(ChromaDB Vector DB)]
    MainOrchestrator <-->|Parse Intent & Execute| Tools[Tool Executor]
    MainOrchestrator <-->|Generate Response| LLMEngine[ROCm LLM Engine]
    
    Tools --> SysDiag[System Diagnostics]
    Tools --> FileMan[File Management]
    
    LLMEngine --> PyTorch[PyTorch backend]
    PyTorch --> ROCm[AMD ROCm Driver]
    ROCm --> GPU[AMD Radeon GPU]
```

## 3. Optimization Strategies for AMD Radeon GPUs
To maximize performance on AMD hardware, SentinelDesk employs the following strategies:

1. **ROCm-Native PyTorch:** Utilizes PyTorch wheels explicitly compiled against ROCm 6.0+, bypassing any abstraction overhead.
2. **FP16 Inference:** The LLM Engine automatically casts models to `torch.float16` when a ROCm-compatible CUDA device is detected, effectively halving memory bandwidth requirements and doubling throughput on supported RDNA/CDNA architectures.
3. **Device Mapping:** Leverages HuggingFace `accelerate` with `device_map="auto"` to automatically and optimally partition model layers across available VRAM.
4. **Lightweight Embedding Storage:** ChromaDB runs directly in-process and persists locally, minimizing IPC overhead compared to separate database instances.
