[← Back to README](README.md)

# Security Policy

This document outlines the security model, trust assumptions, and mitigation mechanisms implemented in **VTE (Vector Tensor Engine)** to ensure stable execution and hardware safety.

> [!NOTE]
> **VTE is an open-source, educational project developed for learning, experimentation, and academic coding challenges.** It is designed as a lightweight, from-scratch implementation of an LLM inference motor using AMD's HIP SDK on Windows, and should be treated as a study reference rather than a production-hardened environment.

---

## 1. Threat Model

VTE operates under the assumption of a local execution environment.

### Untrusted Inputs
* **`.gguf` files**: The only input to this project that is treated as genuinely **untrusted**. Malicious GGUF files can contain corrupted headers, invalid offsets, or mutated tensors designed to cause buffer overflows, memory leaks, or GPU driver crashes.

### Trusted Components
* **IPC Commands**: The communication pipeline between the User Interface (UI) and the engine (`motor.py`) assumes a local-only threat model. The channel is local-only and not designed to cross a network boundary.
* **Compilation Environment**: The generation and compilation of HIP C++ kernels (`hipcc`) assumes that the local operating system and the installed compiler toolchain are secure and trusted.

---

## 2. Implemented Defense Mechanisms

To mitigate the risks of executing custom native code directly on the GPU, VTE implements the following safety layers:

### A. Dual-Layer GGUF Validation
Before any tensor data is loaded into physical VRAM or mapped into compute graphs, the `.gguf` file undergoes two verification steps:
1. **`GGUFSanitizer`**: Performs structural integrity checks, validating magic bytes (`GGUF`), format version, file size bounds, and caps on tensor and key-value counts.
2. **`GGUFParser`**: Validates the offsets and sizes of each tensor to ensure they do not point outside the physical file bounds, preventing out-of-bounds read vulnerabilities.

### B. VRAM Sandboxing (`SlabAllocator`)
To avoid memory fragmentation and illegal memory accesses that could cause segment faults or Blue Screens of Death (BSOD) at the GPU driver level:
* All memory required for weights, intermediate states, and the KV Cache is pre-allocated inside a single, contiguous memory pool (the **Slab Pool**).
* Sub-allocations (like the **Activation Arena**) are managed internally using strict offsets and boundary checking against the main Slab.
* Any request exceeding the pre-allocated bounds triggers a fail-fast error (`HIPSafetyError`) inside VTE, preventing invalid operations from reaching the GPU.

### C. Hardware Safety (Watchdog & Guard)
Custom GPU kernel executions are monitored in real time:
* **Kernel Watchdog**: Tracks active GPU execution times. If a kernel gets stuck in an infinite loop or blocks the execution pipeline, the watchdog detects the failure before it locks up the entire operating system.
* **GPU Utilization Guard**: Observes overall GPU load on the host. If GPU utilization reaches critical thresholds (above 95%), VTE manages scheduling defensively to prevent thermal spikes or power instability.

---

## 3. Best Practices

* **Model Sourcing**: Only run `.gguf` models downloaded from trusted, verified sources (e.g., official Hugging Face repositories).
* **IPC Isolation**: Do not expose VTE's IPC channels or named pipes to external networks. For remote inference, wrap the engine behind a secure, authenticated network API (such as TLS-encrypted HTTP endpoints).

---

## 4. Reporting Vulnerabilities

As VTE is an open-source, community-driven educational project, we encourage transparency and collaborative improvement:
1. If you discover a security vulnerability, memory safety concern, or hardware instability issue, please **open a GitHub Issue** in this repository.
2. Provide details about the bug, steps to reproduce, and any Proof of Concept (PoC) or code suggestions to help fix it.
