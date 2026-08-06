# Track 2 Submission — DocuFlow

- **Track:** Track 2 — Development & Local Deployment of Private AI Agents
- **Participant (Team name):** Liu Li (刘力)
- **Email:** leo@pasuntech.com
- **Application name:** DocuFlow
- **Project repository:** https://github.com/stliuexp/DocuFlow

## Project Overview

DocuFlow is a B/S-architecture private AI agent platform for enterprise document parsing. Users upload business documents such as invoices and contracts (images / Excel / Word / PDF / XML); the platform turns them into structured, filterable, sortable data through a "text extraction → OCR → LLM structured parsing → human confirmation" pipeline, with an open API for ERP integration.

Core idea: **business templates are defined by the user** (modules, fields, ordering, prompts, timeouts), and **compute is chosen by the user** — a cloud LLM API, or a private AMD Radeon GPU server (ROCm) connected via a one-click SSH tunnel, so data never leaves the intranet.

## Submission Materials (Track 2 Requirements)

All materials live in the project repository: https://github.com/stliuexp/DocuFlow

1. **Project Specification Document** — [`report/specification.md`](https://github.com/stliuexp/DocuFlow/blob/main/report/specification.md)
   - Application scenarios, agent architecture diagram, core capabilities, model introduction & local deployment plan, and the AMD Radeon GPU inference optimization description
   - Architecture diagram: [`report/blockdiagram.pdf`](https://github.com/stliuexp/DocuFlow/blob/main/report/blockdiagram.pdf)
2. **Project Source Code** — complete repository with a README covering environment configuration, startup guide (one-click and manual), and dependency list
3. **Demo Video** — [Watch on Bilibili](https://www.bilibili.com/video/BV1DNup66ESb/); a local copy is at [`report/amd.mov`](https://github.com/stliuexp/DocuFlow/blob/main/report/amd.mov). It demonstrates the full workflow running on an AMD Radeon GPU, from GUI operations to the final structured result
4. **Supplementary Material (PPT / Poster)** — submission deck [`report/DocuFlow · AMD Radeon Hackathon 2026-07 Submission.pptx`](https://github.com/stliuexp/DocuFlow/blob/main/report/) and [`report/poster.md`](https://github.com/stliuexp/DocuFlow/blob/main/report/poster.md)

## AMD Radeon GPU / ROCm Highlights

- **Hardware baseline:** AMD Radeon GPU (gfx1100, 48 GB VRAM), ROCm 6.2 user space on Ubuntu 24.04
- **LLM inference:** Ollama (ROCm build) serving `qwen3:32b`, benchmarked on real invoice text at ~5.5 s per document — well under the 120 s per-template timeout; model selection validated against smaller candidates (`qwen3:8b` 4.3 s, `deepseek-r1:1.5b` for smoke tests)
- **OCR inference:** Unlimited-OCR adapted to run on the Radeon GPU (`torch 2.5.0+rocm6.2`) behind the same HTTP contract as the CPU PaddleOCR service — ~61 s end-to-end per invoice including vision-model inference, a generational usability jump over CPU mode
- **Private deployment:** SSH tunnels map the GPU server's Ollama/OCR ports to localhost; switching between cloud API and the Radeon server is a priority change, no code edits — fully private inference with data staying on-premises
- **One-click GPU stack deployment scripts:** `scripts/radeon/deploy-ollama.sh` and `scripts/radeon/deploy-unlimited-ocr.sh` in the project repository
