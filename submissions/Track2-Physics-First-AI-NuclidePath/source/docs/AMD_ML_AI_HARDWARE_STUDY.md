# Deep Learning / Scientific ML on AMD Hardware — NuclidePath Expansion

**Date:** 22 July 2026
**Authors:** Stefano Rigante + Hermes Agent
**Focus:** Documented, measured, planned, and research-only uses of AMD GPU (ROCm) compute for scientific ML/DP in radionuclide transport

**Status key:** **Implemented** means present in the repository; **Measured** means observed in the documented `gfx1100` ROCm endpoint; **Planned** means a roadmap item with no implementation/evidence yet; **Research-only** means a hypothesis or design direction requiring validation. The measured endpoint is an AMD `gfx1100` Radeon cloud device; it is not identified in the evidence as a retail RX 7900 XTX, so retail-card specifications and performance must not be inferred from it.

---

## Framing: Why AMD GPU Changes the ML Game Here

Standard CPU-based scientific computing limits NuclidePath to:
- Single-scenario evaluation (one transport solve at a time)
- Offline Monte Carlo (feasible but slow)
- No real-time parameter sweeps or inverse modeling

AMD GPU (ROCm) may reduce these constraints for workloads that are implemented and benchmarked successfully. The items below are proposals, not evidence that every compute-intensive task is currently interactive.

The key principle: **AMD GPU should not just run the LLM**. It should accelerate the entire scientific ML stack.

---

## 1. Training Infrastructure — What AMD GPU Enables

### 1a. GCS Surrogate Training at Scale

The Bradbury GCS model requires solving a nonlinear system of cation exchange equations for each (multi-ion) parameter combination. On CPU this is serial and slow for large ensembles.

On AMD GPU:
- **Latin Hypercube sampling**: generate 200k parameter combinations in parallel
- **Batched GCS evaluation**: all 200k solves dispatched as a single GPU kernel batch
- **Surrogate training**: PyTorch/ROCm with automatic differentiation through the GCS physics

**Planned targets (not measurements):** 200k evaluations, surrogate training, and inference should be benchmarked against a CPU baseline after implementation. No timing is claimed here.

This is a **planned/research-only** design. Exponentials and reciprocals are elementwise operations; this text does not claim tensor-core execution or that a custom-kernel-free implementation is already available.

### 1b. Physics-Informed Neural Networks (PINNs)

A PINN encodes the GCS physics directly into the loss function:

```
L_total = L_data + lambda_physics * L_physics

where:
  L_physics = |charge_balance| + |Kd_constraints| + |GCS_residuals|
```

On AMD GPU:
- The physics residual is computed in batch for all training points simultaneously
- Backpropagation through the physics (automatic differentiation of GCS equations) is tractable on GPU
- The result is a surrogate that is not just accurate but **physically constrained**

**Note**: PINNs require careful implementation of GCS as a differentiable PyTorch module. This is non-trivial but tractable. The benefit is a network that cannot violate physical constraints even for extrapolated inputs.

### 1c. Neural Uncertainty Quantification (NUQ)

Instead of simple Monte Carlo, train a network to learn the uncertainty distribution:

```
Input: ion concentrations + mineralogy
Output: p(Kd_eff | inputs) -- modeled as a distribution, not a point estimate

Architecture: heteroscedastic MLP
  - mean head: predicts Kd_eff
  - variance head: predicts epistemic uncertainty

Training: combination of:
  - GCS solver outputs (aleatoric uncertainty from Kc measurement error)
  - Residual/resampling methods (epistemic uncertainty from model gap)
```

This gives credible intervals that are **data-driven**, not just parametric sensitivity analysis.

---

## 2. Data-Driven Inverse Modeling — Calibrating GCS from Experimental Data

### 2a. Bayesian Parameter Estimation with Hamiltonian Monte Carlo

If Stefano has experimental data from his thesis (Cs adsorption on illite at various K+ concentrations), this can be used to calibrate the GCS Kc values:

```
Prior: Kc_Cs_K_FES ~ Uniform(Bradbury_low, Bradbury_high)
        site_capacity_FES ~ Normal(literature_mean, literature_std)

Likelihood: GCS_model(params, experimental_conditions) vs measured_Cs_adsorption

Posterior: HMC sampling on AMD GPU (**research-only**)
  - PyMC-on-ROCm is not established by this project; custom HMC in PyTorch or another validated backend would require separate implementation
  - 10,000 posterior samples: **planned benchmark; no timing claimed**
  - Produces credible intervals for every Kc parameter
```

This transforms the GCS from "literature parameters" to "your-specific-illite parameters" — much higher scientific value.

### 2b. Differentiable Transport Inverse Problem

Extend the inverse problem beyond GCS to the full Ogata-Banks transport:

```
Measured breakthrough curve at distance x_d
         |
Gradient-based optimization (L-BFGS-B on AMD GPU)
         |
Fitted parameters: D (dispersion), v (velocity), Kd_eff (from GCS)
         |
Uncertainty via Hessian approximation
```

Whether this becomes interactive is **planned** and must be established by a reproducible benchmark; no seconds/minutes claim is made.

---

## 3. Reinforcement Learning — Optimal Monitoring Network Design

### 3a. RL for Sensor Placement

Given a contamination scenario, where should monitoring wells be placed to maximize early detection probability?

```
State: spatial concentration field (from GCS+transport simulation)
Action: place/move a monitoring well
Reward: early detection probability - monitoring cost

Agent: PPO or SAC on AMD GPU
Environment: batch of 1000 simulated scenarios (parallelized on GPU)
```

This is a genuine RL problem with:
- High-dimensional state (2D/3D concentration field)
- Discrete-continuous action space (well positions + detection thresholds)
- Sparse reward (contamination detected or not)

AMD GPU advantage: the environment simulation (GCS + transport) is expensive. Batch-parallelizing 1000 scenarios per training step is only feasible on GPU.

### 3b. RL for Adaptive Sampling Strategy

During an ongoing contamination event, sequentially choose where to sample next:

```
Current data: partial concentration observations
Belief: posterior over concentration field (updated via data assimilation)
Action: next sampling location
Reward: reduction in uncertainty about source term / receptor exposure

Framework: Bayesian optimization / Bayesian RL
  - Gaussian Process surrogate of the concentration field
  - Acquisition function: expected information gain of next sample
  - Batch evaluation: evaluate multiple candidate locations simultaneously on GPU
```

### 3c. Multi-Objective RL for Intervention Planning

Given a contamination scenario, plan optimal intervention (excavation, containment, pump-and-treat):

```
Objectives (Pareto optimization):
  - Minimize dose equivalent to population
  - Minimize remediation cost
  - Minimize time to below regulatory limit

State: contamination state + current intervention actions
Action: adjust intervention parameters
Reward: vector of three objectives

Algorithm: Multi-Objective PPO (MO-PPO) on AMD GPU
  - Parallel environments: 1000 scenarios per training iteration
  - Pareto front approximation after convergence
```

---

## 4. Data Processing and Structured ML

### 4a. Automated Parameter Extraction from Literature (Vision + OCR)

The Bradbury 2000 PDF contains tables that should be machine-readable:

```
Pipeline:
  1. PDF page --> image (render at 300 DPI)
  2. Table detection --> bounding boxes (trained detector or heuristic)
  3. OCR / structure extraction --> numerical values
  4. Semantic assignment --> JSON with units, site type, radionuclide
  5. Uncertainty estimation --> Kc values have measurement uncertainty
```

**Planned:** table detection/OCR could be evaluated with ONNX Runtime on ROCm. Throughput is workload-, model-, and backend-dependent; no pages/second figure is claimed.

### 4b. Anomaly Detection in Monitoring Time Series

Real monitoring data has noise, sensor failures, and detection limits:

```
Task: Given a time series of concentration measurements at a well,
detect:  - trend changes (contamination arrival)
         - sensor anomalies / spikes
         - values below detection limit (censored data handling)

Model: Transformer-based anomaly detector
  - Trained on synthetic GCS output + noise injection
  - Online inference: O(1) per new data point
  - AMD GPU: batch inference for 100+ wells simultaneously
```

### 4c. Spatial Interpolation / Emulation of 2D Concentration Fields

The current model is 1D. A spatial emulator maps 1D transport results to 2D:

```
Input: 1D breakthrough curves at receptor distances
       + geological heterogeneity model (K, porosity maps)
Output: 2D concentration field at any (x, z, t)

Architecture: Conditional Neural Process (CNP) or Fourier Neural Operator
  - Learns to interpolate spatial fields given sparse observations
  - Trainable on GCS + flow simulation data
  - Inference: O(seconds) vs O(hours) for full 2D PDE solve
```

---

## 5. LLM-Specific GPU Acceleration

### 5a. Speculative Decoding with Smaller Draft Model

For local LLM inference on AMD GPU:

```
Draft model: Qwen-0.5B or 1B (fast, lower quality)
Target model: Qwen-9B (high quality, slower)

Speculative decoding:
  - Draft model generates K tokens
  - Target model verifies all K tokens in parallel on AMD GPU
  - Accepted tokens fed back to draft model
  - Speedup: **planned benchmark; no multiplier claimed**
```

**AMD-specific**: llama.cpp supports HIP (AMD GPU) for both draft and target models. Speculative decoding on ROCm is a direct LLM speedup for the NuclidePath orchestrator.

### 5b. KV-Cache Optimization for Long Contexts

NuclidePath agents have multi-turn memory but LLM context windows are finite:

```
Technique: KV-cache compression
  - Compress past KV entries using quantization (4-bit)
  - Retain semantic summary tokens at full precision
  - AMD GPU: batch KV operations are memory-bandwidth-bound
  - Available VRAM on AMD RX 7900 XTX (24GB) can fit:
      Qwen-9B Q8 + 8192 context with KV compression
```

### 5c. Multi-Query Attention for Agentic Workflows

Current LLM architectures use multi-head attention. For multi-agent scenarios:

```
Technique: Multi-Query Attention (MQA) variant
  - All attention heads share the same K and V projections
  - Reduces KV-cache size by ~Nx (N = num heads)
  - AMD GPU: memory and throughput effects are **hardware/backend-dependent and unmeasured here**

Alternative: Grouped Query Attention (GQA)
  - N_kv < N_heads, intermediate between MHA and MQA
  - Available in Qwen 2.5 architecture
```

---

## 6. Differential Programming — Automatic Differentiation Through Physics

### 6a. Sensitivity Analysis via Backpropagation

Instead of finite differences:

```
d(Kd_eff) / d(Kc_Cs_K_FES) = backpropagate through GCS equations

AMD GPU:
  - GCS equations as PyTorch autograd functions
  - All 8 Kc parameters: computed simultaneously in one backward pass
  - Jacobian-vector products: O(1) rather than O(n_params) finite differences
```

### 6b. Gradient-Based Optimization of Site Characterization

```
Task: Given measured breakthrough curves, find site parameters

Optimization: L-BFGS-B with gradients from GCS PyTorch module
  - Convergence and iteration count: **research-only until validated on representative data**
```

### 6c. Inverse Uncertainty Propagation

```
Forward: Kc parameters (with measurement uncertainty) --> Kd_eff distribution
Method: Monte Carlo with GCS PyTorch on AMD GPU
  - 100,000 samples: **planned benchmark; no timing claimed**
  - Full posterior of Kd_eff given Kc uncertainties

vs CPU: **planned comparison; no timing claimed**
```

---

## 7. Distributed and Multi-GPU Scenarios

### 7a. Data Parallel Training for Surrogate Model

If training data exceeds single-GPU memory:

```
Strategy: DataParallel on multiple AMD GPUs
  - Split 200k training samples across N GPUs
  - Each GPU computes gradient for its shard
  - AllReduce gradients across GPUs
  - ROCm NCCL support for multi-GPU gradient communication

ROCm note: For a single GPU, not needed; the project endpoint is not identified as a retail RX 7900 XTX.
For cloud multi-GPU (MI300X): critical for scaling.
```

### 7b. Pipeline Parallelism for Multi-Agent

The NuclidePath multi-agent system has independent agents that could run in parallel:

```
Site Agent      --> parallel --> Environment Agent
Local KB        --> parallel --> both agents
LLM Planner     --> coordinates but inference is sequential

Optimization:
  - Prefill phase: token generation starts after planning tokens produced
  - Decode phase: continuous batching across agent instances
  - AMD GPU: multiple inference streams on same GPU with time-slicing
```

---

## 8. Emerging Hardware Features on AMD CDNA/MI Architecture

### 8a. Matrix Foam Units (MFMA) for FP8 Training

AMD MI300X and other CDNA-class hardware may support FP8 matrix operations subject to architecture and ROCm/kernel support:

```
Implication for NuclidePath:
  - FP8 surrogate training: **research-only**, requiring explicit kernel, scaling, and accuracy validation
  - Throughput/accuracy: **no claim until measured**

Note: RX 7900 XTX is RDNA3, not CDNA. MFMA not available.
MI300X cloud instances (if accessible) would benefit most.
```

### 8b. Hardware Ray Tracing for Spatial Visualization

AMD RDNA3 has hardware ray tracing. Not directly relevant for physics computation, but:

```
Use case: Interactive 3D visualization of contamination scenarios
  - Ray-traced rendering of concentration field as volume
  - Hardware acceleration on AMD GPU
  - Could be integrated into the dashboard for spatial display

Note: This is a rendering task, not a compute task.
RDNA3 ray tracing is for graphics, not scientific computing.
```

### 8c. Unified Memory (APU) for Large Model + Data Co-location

If using AMD APU (e.g., Ryzen AI) instead of discrete GPU:

```
Unified memory architecture:
  - CPU and GPU share same physical memory pool
  - No PCIe bandwidth bottleneck for data transfer
  - Benefit: Large model weights + training data in same address space

For NuclidePath:
  - Useful if running on laptop APU (e.g., Ryzen AI 300 series)
  - Less relevant for RX 7900 XTX or cloud MI instances
```

---

## 9. Summary Table: AMD GPU Exploitation Map

| Capability | AMD Hardware Feature | NuclidePath Use Case | Current Status |
|---|---|---|---|
| Surrogate training | ROCm + PyTorch batched | GCS surrogate, 200k eval | Not started |
| Monte Carlo | ROCm vectorized | Uncertainty propagation | Partially done (CPU) |
| Bayesian inference | ROCm + PyTorch | HMC parameter calibration | Not started |
| Speculative decoding | llama.cpp HIP | Faster local LLM | Not started |
| PINN training | Autograd + ROCm | Physics-informed surrogate | Not started |
| KV compression | HIP memory management | Longer agent contexts | Not started |
| Multi-agent inference | Continuous batching | Parallel agent execution | Not started |
| Spatial emulation | Fourier Neural Operator + ROCm | 2D concentration field | Not started |
| RL training | Batch parallel envs + ROCm | Monitoring well placement | Not started |
| Table extraction | ONNX Runtime + ROCm | Bradbury PDF parsing | Not started |
| FP8 training | MI300X MFMA | Large surrogate training | Cloud MI only |
| Anomaly detection | Transformer + ROCm | Monitoring time series | Not started |

---

## Priority Ranking for NuclidePath v0.5-v0.7

### Immediate (v0.5 — 1-2 weeks)
1. **Surrogate model** — highest impact, well-defined scope
2. **Bradbury parameter extraction** — foundation for everything else
3. **Illite% scaling** — straightforward extension, immediate value

### Short-term (v0.6 — 3-4 weeks)
4. **Sr-90 + Ca/Mg competition** — multi-isotope, high scientific value
5. **Bayesian UQ on Kc parameters** — thesis data integration
6. **Speculative decoding for LLM** — direct UX improvement

### Medium-term (v0.7 — 1-2 months)
7. **PINN surrogate** — stronger physical constraints
8. **RL for monitoring optimization** — novel capability
9. **Spatial emulator (2D)** — bridge from 1D to visualization

---

## References and Further Reading

- Bradbury & Baeyens (2000) — GCS model foundation
- Raissi, Perdikaris & Karniadakis (2019) — Physics-Informed Neural Networks
- Silver et al. (2017) — Monte Carlo Tree Search / RL
- Chen et al. (2021) — Neural Operators for PDE surrogate modeling
- AMD ROCm documentation — PyTorch HIP backend
## AMD Hardware Advantages vs NVIDIA — Specific for Scientific Computing

### FP64: AMD Has Real Double-Precision Performance

NVIDIA Tensor Cores are optimized for FP16/BF16, not FP64. On RTX 4090, FP64 is throttled to 1/64 of FP32 peak throughput. AMD CDNA (MI300X) and RDNA3 have native FP64 units.

| Architecture | FP64 : FP32 ratio | FP64 peak (TFLOPS) |
|---|---|---|
| AMD `gfx1100` endpoint used by this project | Measured: FP64 0.8054 TFLOPS; FP32 22.8747 TFLOPS (~3.52% of FP32) | 0.8054 measured |
| AMD MI300X (CDNA3) | ~1/2 | ~163 |
| NVIDIA RTX 4090 (Ada) | ~1/64 | ~0.5 |
| NVIDIA H100 (Hopper) | ~1/3 | ~51 |

The current evidence measures a PyTorch matmul on the `gfx1100` endpoint, not every NuclidePath workload. Transport/GCS/Monte Carlo/HMC/PINN precision and performance remain workload-specific. No categorical AMD-vs-NVIDIA conclusion is supported by this document.

### INT8/DP4A on RDNA3

The project evidence does not establish a specific DP4A instruction path or attribution for its quantized LLM throughput. Treat DP4A acceleration as **research-only** until verified with a documented kernel/build and benchmark.

| Configuration | Memory footprint | Throughput |
|---|---|---|
| Qwen-9B FP16 | ~18 GB | Not measured here |
| Qwen-9B INT8 (Q8_0) | ~11 GB | Not measured on a retail RX 7900 XTX |
| Qwen-9B INT4 (Q4_K_M) | ~5.5 GB | Not measured here |

llama.cpp's HIP backend ran the documented Q8_0 model on the measured `gfx1100` endpoint. No `hipBLASLt` requirement, `-qtune rDNA3` flag, packed-integer instruction path, or INT4 comparison was verified in this project.

### 24 GB VRAM Layout — What Fits Simultaneously

**Retail RX 7900 XTX planning example (not the measured endpoint):** 24 GB GDDR6 and approximately 960 GB/s nominal bandwidth. The following is a sizing estimate, not a capacity measurement:

```
Qwen-9B Q8_0:           ~11 GB
GCS surrogate (FP32):  ~500 MB
200k batch buffers:     ~1 GB
KV cache (8k ctx):     ~2 GB
Activation memory:       ~3 GB
────────────────────────────────
Total:                  ~17.5 GB  →  6.5 GB headroom

With INT4 Qwen-9B:      ~5.5 GB
→ 18.5 GB free for surrogate + MC + activations
→ Run LLM + surrogate + Monte Carlo in parallel on ONE card
```

Actual residency, fallback, and model swapping require a run on the target hardware; none is guaranteed by this estimate.

### hipSOLVER — GPU-Resident Nonlinear System Solve

The GCS model requires solving a nonlinear system of cation exchange equations. The current implementation uses the documented CPU path; a GPU nonlinear-solver path is **planned/research-only**. hipSOLVER provides linear algebra primitives, but does not make GCS a turnkey nonlinear solve.

```
hipSOLVER supports:
  - Cholesky / LU / QR factorization
  - Iterative solvers: CG, BiCGStab, GMRES
  - Dense and sparse systems

Possible research direction: implement and validate a Newton method whose linear subproblems use suitable ROCm primitives. GPU residency, convergence, batching, and transfer behavior are not established.
```

### RCCL vs NCCL — Multi-GPU

For multi-AMD-GPU training (MI300X cloud nodes or multi-GPU workstation):

```
ROCm Collective Communications Library (RCCL):
  - AllReduce, Broadcast, AllGather for gradient synchronization
  - AMD MI300X: 4-8 GPU nodes with Infinity Fabric interconnect
  - Scaling: **planned benchmark; no multiplier claimed**

Single-GPU case: collect a baseline first.
MI300X multi-GPU case: planned scaling study, not a demonstrated result here.
```

### What AMD Cannot Do Well (Honest Assessment)

| Task | AMD status | Use instead |
|---|---|---|
| Video encoding (NVENC) | Mature but not as fast | CPU encoder |
| cuDNN CNN optimizations | MIOpen, ~2 years behind | CPU for now |
| TF32 training | Not available on RDNA3 | BF16 (acceptable) |
| Triton kernel fusion | HIP port exists, less optimized | Native PyTorch |
| H100 NVLink bandwidth | N/A | N/A |

Hardware fit is workload- and configuration-dependent. AMD is **measured/implemented for this project’s local ROCm inference path**; NVIDIA comparisons require equivalent hardware, software, precision, and benchmark conditions.

### Bottom Line: AMD vs NVIDIA for NuclidePath

| Criterion | AMD RX 7900 XTX | NVIDIA RTX 4090 |
|---|---|---|
| FP64 compute | 0.8054 TFLOPS measured on project endpoint | Not benchmarked here |
| VRAM | 24 GB | 24 GB |
| LLM inference (Qwen-9B) | Measured on `gfx1100` endpoint: pp512 2877.30±153.36 tok/s; tg128 67.66±0.14 tok/s (Q8) | Not benchmarked here |
| Scientific batch compute | Workload-dependent; no retail-card benchmark | Workload-dependent; no benchmark here |
| Multi-GPU scaling | RCCL, MI300X | NCCL, NVLink |
| Cost | Not compared under equivalent configurations | Not compared under equivalent configurations |
| Software ecosystem | ROCm/HIP path verified for this project | CUDA path not evaluated by this project |

**Conclusion:** the project has measured a ROCm path on a `gfx1100` endpoint and should report that evidence as-is. It does not establish retail RX 7900 XTX performance, an FP64 bottleneck for all workloads, or AMD superiority over NVIDIA.

---

## References and Further Reading

- Bradbury & Baeyens (2000) — GCS model foundation
- Raissi, Perdikaris & Karniadakis (2019) — Physics-Informed Neural Networks
- Silver et al. (2017) — Monte Carlo Tree Search / RL
- Chen et al. (2021) — Neural Operators for PDE surrogate modeling
- AMD ROCm documentation — PyTorch HIP backend
- AMD MI300X whitepaper — CDNA3 architecture, FP8 MFMA
