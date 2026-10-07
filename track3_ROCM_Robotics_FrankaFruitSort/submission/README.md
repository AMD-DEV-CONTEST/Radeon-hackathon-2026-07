# Source Code — Track 3 Submission

This directory contains the source code for the **Franka Multi-Fruit Sorting via SmolVLA on AMD ROCm** project, submitted to AMD Radeon Hackathon 2026 Track 3 (Physical AI).

## Directory Structure

```
submission/
├── src/
│   ├── scene/           # Genesis simulator scene construction
│   ├── data/            # Dataset collection scripts
│   ├── train/           # SmolVLA fine-tuning
│   ├── eval/            # Closed-loop evaluation
│   └── utils/           # Remote execution & auxiliary tools
├── configs/             # Scene and task configurations
└── requirements.txt
```

## Quick Start

For full reproduction instructions, environment setup, and step-by-step guide, please refer to the **[root README.md](../README.md)**.

## Dependencies

See [requirements.txt](./requirements.txt). The project requires AMD ROCm 7.2.1 + PyTorch 2.9.1+rocm7.2.1.

## License

This project uses open-source components under their respective licenses:
- Genesis: Apache-2.0 (Genesis-Embodied-AI/Genesis)
- LeRobot: Apache-2.0 (huggingface/lerobot)
- SmolVLA: Apache-2.0 (Hugging Face)
