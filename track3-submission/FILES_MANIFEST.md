# Track3 文件清单（2026-08-06 终版，路径全部真实存在）

## 提交物核心

| 文件 | 说明 |
|------|------|
| `README.md` / `README_zh.md` | 主 README（英文/中文），单机器人真踢球叙事 |
| `SPEC.md` | 提交规格：评分维度 / 当前状态 / 复现 / 门禁 |
| `acceptance/final_video/track3_final_20260806.mp4` | **最终成片**（87.7 s, 1080p30, 六段叙事, 英文 v12：英文幻灯片 + 英文字幕 + 微软神经配音） |
| `docs/technical_report.md` | 技术报告（真踢球核心 + AMD ROCm 证据） |
| `scripts/render_kick_final.py` | ★ 真踢球渲染脚本（胜利配方） |
| `render_kick_final.py` | SPEC §3 复现入口（工作区根，读取 `kick_params.json`） |
| `kick_params.json` | ★ 踢球配方参数（球偏移 0.22m、hip/knee 幅度、关节索引） |
| `run_task9_p1.py` | P1 追球训练脚本（rsl_rl 5.4.2，支持续训） |
| `run_task9_eval.py` | 单场景策略评测（300 步，SPEC §3） |
| `amd-physical-ai-soccer/Dockerfile` | ★ 唯一 canonical 提交镜像（非 root + Jupyter token 强制） |
| `amd-physical-ai-soccer/requirements-lock.txt` | 参考 ROCm 实例 `pip freeze` 锁文件（官方 6.3） |
| `docs/DOCKER.md` | Docker build / run / 复现三入口命令 / 推送闭环命令 |
| `scripts/docker_build_push.sh` | 一条命令完成 build + tag + push（在 AMD 主机运行，需先 `docker login`） |
| `presentations/track3_presentation_en.pptx` | **展示 PPT**（8 页英文幻灯片，与成片同画面同叙事） |
| `PR_DESCRIPTION.md` | 官方提交 PR 描述（含 Docker 与视频链接位） |

## 证据

| 目录/文件 | 内容 |
|-----------|------|
| `kick_final/` | `result.json`（contact/scored/球速，规范运行） |
| `demos/exp/` | `run4_kick_final.mp4`（真踢球原片）+ 4 个比赛演示（1v1 射门 / 3v3 比赛 / 规则行走 / task-7d） |
| `outputs/metrics/` | 官方 6.2 结构：`kick_final_result.json`、比赛结果、`model_hashes.csv`、`gpu_telemetry.csv` |
| `outputs/videos/` | 官方 6.2 结构：比赛演示 + 真踢球原片镜像 |
| `acceptance/training/` | `training_curve.csv`、`model_hashes.csv` |
| `acceptance/performance/` | `gpu_telemetry.csv`（612 条遥测） |
| `acceptance/single_agent/` | 单智能体评测日志 + 奖励分量 JSON |
| `acceptance/evaluation/` | `metrics.json`、`team_metrics.csv`、`client_metrics.csv` |
| `acceptance/remote/` | `codex_rocm_environment.txt`、`codex_canonical_sha256.txt` 等 |
| `acceptance/summary.json` | 验收汇总 |
| `reports/` | 基线与评测证据 |

## 历史/内部文档（不提交，保留于 `archive/_internal/`）

- 过程决策（`decisions/`）、RoboCup 参考笔记、安全审计报告、C 阶段评测日志、多机器人基线输出等
  已归档至 `archive/_internal/process_docs/`（git-ignored，不进入提交物）。

## 实例信息（已清除，勿再引用）

- 实例访问信息/凭据在公开文档中已 redact；详见历史提交记录（secret-scrub）。
