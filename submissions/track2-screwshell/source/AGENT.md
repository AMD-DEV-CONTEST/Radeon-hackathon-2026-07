# AGENT.md — ScrewShell 入口（唯一信源索引）

> ⚠️ 本仓库所有"项目目的 / 技术事实 / 参赛状态"的**唯一权威信源是 `docs/TRUTH.md`**。
> 旧文档（COMPETITION_STRATEGY.md、HANDOFF_EXPERT_ROSTER.md、PROJECT_REVIEW_2026-08-02.md、PROJECT_SUMMARY.md 等）已归档至 `docs/_archive/` 并标记 STALE/ARCHIVED，**不再作为真相依据**。当前在役 docs：`TRUTH.md`（信源）、`SPEC.md`（参赛交付物，非信源）、`AUTOTUNE.md`（autotune 细节，从属信源）；`E2E_OPTIMIZATION.md` / `FRONTEND_TOOL_E2E_STRATEGY.md` 为保留的工作 / 方法论文档（非信源，结论以 TRUTH 为准）。代码（`screwshell/`）本身永远是最低层事实。

## 快速导航
- 项目是什么 / 架构 / 最终 LoRA 阵容 / 验收状态 → **`docs/TRUTH.md` §1–§3**
- autotune 三层系统 / L3 双档换装（热切 0.65ms vs 重启换装 ~5s）/ 真机验证结论 → **`docs/TRUTH.md` §1.6**；细节 → **`docs/AUTOTUNE.md`**
- 产品定位（自研网页 agent + 兼容 opencode/pi + 规划中统一观测/调优层）→ **`docs/TRUTH.md` §1.7**；兼容/tool 失效调查 → **`docs/HANDOFF_GATEWAY_RELOCATION.md`**
- 黑客松提交清单与截止日 → **`docs/TRUTH.md` §4**
- 赛前落地路线（转 LoRA / 录视频 / PR）→ **`docs/TRUTH.md` §5**
- 禁止事项与已知坑（含 W7900 远程实例坑）→ **`docs/TRUTH.md` §6**

## 给 Agent 的硬规则
1. 任何关于"阵容 / 提交 / 状态"的判断，先读 `docs/TRUTH.md`，不要信未归档的旧 md。
2. 不要编辑 `D:\AI\screwshell`（独立的旧历史快照，只读参考）。规范工作副本是本 Git 仓库（`D:\AI\git\screwshell`），所有改动在仓库内提交到 GitHub。
3. 技术事实以 `screwshell/` 代码为准；文档与代码冲突时，以代码 + TRUTH.md 为准。
4. `hermes_s2` / `fable5` 为永久禁用专家，禁止重新引入（见 TRUTH.md §6）。
5. W7900 远程实例（SSH 端口 31010）上，当前代码在 `/workspace/persistent/screwshell_run`；`/workspace/persistent/screwshell` 是旧快照勿用。`--l3-mode tight` 必须配 `--launch-cmd`；`--takeover` 仅在确认可接管目标端口时用（见 TRUTH.md §6.5）。
