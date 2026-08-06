# ⚽ 人形机器人足球 — AMD Radeon GPU（赛道三）

[![AMD ROCm](https://img.shields.io/badge/AMD-ROCm%207.2-ED1C24?logo=amd&logoColor=white)](https://www.amd.com/en/products/software/rocm.html)
[![Genesis](https://img.shields.io/badge/Genesis-1.3.1-blue)](https://genesis-embodied-ai.github.io/)
[![torch](https://img.shields.io/badge/torch-2.9.1%2Bgitff65f5b-green)](https://pytorch.org/)

**AMD AI DevMaster 2026 — 赛道三：Physical AI（人形机器人足球）**

在 AMD Radeon（ROCm）上构建的层级机器人足球系统：人形机器人自主走近足球、摆腿、
**脚面真实接触足球**、并把球推入球门——全部在 Genesis 物理引擎 + AMD GPU 上完成，全程无 NVIDIA 硬件。

## 项目状态（2026-08-06）

| 主线 | 状态 | 证据 |
|------|------|------|
| **主提交物：单机器人真踢球 → 进球** | ✅ **PASSED** | 蓄力 → 摆腿 → 脚触球（`contact@116`）→ 进球（`scored@144`），球速 **4.33 m/s**，0 摔倒 — 成片 `acceptance/final_video/track3_final_20260806.mp4` |
| 可复现性（4 次独立运行） | ✅ **PASSED** | 4 次全进球且 0 摔倒：contact 116–117 / scored 144–147 / 球速 2.7–4.3 m/s — 见 `kick_final/result.json` 与 `kick_live/result.json` |
| 单机器人追球（历史） | ✅ PASSED | 200 步，0 摔倒，球位移 12 m |

**提交策略**：单机器人真踢球视频为保底交付物；README 中的所有结论均有仓库内真实仿真记录支撑（脚本 + 参数 + 日志 + `result.json`）。

## 真踢球证据（核心交付物）

成片展示的是一条**真实踢球动作链**——无任何脚本赋值：

```
走近足球 → 风车蓄力 → 前摆 → 脚面接触足球 → 球被推动 → 进球
```

- 胜利配方 `kick_params.json`：球置于右脚前方 0.22 m；摆动 `hip:+1.0 / knee:-1.6`（蓄力）→ `hip:-1.8 / knee:+1.8`（前摆）→ 保持；关节索引 `R_HIP=6, R_KNEE=16, R_ANK=18, L_KNEE=15`。
- 踢球阶段 `clip_actions = 100.0`，腿部摆动不被钳制——球速完全由物理冲量产生（非脚本设速）。
- 规范运行（2026-08-06）：`contact@116`（脚触球）→ `scored@144`（球越过球门线 x=7.0），峰值球速 **4.33 m/s**（`kick_final/result.json`，单机位渲染），**0 摔倒**，288 帧 @ 1920×1080/30fps。
- 成片所用多机位渲染实测 **3.54 m/s**（`kick_multi_result.json`，contact@116 → scored@145）——两者均为同一配方下的真实物理运行，对应 `result.json` 随仓库分发，每个数字都可追溯。
- 原始证据：`scripts/render_kick_final.py` + `kick_params.json` + 带时间戳运行日志 + `result.json`（本会话复现 4 次全部进球）。

## 架构

```text
高层踢球控制器（速度指令 @ 10 Hz）
    │  蓄力/前摆阶段的关节级覆盖（hip/knee/ankle）
    ▼
冻结行走模型 t1_walk.pt（720 维观测 → 21 维关节目标 @ 50 Hz）
    │  action_scale=0.16, clip_actions=100.0（踢球阶段）
    ▼
Genesis 物理引擎 on AMD Radeon GPU（ROCm 7.2 · gfx1100 · 96 CUs）
    └─ 1080p 多机位渲染 + 逐步指标（contact/scored/球速）
```

## 演示

| 视频 | 路径 | 内容 |
|------|------|------|
| **最终成片（1:28）** | `acceptance/final_video/track3_final_20260806.mp4` | 87.7 s，六段叙事（背景 → 架构 → AMD GPU/ROCm → 运行 → 效果/指标 → 创新），英文幻灯片 + 英文字幕 + 微软神经配音，真踢球素材 |
| 比赛演示 | `demos/exp/*.mp4`（同步至 `outputs/videos/`） | 1v1 射门、3v3 比赛、规则行走基线、task-7d 运行 |
| 真踢球原始渲染 | `demos/exp/run4_kick_final.mp4` + `kick_final/result.json` | 蓄力 → 脚触球 → 进球，1080p30，contact@116/scored@144 |
| 展示 PPT | `presentations/track3_presentation_en.pptx` | 8 页英文幻灯片，与成片同画面同叙事 |

## 快速开始（AMD 实例，`/workspace`）

```bash
# 1) 真踢球渲染（复现成片踢球场景）
/opt/venv/bin/python3.12 render_kick_final.py          # 读取 /workspace/kick_params.json
#    输出 /workspace/kick_final/kick_final.mp4 + result.json

# 2) P1 追球训练（无对手）
/opt/venv/bin/python3.12 run_task9_p1.py --max_iterations 240 --num_envs 2048 --phase A

# 3) 单场景策略评测（300 步）
/opt/venv/bin/python3.12 run_task9_eval.py --ckpt runs/task9_p1/model_latest.pt --steps 300
```

本地（无 GPU）：`python3 -m pytest track3-soccer/tests/ --ignore=tests/test_e2e.py -q`。

## 目录布局

```text
track3-soccer/
├── SPEC.md                  # 提交规格（评分维度/状态/交付物）
├── FILES_MANIFEST.md        # 真实路径索引
├── scripts/render_kick_final.py   # ★ 真踢球渲染（胜利配方）
├── kick_params.json         # ★ 踢球配方参数（球偏移、hip/knee 幅度）
├── run_task9_p1.py          # P1 训练脚本（rsl_rl 5.4.2，支持续训）
├── run_task9_eval.py        # 单场景策略评测
├── configs/                 # hierarchical_agent.yaml
├── demos/                   # 演示视频 + exp/（真踢球渲染、比赛演示）
├── presentations/           # track3_presentation_en.pptx（8 页英文 PPT）
├── outputs/                 # 官方 6.2 结构：metrics/ + videos/
├── reports/                 # 基线与证据
├── acceptance/              # 成片 + 验收证据
├── docs/                    # technical_report.md、DOCKER.md
└── LICENSE                  # MIT
```

## 验证状态（已验证）

| 检查项 | 结果 |
|--------|------|
| 真踢球 → 进球（规范运行） | contact@116 · scored@144 · **4.33 m/s** · 0 摔倒 · 288 帧 1080p30 |
| 可复现性 | 4/4 次进球、0 摔倒（contact 116–117 / scored 144–147 / 2.7–4.3 m/s） |
| 本地测试 | 151 passed |
| 单机器人追球（历史） | 200 步，0 摔倒，球位移 12 m |
| P1 训练吞吐 | ~4,600 steps/s，2048 envs on AMD Radeon |

## 复现所需时间（官方 README 第 10 项）

在单张 AMD Radeon RX 7900 XTX 级别 GPU（ROCm 7.2、gfx1100、96 CUs）上实测：

| 步骤 | 命令 | 耗时 |
|------|------|------|
| 真踢球渲染（成片踢球场景，288 帧 1080p30） | `python render_kick_final.py` | ~2–5 分钟 |
| P1 快速冒烟（256 envs，100 轮） | `python run_task9_p1.py --max_iterations 100 --num_envs 256 --phase A` | ~5 分钟 |
| P1 完整训练（2048 envs，240 轮） | `python run_task9_p1.py --max_iterations 240 --num_envs 2048 --phase A` | ~45–60 分钟 |
| 规范完整训练（已记录） | 500 轮，2048 envs | 1 小时 35 分钟 |
| 单场景评测（300 步） | `python run_task9_eval.py --ckpt runs/task9_p1/model_latest.pt --steps 300` | < 5 分钟 |
| 本地测试（CPU） | `python3 -m pytest tests/ --ignore=tests/test_e2e.py` | ~2 分钟 |

从干净检出到端到端复现：**约 1.5–2 小时**（AMD 实例）。

## 已知限制

- **近距离控球**（~2 m）：无精细盘带。
- **ROCm 求解器**：Newton 求解器在多机器人场景下超出 gfx1100 本地内存限制；CG 求解器回退可用但较慢。

## 提交对齐

| 官方要求 | 位置 |
|----------|------|
| 技术报告 | `docs/technical_report.md` |
| 源代码 + Docker | 本仓库 + `amd-physical-ai-soccer/Dockerfile`（唯一 canonical 镜像，见 `docs/DOCKER.md`） |
| 可复现性 | `## 快速开始` + `render_kick_final.py` + `kick_params.json` |
| 演示视频 | `acceptance/final_video/track3_final_20260806.mp4`（87.7 s，英文版，真踢球） |
| 官方仓库结构 | `outputs/metrics/` + `outputs/videos/` + `LICENSE`（README 第 10 项已补） |
| AMD GPU 证据 | 终端实拍：`rocm-smi` / `amd-smi`（gfx1100）/ torch 2.9.1+HIP 7.2（在成片与 `docs/technical_report.md` 中） |
