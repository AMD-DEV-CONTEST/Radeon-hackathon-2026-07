# Track 3 Soccer Robot — Submission Spec

> **Spec ID:** T3-SDD-2026-08-06
> **Author:** (team)
> **Date:** 2026-08-06
> **Status:** Active (final submission)
> **Deadline:** 2026-08-06

---

## 1. 目标

在 AMD Radeon GPU 上交付**真实踢球 → 进球**的人形机器人足球项目（Booster T1 + Genesis + ROCm），
满足官方 5 大评分维度（100 分）。核心主张：机器人摆腿、**脚面真实接触足球**、把球推入球门，
全部由物理冲量产生，无脚本赋值、无摔倒素材。

### 1.1 评分维度

| # | 维度 | 分值 |
|---|------|------|
| 1 | 机器人能力表现（训练收敛+任务指标+奖励分量） | 30 |
| 2 | AMD ROCm 采用（GPU/ROCm/吞吐/延迟/VRAM） | 20 |
| 3 | 创新性（首个 AMD GPU 人形足球管线） | 20 |
| 4 | 实际应用价值（Sim2Sim+部署路径） | 20 |
| 5 | 上游开源贡献（可复用 Genesis 足球环境） | 10 |

### 1.2 交付物

- 技术报告（`docs/technical_report.md`）
- 源代码 + README（`README.md` / `README_zh.md`）
- 成片视频（`acceptance/final_video/track3_final_20260806.mp4`，87.7 s 英文终版：英文幻灯片 + 英文字幕 + 微软神经配音）
- 证据：训练日志、GPU 遥测、模型 SHA-256、真踢球 `result.json`

---

## 2. 当前状态（2026-08-06 终版）

### 2.1 已达成（已验证）

| 资产 | 状态 | 数据 |
|------|------|------|
| **真踢球 → 进球（主提交物）** | ✅ | contact@116 → scored@144，球速 4.33 m/s，0 摔倒，288 帧 1080p30 |
| **可复现性** | ✅ | 4/4 独立运行全部进球 0 摔倒（contact 116–117 / scored 144–147 / 2.7–4.3 m/s） |
| PPO 训练收敛 | ✅ | 500 轮, reward -24→+93, 4618 steps/s |
| t1_walk.pt 行走模型 | ✅ | stance 60 步/0 跌倒, gait 150 步/6.4m |
| chase_v8_policy.onnx | ✅ | 19→3 dim, 0.4ms 推理, 46467 params |
| GPU 证据 | ✅ | 612 条遥测, 峰值 100% 利用率, 23.7GB VRAM；gfx1100/96CU、torch 2.9.1+HIP 7.2 |
| 多机器人稳定性（支撑证据） | ✅ | 18 场干净运行 0 异常退出；恢复率 83–93%（t1_walk.pt） |
| 本地测试 | ✅ | 151 passed |

### 2.2 成片结构（`track3_final_20260806.mp4`，87.7 s，英文 v12）

1. 背景与目标 → 2. 系统架构（底层行走策略走近足球）→ 3. AMD GPU 与 ROCm（真实命令/输出）
2. 运行过程（真实命令行 + 实况日志）→ 5. 最终效果与量化指标（真踢球慢动作/回放）
3. 创新点与未来工作（真机迁移、端到端强化学习踢球、多机器人协同）

成片素材只使用**真踢球原片**（`demos/exp/run4_kick_final.mp4`：摆腿 → 脚触球 → 球被推动）；无倒地素材、无脚本设球速。
配音使用微软神经 TTS（en-US，`edge-tts` 管线），非本地系统合成音；字幕为英文。

---

## 3. 复现

```bash
# 真踢球渲染（胜利配方）
/opt/venv/bin/python3.12 render_kick_final.py          # 读取 kick_params.json
#    期望：contact@116 -> scored@144，球速 ~4.3 m/s，0 摔倒

# P1 追球训练（无对手）
/opt/venv/bin/python3.12 run_task9_p1.py --max_iterations 240 --num_envs 2048 --phase A

# 单场景策略评测（300 步）
/opt/venv/bin/python3.12 run_task9_eval.py --ckpt runs/task9_p1/model_latest.pt --steps 300
```

---

## 4. 提交门禁（Go/No-Go）

- [x] 真踢球规范运行通过（contact/scored/球速/0 摔倒）
- [x] 4 次独立复现全部进球
- [x] 本地测试通过（151 passed）
- [x] 成片无倒地素材，措辞与 README 一致
- [x] README/技术报告/成片叙事一致
- [x] 匿名提交（无个人标识、无实例访问信息）
