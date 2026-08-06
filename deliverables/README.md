# Deliverables — Submission Index

Track 1 · Multimodal Content Creation Tools（第一轨 · 多模态内容创作工具）
Project: **IndieGen Asset Studio** — one text setting → game-ready multimodal assets, natively on AMD Radeon / ROCm.

This index maps every required submission item to its file in the repository.

---

## 1. Project Profile — PDF（项目简介文件 PDF）

**File:** `deliverables/Project_Profile_EN.pdf`（6 pages, generated from `docs/PROJECT_PROFILE_EN.md`）

| Required section（要求） | Where in the PDF |
| --- | --- |
| 项目背景 / Project background | §1 — indie teams spend 40–70 % of budget on outsourced art; style drift between vendors; one chain + one GPU |
| 目标用户与应用场景 / Target users & scenarios | §2 — solo devs, small studios, game jams, content creators; 4 scenarios incl. the flagship "wasteland bar" |
| 系统架构 / System architecture | §3 — Browser UI → FastAPI backend + SQLite → ComfyUI GPU engine (W1–W7) |
| 模型与算法介绍 / Models & algorithms | §4 — SDXL, MiDaS, PBRFromDepth, MusicGen-small, ProceduralSFX, ActionPose + ControlNet OpenPose, TripoSR, MarianMT, Three.js |
| AMD Radeon GPU / ROCm 适配描述 / ROCm adaptation | §5 — auto GPU detection, ROCm 7.1 wheels, measured performance table, full chain ≈57 s GPU time |

Regenerate with: `./ComfyUI/.venv/bin/python deliverables/tools/render_profile_pdf.py`

---

## 2. Project Source Code（项目源代码）

**Complete repository:** this repository root (GitHub: `MFWTW/create_3Dgame`)

- Workflows: `workflows/W1_concept.json` … `W7_model.json` (ComfyUI API format)
- Custom nodes: `nodes/indie_studio_nodes/` (PBRFromDepth, MusicGenNode, ProceduralSFX, ActionPose, SaveMeshGLB)
- Backend: `server/` (FastAPI + SQLite job archive, output proxy, Chinese→English translation)
- Frontend: `web/` (workbench UI + Three.js 3D scene viewer)
- Deployment: `deploy/` (docker-compose, nginx, systemd)

**README:** `README_EN.md`

| Required content（要求） | Section in README_EN.md |
| --- | --- |
| 环境配置 / Environment setup | §1–§4 — clone, `setup_comfyui.sh` (AMD ROCm auto-detect), model downloads, W7 TripoSR install |
| 启动指南 / Startup guide | §5 — start ComfyUI (8188) + web backend (8000), open http://localhost:8000 |
| 依赖列表 / Dependency list | §9 — backend, custom nodes, ComfyUI + third-party nodes |
| 性能 / Performance | §7 — measured AMD Radeon table (W1–W6) |

---

## 3. Demo Video（演示视频）

**Provided by the submitter（提交者已有视频，本仓库不生成）** — expected file: `Demo_Video_EN.mp4`

Checklist for the 3–5 min video（按需求自查）:

- [ ] 时长 3–5 分钟
- [ ] 演示实际操作流程（Web 界面或命令行，从提交到最终结果）
- [ ] 展示 AMD Radeon GPU 实际执行性能（rocm-smi / 真实耗时）
- [ ] 命令行 / 图形界面两种入口至少一种
- [ ] 结果清晰、稳定、输出多样性（图片 / 音频 / 3D 模型）

Real numbers to cite（实测）: W1 concept 14.6 s GPU · W2 depth 1.1 s · W3 PBR 1.0 s · W4 music 9.6 s ·
W5 SFX 0.04 s · W6 sprite 20.9 s · W7 2D→3D 5.2 s · full chain W1–W6 ≈57 s.
Walkthrough for recording: `docs/HANDS_ON_WALKTHROUGH_CN.md`.

---

## 4. Supplementary Material（补充材料 · 选择一份）

**Chosen: PPT** — `deliverables/Supplementary_Deck_EN.pptx`（16:9, 9 slides, generated from `deliverables/tools/make_deck.py`）

Highlights the creative scenario (wasteland bartender / xianxia secret realm) and practical value:
full-chain style lock, engine-ready outputs, one Radeon GPU, reproducibility, product-grade packaging.

---

## 5. Extra Supporting Evidence（附加佐证）

| Item | File |
| --- | --- |
| Live benchmark data (rocm-smi sampled) | `deliverables/perf/benchmark.json` + `benchmark.log` |
| Architecture / pipeline / performance diagrams | `deliverables/assets/*.png` |
| AMD ROCm adaptation details | `docs/AMD_ROCm_EN.md` |
| Deliverable generator scripts | `deliverables/tools/` |

---

All submission materials are in English. · Track 1 · Multimodal Content Creation Tools
