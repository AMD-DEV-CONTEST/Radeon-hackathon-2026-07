# Radeon Hackathon 2026-07

AMD Radeon 黑客松参赛仓库（fork 自官方模板）。

这是参加 AMD Radeon 黑客松的提交仓库，目录结构按赛事要求组织。我的实际项目代码和说明放在对应 Track 的子目录 / 链接里（见下方"我的提交"）。

## Track 3 starter demo: robot simulation on AMD Radeon GPU

New to robotics, or want to learn how to run robot simulation on AMD GPUs? This reference demo is a quick, hands-on starting point for Track 3 participants — an end-to-end pipeline where a Franka Panda arm picks fruit off a table and places it in a bowl, built on the **Genesis** physics engine and **LeRobot**, running on an AMD Radeon (ROCm) GPU.

▶️ **Demo repo & videos:** https://github.com/wangxunx/franka_fruit_pick_demo

What you'll learn:
- Set up a robot simulation environment on an AMD Radeon GPU (ROCm), using the prebuilt ROCm PyTorch wheels
- Build a scene and run physics simulation with **Genesis**
- Record data, apply domain randomization, and train a visuomotor policy with **LeRobot**
- Go end-to-end — from a scripted pick-and-place to a trained, closed-loop policy, with evaluation videos

> Note: this is a learning reference to show how to run simulation and training on an AMD GPU with `genesis-world` + `lerobot`; the trained model's success rate is not guaranteed.

## 如何参赛 / 提交

**pls fork this repo and open a pull request including the stuff that is mentioned in Rules&conditions of luma page. the title of pull request should be like "Track x, Team name, your application name"**

> [!IMPORTANT]
> Team name was an optional field on the Luma registration form. If you did not fill in a team name when you registered, please use your own name instead, so the title of the pull request should be like **"Track x, Your name, your application name"**.

> [!NOTE]
> All submission materials, project descriptions, and Pull Requests should be submitted in English.

以下内容为赛事官方说明，原样保留：

- 参赛与 AMD Radeon GPU 使用指引见 [官方 README](https://github.com/AMD-DEV-CONTEST/Radeon-hackathon-2026-07/blob/main/Radeon-Cloud-User%20Guide/README.md)
- **提交方式**：fork 本仓库，开 Pull Request，标题格式为 `Track x, Team name, your application name`
- 所有提交材料、项目描述和 PR **需使用英文**

## 各 Track 提交要求（摘要）

- **Track 1 · 多模态内容创作工具**：项目文档(PDF) + 源码(含 README) + 演示视频(3–5min) + 补充材料(PPT/Poster 任选)
- **Track 2 · 私有 AI Agent 本地部署**：规格文档 + 源码(含 README) + 演示视频 + 补充材料
- **Track 3 · 物理 AI / 机器人仿真**：技术报告 + 源码(建议带 Docker) + 复现 README + 演示视频 + 补充材料

> 详细规则以官方 Luma 页面和仓库为准。复现 README 需包含环境搭建、执行使用、依赖说明、逐步复现步骤，让评审能复现结果。

## 我的提交

- **参加 Track**：Track 2 · 私有 AI Agent 开发与本地部署
- **项目简介**：Radeon-Assistant（对外作品名「磐石」）。一个基于 AMD Radeon GPU + ROCm 的**本地私有 AI Agent 系统**，定位为学习 / 开发阶段作品。推理全程在本地 GPU 完成，支持本地知识库（RAG）、工具调用、多步任务规划，以及高危操作的人工审批与审计日志。近期补充了面向**硬件研发**的使用场景特化（硬件领域 system prompt、Verilog/Testbench 本地生成工具、芯片手册 PDF 表格 / 引脚解析）。
- **用的显卡**：AMD Radeon Pro W7900（Radeon Cloud，单卡 48GB）
- **Demo / 代码位置**：`submissions/Neoh/`（说明见该目录 README.md）

## Reflection

- **ROCm 跑通体验**：在 Radeon Cloud 的 W7900 上用 vLLM + ROCm 7.2.1 跑通了 Qwen2.5（14B / 7B FP16）。W7900 / RX7900 属 gfx1100，需在 vLLM 前设置 `HSA_OVERRIDE_GFX_VERSION=11.0.0` 才能被识别。实测 14B 约 27.5 tok/s、7B 约 46 tok/s。
- **踩的坑**：① 消费级 / 专业卡 gfx1100 不被 vLLM 官方 wheel 默认识别，必须 override GFX 版本；② 多卡张量并行（TP）必须用 spawn 启动；③ Windows 桌面环境无法跑 ROCm 推理，需 Linux + AMD GPU（本地开发靠 Radeon Cloud）。
- **当前局限（客观）**：模型选型 14B 还缺系统的对比评测数据；Verilog / Testbench 目前是 LLM 轻量生成（不接 iverilog 等仿真器做自动验证）；硬件能力属于「使用场景特化」，并非从零自研的 EDA 引擎。
- **下次改进**：补 7B / 14B / 32B 小评测作为选型依据；考虑接 iverilog 做生成代码的仿真自检；把更多真实芯片手册纳入硬件知识库。
