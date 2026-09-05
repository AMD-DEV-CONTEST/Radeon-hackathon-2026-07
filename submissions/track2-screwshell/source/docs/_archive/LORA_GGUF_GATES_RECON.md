> ⚠️ STALE：本文件已归档，唯一信源见 docs/TRUTH.md。
# LORA_GGUF_GATES.md × 项目实际情况 对账（2026-07-29）

> **状态：✅ 已修复（2026-07-29）**。下方"发现的漂移"三条均已闭环——见文末"修复记录"。
> 本文件保留为问题定位与流程教训记录。

> 目的：把 `bench/LORA_GGUF_GATES.md`（闸结果文档）与仓库真实代码/配置逐条核对，
> 确认"闸过了"到底覆盖了什么、没覆盖什么。结论：**G1–G5 代码与远程运行时部分可信；
> bench 配置与部分文档仍停留在清阵容之前的 hermes_s2/fable5 状态——这是文档漂移，不是代码失败。**

## 一、逐条验证

| 闸 / 声明 | 文档说法 | 仓库实际 | 判定 |
|---|---|---|---|
| G1 转换闸 | 4 个 adapter 转 GGUF，tensor 数同族（teichai/btl3/n7=992，cybersec=512） | 远程实例产物，本机无 GPU 无法复验；但 `router.py` / 测试已按这 4 个名字接线 | 远端可信，本机不可验 |
| G2 基座 revision 闸 | 三个新 adapter `base_model_name_or_path` == `Qwen/Qwen3.6-27B` | `router.py` 头部注释逐条写明四专家均上游核验 == `Qwen/Qwen3.6-27B`；`hermes_s2`/`fable5` 列入"Removed 黑名单" | ✅ 一致 |
| G3 行为闸 | 4 专家关思考对比，均 DIFFERS=True，无静默挂空 | 远程运行时结论，本机不可复验 | 远端可信 |
| G4 热切延迟闸 | btl3 0.5 / cybersec 0.8 / teichai 0.6 / n7 0.7 ms | 远程运行时结论，本机不可复验 | 远端可信 |
| G5 回归闸 | `tests/test_mol_llamacpp.py` 已改新阵容；`7 passed / 1 skipped` | **本机实测：`7 passed, 1 skipped in 2.11s`（torch 缺失跳 1 个 parity 测试）**；测试内 `_Handler.preloaded` 与断言确实用 btl3/teichai/cybersec/rag_n7 | ✅ **完全吻合（已复跑确认）** |
| G5 补充 | `scripts/test_local_logic.py` 全 PASS | 文件存在（未跑，但非 G5 主闸） | ⚠️ 未复验 |
| `router.py` 已切新阵容 | 暗示 skill_map 用 btl3/cybersec/teichai/rag_n7 | `DEFAULT_SKILL_MAP` = tool→btl3, code→btl3, agent→teichai_fable5_plan, security→cybersec, doc→rag_n7, base→None；hermes_s2/fable5 显式列入 Removed | ✅ 已落地 |
| `--lora` id 顺序 | 复跑命令按 teichai,btl3,cybersec,n7 挂；T1 表按 btl3,cybersec,teichai,n7 列 | `MoLLlamaCpp.load_base()` 通过 `GET /lora-adapters` **运行时推导 id**，不写死顺序 | ✅ 顺序无关，非 bug（仅文档两处排序不一致， cosmetics） |

## 二、发现的漂移（闸没覆盖到的地方）

### 🔴 1. `bench/benchmark_pathd.json` 仍是"清阵容之前"的快照
这是最实打实的一处。该文件与闸文档同目录（bench/），且被 SPEC.md / README.md / BENCHMARK_STATUS.md / PATH_D_HANDOFF.md 当作**权威原始数据**引用，但它里面：
- `server_args`（L6）：仍挂载 `hermes_s2/adapter.gguf,teichai_fable5_plan/adapter.gguf` —— **旧的两专家阵容，且含已被判死刑的 hermes_s2（静默错配基座）**。
- `behavior_diff_temp0`（L30）：仍是 `hermes_s2_tool` 那条（错配基座上测的无效结论）。
- `adapters`（L35/37）：`hermes_s2` 标 `converted:true`（608 tensor，旧错配数据），`fable5` 标 `converted:false`；**新阵容 btl3/cybersec/rag_n7 一个都没有**。
- SPEC.md L105、README.md L86 还写着"Measured results … raw data `benchmark_pathd.json`"，于是读者顺着引用看到的是 hermes_s2 阵容 + 旧性能数字（base 31 tok/s、热切 2.09ms），与闸文档 G4 的新数字（0.5–0.8ms、~26 tok/s）对不上。

> HANDOFF_EXPERT_ROSTER.md L78 当时就明确写了："`bench/benchmark_pathd.json` 里 hermes_s2 的 behavior 数据是在错配基座上测得的，**无效数据**，更新 bench 时一并清理/标注。" —— **这条没闭环。**

### 🟡 2. 多份叙事文档仍带 hermes_s2 / fable5 的运行命令与叙事
- `docs/PATH_D_HANDOFF.md`：L61-62/64/90/103-120/132/147/171/175/225-228 仍含 hermes_s2 启动命令、fable5 401 阻塞叙述。
- `docs/PATH_D_IMPLEMENTATION.md`：大量 hermes_s2/fable5 的 `DEFAULT_SKILL_MAP` 旧写法、旧 `--lora` 命令、旧激活 id 注释。
- `docs/COMPETITION_STRATEGY.md`：仍以"hermes_s2 是 #1 风险、须在 8/6 前排掉"为框架写，且说 SPEC/PPT/VIDEO 仍带 hermes_s2（实际 SPEC 已改，但策略文档自身未更新）。
- `docs/VLLM_ROCM_FEASIBILITY.md` L285：仍把 hermes_s2/fable5 当作已定阵容写。
- 已正确更新的：`docs/SPEC.md`（L56-57/87-90/94/114 已切新阵容并标注 hermes_s2 作废）、`docs/HANDOFF_EXPERT_ROSTER.md`、`docs/OFFICIAL_TREE_WHITELIST.md`、`docs/SUBMISSION_CHECKLIST.md`、`docs/PPT_OUTLINE.md`、`docs/VIDEO_SCRIPT.md`。

## 三、流程层根因（为什么"闸过了"却还有漂移）

1. **验证闸的覆盖范围 ≠ 仓库范围。** G5 只跑 `tests/test_mol_llamacpp.py`（验证逻辑层 + 路由映射），G1–G4 只验远程实例产物。没有任何一道闸去核对 `bench/*.json`、`docs/*.md` 这些**静态叙事/配置产物**是否同步到了新阵容。
2. **"清理 bench"是 HANDOFF 里的一条手写待办，没有变成可回归的闸。** 它依赖人记得去改 `benchmark_pathd.json`，而没人验。这正是 djb 反复点出的老问题：**静态正确（代码/测试绿）和运行时验证都有了，但"文档/配置与已验证运行时是否一致"这层闸缺位**。
3. **致命点**：`benchmark_pathd.json` 被 SPEC/README 当成"权威实测原始数据"引用。它虽不被 `benchmark_mol.py` 直接读取（那脚本走 PEFT 扫描 `LORA_DIR`），但**任何信任它的人都会以为她的mes_s2 还在阵容里、且性能数字来自旧阵容**——等于把 G3 专门要消灭的"静默错配"又从文档侧放了进来。

## 四、建议的最小修复（开箱即用，不动生产逻辑）

1. **刷新 `bench/benchmark_pathd.json`**：`server_args` 改成四专家 `--lora` 命令；`adapters` 改成 btl3/teichai/cybersec/rag_n7（含 tensor 数 992/992/512/992、大小 466.9M/934M/79.7M/1.9G），删除 hermes_s2/fable5 条目；`behavior_diff_temp0` 用闸文档 G3 结论重写。或至少顶部加一行 `"status": "STALE — superseded by LORA_GGUF_GATES.md, do not cite"`。
2. **把"文档/配置同步"补成一道闸**：在 G5 里加一个 `grep` 断言——仓库内（除 LORA_SOURCE_VERIFICATION.md 证据文档外）不应再出现 hermes_s2 作为"在用专家"，`benchmark_pathd.json` 的 `server_args` 不得含 hermes_s2。这样漂移会在 CI 里自己冒头。
3. **清理 stale 文档**（PATH_D_HANDOFF / PATH_D_IMPLEMENTATION / COMPETITION_STRATEGY / VLLM_ROCM_FEASIBILITY 中的 hermes_s2/fable5 运行命令与旧阵容叙述）。

> 要我直接执行第 1、3 步（刷新 bench 配置 + 清理 stale 文档），或把第 2 步的"文档同步闸"写进 `tests/` 吗？这些都只是配置/文档改动，不动推理逻辑。

## 五、修复记录（2026-07-29，已完成归档动作）

1. **`bench/benchmark_pathd.json` 已被刷新**：`server_args` 改为四专家 `--lora` 命令（teichai/btl3/cybersec/rag_n7），`adapters` 改为四专家（含 tensor 数/大小/base），`hermes_s2`/`fable5` 移入 `removed` 字段并标注作废；性能数字改用 `LORA_GGUF_GATES.md`的 G4 值（~26 tok/s、热切 0.5–0.8ms）。
2. **G5 已加"文档同步闸"**：`tests/test_mol_llamacpp.py` 新增 `test_bench_config_has_no_removed_experts` 与 `test_skill_map_excludes_removed_experts`，断言 `benchmark_pathd.json` 与 `DEFAULT_SKILL_MAP` 不得含 hermes_s2/fable5、必须含四专家。本机复跑 = **9 passed / 1 skipped**（torch parity 跳过）。*注：开发中该闸一度因 server_args 嵌套在 `meta` 下 + 路径解析写错而"假绿"，修正后真正咬住过旧数据，确认有效。*
3. **stale 文档已清理完成**：
    - `docs/PATH_D_HANDOFF.md`：L90 启动命令改为四专家；L108-120 / L225-228 的 hermes_s2 转换命令标注为"历史命令，不再执行"（顶部已有阵容变更 banner）。
    - `docs/PATH_D_IMPLEMENTATION.md`：补阵容变更 banner；L188-198 启动命令改四专家；L289-298 `DEFAULT_SKILL_MAP` 改新阵容；L110-117 工具专家章节标"历史"。
    - `docs/VLLM_ROCM_FEASIBILITY.md`：补 banner；L285"三专家覆盖"句改为最终四专家阵容。
    - `docs/COMPETITION_STRATEGY.md`：本就已有"已解决"状态 banner，跳过。
    - 残余的 hermes_s2/fable5 提及均处于带 banner 的历史叙事语境，无未标注的可执行运行命令。

> **Note**: root_docs_mirror / root_bench / root_demo_workspace 已在 2026-07-29 删除，此处仅保留历史记录索引。

> 流程教训落地：漂移根因（"缺文档/配置与已验证运行时同步的闸"）现在由第 2 步的 CI 断言兜底——任何把 hermes_s2/fable5 重新写回 bench 配置或 skill_map 的提交都会让 G5 红。

## 第二轮清理（2026-07-29 · 整合总入口 + 归档）

对账后又发现 RECON 的"已闭环"结论不严谨——仍有两处未标注的可执行 stale 命令、根 `README.md`/`DEPRECATED.md` 误导、以及根目录与 `screwshell/` 重复的 `docs/`、`bench/`、`demo_workspace/`。本轮处理：

1. **整合总入口**：新增仓库根 `AGENT_ONBOARDING.md`——新 Agent 唯一先读文档，覆盖 TL;DR、架构、最终阵容、G1–G5、运行验证、关键决策、陷阱清单、文档地图（current vs archived）、待办。
2. **修正误导声明**：根 `README.md` 从 9B/PEFT 旧设计改为准确简版并指向 `AGENT_ONBOARDING.md`；`DEPRECATED.md` 改为准确的"归档与布局说明"（澄清 workspace 是活仓，旧"外层已废弃"指控不准）。
3. **归档去重**：`screwshell/docs/_archive/` 新建；根 `docs/`（4 md 副本 + csv 已并入规范 `screwshell/docs/`）、根 `bench/`（原始数据副本）、根 `demo_workspace/`（语料副本）合并去重后归档；`INSTANCE_FINDINGS_AND_Z_PLAN.md`（vLLM 时期历史）也归档。
4. **修残留 stale 命令**：`PATH_D_IMPLEMENTATION.md` §阶段5 的 `hermes_s2`/`fable5` curl 示例改为四专家并标历史；`BENCHMARK_STATUS.md` 的 2.09ms 旧数改为 0.65ms 均值/0.5–0.8ms 每专家、启动命令改四专家、hermes_s2 行为差标注为错配无效；`LORA_GGUF_GATES.md` G5 计数 7→9；`screwshell/README.md` 的 2.09ms 与 hermes_s2 描述同步修正。

复跑：`pytest tests/test_mol_llamacpp.py -q` → **9 passed / 1 skipped**。至此 RECON 的"已闭环"在文档侧成立。
