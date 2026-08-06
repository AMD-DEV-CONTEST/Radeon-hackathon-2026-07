> ⚠️ STALE：本文件已归档，唯一信源见 docs/TRUTH.md。
# 归档与布局说明（原 DEPRECATED）

> 本文档**不再表示"整个 `D:\ai\screwshell-v2` 已废弃"**。该目录就是当前活的工作区。
> 此文件仅说明：哪些材料已归档、为什么，以及规范文档现在在哪里。

## 现状
- `D:\ai\screwshell-v2` 是 **live 工作区**。代码、文档、benchmark 的规范来源统一在 **`screwshell/`** 子目录。
- `D:\ai\screwshell` 是一个单独的 old history snapshot（旧历史快照），不要编辑。
- 早期仓库在根目录有一套与 `screwshell/` **重复**的 `docs/`、`bench/`、`demo_workspace/`。2026-07-29 已合并去重，原根副本归档到 `screwshell/docs/_archive/`：
  - `root_docs_mirror/`（4 个竞赛文档副本）— **已删除**
  - `root_bench/`（benchmark 原始数据副本）— **已删除**
  - `root_demo_workspace/`（demo 语料副本）— **已删除**
- `INSTANCE_FINDINGS_AND_Z_PLAN.md`（旧 9B 实例勘察 + 被否决的 vLLM 方向）也已移入 `screwshell/docs/_archive/`（保留）。

> **注意**: root_docs_mirror / root_bench / root_demo_workspace 已在 2026-07-29 归档后被删除，此处仅保留历史记录索引。

## 新 Agent 该读什么
1. **`AGENT_ONBOARDING.md`**（仓库根）——唯一入口，覆盖进度/现状/运行/陷阱/文档地图。
2. `screwshell/README.md` —— 包级总览。
3. `screwshell/docs/` 下的规范文档（见 `AGENT_ONBOARDING.md` §7 文档地图）。
4. `screwshell/docs/_archive/` —— 仅历史/过时材料（现仅含 INSTANCE_FINDINGS_AND_Z_PLAN.md + README.md），勿当作现行事实。

## 关键更正
旧版本文件曾声称"外层 docs/ 描述的是退役 9B/3 专家设计"——此描述已**不准确**：根 `docs/` 在归档前的内容与 `screwshell/docs/` 字节级相同（均为 27B 新栈）；真正过时的只有根 `README.md`（9B/PEFT 旧设计，现已改为指向 `AGENT_ONBOARDING.md`）。
