# Radeon-hackathon-2026-07


### Track 3: Physical AI Challenge – Robotics Simulation and Application Design based on AMD Radeon GPUs and ROCm

1. **Technical Report** (should include, but is not limited to):
   - Definition and description of the target application
   - Overall system architecture and solution design
   - Description of the datasets used for training and/or evaluation
   - Explanation of how AMD Radeon GPUs are utilized during training, inference, and other relevant stages
   - Description of the innovations, key technical contributions, and important aspects of the project
   - Description of the final deliverables and output forms of the project
   - Any additional information that participants believe highlights the strengths or unique aspects of their work
   - Introduction of team members and their respective contributions
2. **Project Source Code**
   - Dedicated source code repositories
   - A Docker image containing the complete source code and all required components for running the project would be preferable
3. **Reproducibility Instruction README** — a detailed README document containing:
   - Environment setup instructions
   - Execution and usage instructions
   - Dependency specifications
   - Step-by-step reproduction procedures
   - Following the provided instructions should allow evaluators to reproduce the submitted results
4. **Demonstration Video** (Recommended Length 3~5 minutes)
   - The video should demonstrate the complete workflow of the project, including command-line and/or GUI operations, execution procedures, and results
5. **Supplementary materials** in other formats may be submitted to demonstrate the value of the proposed technical solution.

# R.A.G.E. (Robotic Assembly & Genesis Environment)
### Track 3: Bimanual Robotics & Multimodal AI Integration

Welcome to **R.A.G.E.** — a production-grade, zero-shot Cognitive Orchestration Framework built for bimanual robotic assembly.

Most robotics hackathon submissions rely on hardcoded kinematic waypoints and pre-scripted animations. We took a radically different approach. R.A.G.E. integrates massive Vision-Language-Action (VLA) models, dynamic operations research scheduling, and real-time Milvus vector memory directly into a deformable multi-physics engine (Genesis) — all running natively and optimized on an AMD ROCm/Vulkan software stack.

This is not just a robotic script; it is a thinking, reacting, and mathematically rigorous factory pipeline.

---

## 🏆 Why This Project Meets & Exceeds the Evaluation Criteria

We architected R.A.G.E. specifically to max out the hackathon rubric across all categories:

- **Hardware Innovation (AMD ROCm & Vulkan)** — We proved Genesis can natively target AMD GPUs for highly complex, deformable MPM (Material Point Method) rubber physics. Through extreme memory optimization, our standalone physics loop runs at ~6 FPS using only 1.16 GB of VRAM, while our full pipeline scales to utilize 30GB+ when loading 7-billion-parameter LLMs into AMD memory.

- **Algorithmic Rigor (Operations Research)** — Instead of using basic if/then logic for task sequencing, R.A.G.E. implements the **Campbell-Dudek-Smith (CDS) heuristic** — a highly efficient algorithm from operations research used in machine scheduling problems — to dynamically calculate the exact sequence that minimizes bimanual idle time and overall makespan.

- **Dynamic Fault Recovery (Milvus RAG)** — The system doesn't just execute blindly. When the Qwen-VL vision parser detects a dropped cable mid-transfer, it queries a Milvus Lite vector database of factory Standard Operating Procedures (SOPs). The RAG system instantly overrides the CDS schedule and physically retracts the arm (`dz = +0.05`) to reset the workspace safely.

- **Open-Source Contribution** — During development, we identified a template mapper caching limitation on the AMD/Vulkan backend during MPM kernel compilation. We have officially submitted a highly detailed bug report with minimal reproducible code to the Genesis core team: **Genesis Issue #3191**.

---

## 📂 Project Architecture & Folder Structure

```
Track3-Solo-R.A.G.E/
├── project/
│   ├── envs/
│   │   ├── generated_assets/       # Dynamically generated collision meshes and URDFs
│   │   ├── active_fixturing.py     # Robot A: Static holding constraints
│   │   └── server_assembly.py      # Robot B: Dynamic bimanual insertion environment
│   ├── memory/
│   │   ├── milvus_data/            # Local Milvus Lite SQLite backend
│   │   └── vector_store.py         # RAG pipeline & embedding retrieval for SOPs
│   ├── scripts/
│   │   ├── scheduling/             # CDS heuristic and operations research mathematics
│   │   ├── cognitive_manager.py    # Qwen-VL Vision-Language parser
│   │   ├── embodied_policy.py      # OpenVLA spatial output mapping
│   │   └── run_pipeline.py         # The Master Orchestrator (Main Entry Point)
├── amd_benchmarks/
│   ├── pipeline_metrics.json       # Output telemetry (VRAM usage, FPS, loop times)
│   └── rage_bimanual_demo.mp4      # The final rendered 5-minute Director's Cut
├── setup.sh                        # Environment & dependency bootstrapping
└── download_models.sh              # HuggingFace weight retrieval script
```

---

## 🚀 Reproducibility Instructions

Follow these exact steps to recreate the complete pipeline, re-compile the physics kernels, and generate the final hardware benchmarks.

### 1. Environment Setup

We have automated the creation of the virtual environment and the installation of all necessary GPU-accelerated libraries. From the root directory, run:

```bash
bash setup.sh
```

> **Note:** This script initializes the Python virtual environment (`venv`) and installs all strict dependencies.

### 2. Model Initialization

To run the full cognitive suite, the massive vision-language and VLA models must be cached locally. Run the model download script:

```bash
bash download_models.sh
```

> **Note:** This step may take 10–15 minutes depending on your network speed, as it pulls the necessary neural network weights directly from Hugging Face.

### 3. Execution

To launch the master orchestrator, initialize the Genesis Vulkan backend, and begin the bimanual physics simulation, run:

```bash
python3 -m project.scripts.run_pipeline
```

**What to expect during execution:**

| Phase | Description |
|---|---|
| **Phase 1 — Hardware Binding** | Genesis will output its connection to your AMD Radeon/EPYC GPU and allocate memory. |
| **Phase 2 — Kernel Compilation** | The Vulkan backend will compile the complex MPM physics kernels for the deformable cables. (This takes ~45 seconds on the first run.) |
| **Phase 3 — The Loop** | The console will stream the active CDS scheduling sequences, the vision parsing confidences, and the AI's spatial `[dx, dy, dz]` commands. |
| **Phase 4 — RAG Override** | Halfway through the sequence, watch the terminal logs for the Milvus database retrieving the "Defect Recovery - Dropped Cable" SOP, proving dynamic fault interception. |

### 4. Output Verification

Once the script prints `R.A.G.E. pipeline run complete.`, you will find two new critical files generated in the `amd_benchmarks/` directory:

- **`pipeline_metrics.json`** — The raw telemetry proving the sub-2GB memory footprint and FPS throughput.
- **`rage_bimanual_demo.mp4`** — A fully rendered visual playback of the simulation, capturing the AI's zero-shot spatial reasoning and dynamic retraction.

---

## 🛠️ Core Dependencies

| Category | Package(s) |
|---|---|
| **Physics** | `genesis-world==1.3.1` (Vulkan Backend via Taichi) |
| **Memory** | `pymilvus[model]` (Milvus Lite) |
| **AI Models** | `torch`, `transformers`, `accelerate` (ROCm optimized) |
| **Vision** | `ultralytics` (YOLO spatial mapping) |
