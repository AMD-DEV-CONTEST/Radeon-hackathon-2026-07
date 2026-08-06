# SUBMISSION_CHECKLIST — 黑客松提交清单（在役）

> **权威信源**：`docs/TRUTH.md` §4（参赛规则与截止）。本文是**交付物追踪清单**，不是信源；与 TRUTH 冲突时以 TRUTH 为准。
> **用途**：四大交付物 + PR 的逐条打勾视图。**每项完成后更新状态与日期**——交付物没有清单闸是"视频/PPT/PR 全没做却没人发现"的根因，本文就是那个闸（2026-08-04 建）。
> **截止**：2026-08-06 23:59 (UTC+8)；**缓冲**：2026-08-05 前提交 PR。

---

## 0. 硬性前提（必须先绿）

| # | 项 | 状态 | 备注 |
|---|---|---|---|
| 0.1 | `pytest tests/` 全绿 | ✅ 2026-08-04 | 230 passed / 0 failed（GPU 实例 `/opt/venv` 实测；v11 的 206 为 f01ce17 前未全量实跑的陈旧数，已更正；路由回归 `test_skill_map_routing` 已修） |
| 0.2 | `scripts/verify_bugfixes.py` EXIT=0 | ✅ 2026-08-04 | 含 §8 测试数机器闸 ≥180 |
| 0.3 | `git fsck` 无 missing/broken | ✅ 2026-08-04 | |
| 0.4 | 本地未提交改动已 commit | ✅ 2026-08-04 | MoL 热切换 e2e（中文路由 + relay embedder 注入）已提交 f01ce17 |

## 1. 交付物① Project Specification（`docs/SPEC.md`）

| 项 | 状态 | 备注 |
|---|---|---|
| SPEC 存在、英文 | ✅ | |
| 测试数/专家状态与 TRUTH 同步 | ✅ 2026-08-04 | L160 改 185 passed/2 skipped/0 failed；teichai 无权重已标 |
| 提交前从 TRUTH 反向同步 | ✅ 2026-08-04 | v10 数据已核对 |

## 2. 交付物② 源码 + README

| 项 | 状态 | 备注 |
|---|---|---|
| README 英文 5 章 | ✅ | Scenario / Architecture / Capabilities / Deployment / Optimization |
| README 环境配置/启动指南/依赖 | ✅ | §4 Run + HOW_TO_OPEN.md |
| README 与 TRUTH 关键数据一致 | ✅ 2026-08-04 | §5 补 KV 实测 + 质量闸 |
| gateway 五层调优旋钮已实现 + 接入生产 | ✅ 2026-08-04 | `gateway/{capacity,config,thinking,reliability,cli}.py` 落地（TRUTH §1.7 v12）；`gateway/cli.py` 已真机接管实例整栈启动（替代手动 setsid + 手动 relay），ctx=131072(fit 真值)，ngl 优先 fit 输出；证据 `_e2e_evidence/gateway_wire_in.md` |
| relay MoL 热切换端到端真机 PASS | ✅ 2026-08-04 | 中文/自然语言查询真实触发加权专家切换（btl3/cybersec/rag_n7），详见 TRUTH §1.5；证据 `_e2e_evidence/mol_e2e_20260804_*.md` |
| 仓库干净可 clone 即跑 | ⚠️ 待 commit 后确认 | 0.4 完成后跑一次 fresh clone 冒烟 |

## 3. 交付物③ 演示视频（3–5 分钟，须露 `rocm-smi`）

| 项 | 状态 | 备注 |
|---|---|---|
| 录制脚本/演示流程 | ⚠️ 未准备 | 需真机（远程 W7900）录制；demo_workspace 语料 + deploy/w7900/RUNBOOK.md 已备 |
| 视频文件（.mp4） | ❌ **未录** | **唯一关键路径**，8/4 前必须启动 |
| 露 `rocm-smi` 证据 | ❌ | 评审硬性要求（Track 2 规则） |

## 4. 交付物④ PPT / Poster（≤10 页）

| 项 | 状态 | 备注 |
|---|---|---|
| 大纲 | ⚠️ | `docs/_archive/PPT_OUTLINE.md`（10 页大纲，已归档 STALE——内容可用但需去归档化/重建） |
| 成品（.pptx / .pdf） | ❌ **未做** | 数据全在 bench/ + TRUTH，制作约 2h |

## 5. PR（fork 上游 + 提 PR）

| 项 | 状态 | 备注 |
|---|---|---|
| fork `AMD-DEV-CONTEST/Radeon-hackathon-2026-07` | ❌ 未做 | 2026-08-04 核实 1105s110martin-art 下无 fork |
| 推送分支 | ❌ | 0.4 commit 后 push |
| PR 标题英文 "Track 2, <队名/姓名>, <应用名>" | ❌ | 全英文要求（上游 README 规则） |

---

## 打开即用的检查命令

```bash
pytest tests/ -q                              # 0.1
python scripts/verify_bugfixes.py             # 0.2
git fsck                                      # 0.3
```

> 每次改动后跑一遍 0.1–0.3；全部 ✅ 才允许动 §1–§5 的勾。
