# 🏭 Wafer Map Classification AI Audit System - Track 1

A local VLM batch inspection system built for AMD Radeon hardware to automate semiconductor wafer defect classification, spatial failure signature identification, and deterministic JSON auditing.

---

## 🚀 Project Links & Presentation Assets

* **🌐 Live Interactive Dashboard:** [Hugging Face Space Live App](https://huggingface.co/spaces/uttarasawant/amd_radeon_wafer_map_classification)
* **📊 Project Slide Deck:** [View the Presentation Slides](https://huggingface.co/spaces/uttarasawant/amd_radeon_wafer_map_classification/resolve/main/Wafer%20Map%20Classification%20AI%20Audit%20System.pdf)
* **🎬 Video Demonstration:** [Watch the Technical Walkthrough](https://youtu.be/-PNz3aqsU60)
* **💻 Core Repository:** [GitHub - Wafer Map Training & Inference](https://github.com/uttarasawantgh/Radeon-hackathon-2026-07)
* **🖥️ UI Repository:** [Control Center Dashboard](https://huggingface.co/spaces/uttarasawant/amd_radeon_wafer_map_classification)
* **🖥️ Project Description PDF:** [Project Description PDF](https://huggingface.co/spaces/uttarasawant/amd_radeon_wafer_map_classification/resolve/main/Project%20Description%20PDF%20Track%201%20Wafer%20Map%20Classification.pdf)
---

## ⚡ Hardware Telemetry & Benchmarking Highlights

This system executes zero-shot and fine-tuned wafer defect classification locally using dedicated AMD hardware and the ROCm software stack:

| Metric | Local AMD Hardware Radeon (PyTorch ROCm) |
| :--- | :--- |
| **Total Training Time** | **36.52 seconds** |
| **Step Throughput** | **0.90 – 1.04 iterations/sec** |
| **Sample Processing Speed** | **7.229 samples/sec** |
| **Inference Engine** | **Qwen2.5-VL-7B-Instruct** (LoRA Adapted via SDPA) |
| **Operational Cost** | **$0.00** (Fixed, Air-gapped Bare-Metal) |

### Key Architectural Takeaways for Judges:
1. **On-Premise Security:** Guarantees absolute data privacy by processing sensitive semiconductor fab test data locally without relying on external cloud APIs.
2. **High-Throughput Localized Execution:** Optimizes AMD Radeon hardware via ROCm and bfloat16 precision to deliver rapid zero-shot defect classification and deterministic JSON audit outputs.

---

## 🚀 Roboflow Dataset Citation

If you use this dataset in your research or project, please cite it as follows:

Wafer Detection Dataset. (2024). *Wafer Defect Detection Dataset* (Version 1) [Data set]. Roboflow Universe. https://universe.roboflow.com/wafer-defect-detection/wafer-detection

---

## 🛠️ Repository, System Structure & Script Order

* *Execute this core logic repository first to generate the necessary CSV and JSON audit logs, then run the UI repository to render the dashboard.*
* **UI Repository Link:** [Wafer Map UI](https://huggingface.co/spaces/uttarasawant/amd_radeon_wafer_map_classification)
* `download_data.py` - Script to download the raw semiconductor wafer map dataset from Roboflow Universe.
* `prepare_dataset_amd.py` - Converts dataset annotations into a structured VLM training format and organizes outputs into the `data/processed` folder.
* `train_amd_native.py` - Fine-tunes the base model using processed training outputs on AMD hardware and saves checkpoints to `./models/wafer_map_qwen_lora`.
* `inference_amd.py` - Runs a single-image inference test using the fine-tuned LoRA weights on AMD hardware.
* `batch_audit_amd.py` - Executes full test set evaluation, parsing results into `wafer_batch_inference_summary.json` and `wafer_defect_summary_log.csv`.
* `wafer_defect_summary_log.csv` - The parsed operational risk matrices displayed on the audit dashboard UI.
* `wafer_batch_inference_summary.json` - The inference results for the image batch.
