> ⚠️ STALE：本文件已归档，唯一信源见 docs/TRUTH.md。
# ScrewShell — 新接手 Agent 总入口（AGENT_ONBOARDING）

> 最后更新：2026-07-29。**本文是你需要先读的唯一文档。** 读完它，你就能掌握项目进度、现状、如何运行与验证、关键决策与陷阱，以及全部文档的地图。
> 权威细节在 `screwshell/docs/`（见末尾"文档地图"）。历史/过时资料已归档到 `screwshell/docs/_archive/`。

## 0. TL;DR（30 秒）

- **ScrewShell 是什么**：一个**完全本地、私有**的 AI 调查智能体，跑在 **AMD Radeon PRO W7900（ROCm 7.2.4）** 上。给它一个工作区，它规划多步调查、用本地 RAG 取证据、调只读本地工具、产出**带行级引用的可核验答案**。
- **技术栈（已定，path-D）**：`llama.cpp` + **Qwen3.6-27B（Q4_K_M, 16.8GB）** + **4 个 GGUF LoRA 专家**热切换。不是 vLLM、不是 9B/PEFT、不是旧三专家（sygnif/DeltaCoder/metro）。
- **当前状态**：验收闸 **G1–G5 全部通过**。本地回归 `pytest screwshell/tests/test_mol_llamacpp.py` = **9 passed / 1 skipped**（skip = torch 精度对照，本机无 GPU 预期跳过）。竞赛（AMD AI DevMaster Hackathon 2026, Track 2）提交截止 **2026-08-06**。
- **最终阵容（铁律，勿擅改）**：`tool/code→btl3`，`agent→teichai_fable5_plan`，`security→cybersec`，`doc→rag_n7`，`base→None`。已移除 `hermes_s2`（基座静默错配）、`fable5`（仓库 404/私有化）。

## 1. 架构一览

```
用户 → screwshell CLI/UI（规划调查）
        └─ SkillRouter（按 task_tag 选专家）
             └─ MoLLlamaCpp（mol_engine）
                  └─ llama.cpp llama-server（OpenAI 兼容 API）
                       └─ 冻结基座 Qwen3.6-27B + 运行时热挂/卸 GGUF LoRA
```

- **路由**：`SkillRouter.DEFAULT_SKILL_MAP` 把任务 tag（tool/code/agent/security/doc/base）映射到专家名。路由逻辑纯 Python，本机可 pytest。
- **热切换**：`llama-server` 以 `--lora-init-without-apply` 启动（上来不挂任何 adapter）；运行时 `POST /lora-adapters` 传 `[{"id":N,"scale":1.0}]` 激活某专家，`body []` 回基座原生。adapter 的 `id` 由 `GET /lora-adapters` 按挂载顺序推导，**不写死**。
- **代码位置**：包在 `screwshell/screwshell/`（子模块 `core/` 路由+引擎、`rag/`、`tools/`、`memory/`、`safety/`、`ui/`）。

## 2. 最终专家阵容与回退

| 任务 tag | 专家（GGUF） | 角色 | 来源 HF 仓库 | tensor 数 | 回退 |
|---|---|---|---|---|---|
| tool / code | `btl3` | 工具调用 / 代码 | `badtheorylabs/BTL-3` | 992 | — |
| agent | `teichai_fable5_plan` | 规划 / 调查编排 | `TeichAI/Qwen3.6-27B-Fable-5-Experimental-LoRA` | 992 | 若退化 → base 原生 thinking |
| security | `cybersec` | 安全审查 | `hotdogs/qwen3.6-27b-cybersecurity-lora` | 512 | — |
| doc | `rag_n7` | 文档/证据问答 | `lananhyeuem/qwen3.6-27b-multilingual-rag-lora-n7` | 992 | 行为不达标 → `None`（基座原生） |
| base | `None` | 纯基座原生思考 | — | — | — |

> 所有 adapter 的 `base_model_name_or_path` = `Qwen/Qwen3.6-27B`（G2 闸校验）。BTL-3 钉死 revision `6a9e13bd…`。

## 3. 验收状态（G1–G5）

| 闸 | 内容 | 结果 |
|---|---|---|
| G1 转换 | 4 adapter 全转 GGUF，tensor 数同族一致 | PASS |
| G2 基座 | 基座 revision 一致、adapter base 同源 | PASS |
| G3 行为 | 同 prompt 下 基座 vs +adapter 输出 DIFFERS 且无空输出/退化 | PASS（4 专家全 3/3 差异） |
| G4 热切 | `POST /lora-adapters` 控制面均值 <1ms | PASS（0.5–0.8ms / 均值 0.65ms） |
| G5 回归 | `tests/test_mol_llamacpp.py` 新阵容名 | PASS（**9 passed / 1 skipped**） |

- **性能（关思考，W7900）**：decode 基座 ~26 tok/s、+LoRA 23–26 tok/s；模型加载 9s；显存 ~21/48GB；热切均值 0.65ms（n7 1.9GB 未拉高）。权威原始数据：`screwshell/bench/benchmark_pathd.json`。
- **本机无法复验的部分**：G1–G4 的远程运行时实测（需 GPU 实例）。这些依赖 `bench/LORA_GGUF_GATES.md` 的远程记录。

## 4. 如何运行与验证

### 4.1 本机（Windows，无 GPU）—— 只验证路由/逻辑/文档同步
```bash
cd screwshell
pytest tests/test_mol_llamacpp.py -q      # → 9 passed, 1 skipped
```
测试覆盖：SkillRouter 路由与回退、MoL 引擎加载逻辑、**两道"文档同步闸"**（断言 `bench/benchmark_pathd.json` 与 `DEFAULT_SKILL_MAP` 不得含 hermes_s2/fable5、必须含四专家——防止阵容漂移复发）。

### 4.2 远程 GPU 实例（真推理/转换只在那跑）
```bash
ssh -i ~/.ssh/id_ed25519 -p 31033 root@36.150.116.206   # 公网 IP，仅经隧道；勿 0.0.0.0 裸跑
export HF_ENDPOINT=https://hf-mirror.com                  # HF 直连超时，必须走镜像
# 启动（逗号分隔多 LoRA + 默认不挂、运行时激活）
/persistent/llama.cpp/build/bin/llama-server \
  -m /persistent/models/Qwen3.6-27B-Q4_K_M.gguf \
  --lora /persistent/loras/teichai_fable5_plan/adapter.gguf,/persistent/loras/btl3/adapter.gguf,/persistent/loras/cybersec/adapter.gguf,/persistent/loras/rag_n7/adapter.gguf \
  --lora-init-without-apply --host 127.0.0.1 --port 8080 -ngl 99 -fa on -c 8192
# 激活专家（数组格式！）：POST /lora-adapters [{"id":N,"scale":1.0}]；回基座 []
```
- 关键路径（实例持久盘 `/persistent`，实例销毁不清）：基座 `…/models/Qwen3.6-27B-Q4_K_M.gguf`；llama.cpp `…/llama.cpp`；转换 venv `…/venv_llamacpp`；LoRA `…/loras/<name>/adapter.gguf`。

## 5. 关键决策与"为什么"（避免重新踩坑）

- **为什么走 llama.cpp（path-D）而不是 vLLM？** vLLM 在 RDNA3/W7900 不可行：FP8 被 gate、需定制 torch 不兼容 ROCm。见 `VLLM_ROCM_FEASIBILITY.md` §5–6。
- **为什么是这 4 个专家？** 对 349 个候选 adapter 扫描（238 个技能级过关），按"base 同源 Qwen3.6-27B + 任务覆盖"选定。见 `OFFICIAL_TREE_WHITELIST.md`。
- **为什么移除 hermes_s2？** 它的真实基座是 `samscrack/Qwen3.6-27B-Opus-CoT-Stage1`，**不是** Qwen3.6-27B → 静默错配，G3 会显示假差异。铁证见 `LORA_SOURCE_VERIFICATION.md`。
- **为什么移除 fable5？** 仓库 404/私有化，从未成功下载。
- **为什么 base 用 None 而非某个专家？** 纯基座原生 thinking 作为规划兜底，避免错配专家污染。

## 6. 陷阱清单（新 Agent 必看）

1. **SSH 私钥是 `id_ed25519`，不是 `id_rsa`**（旧文档里 `C:\Users\dd\.ssh\id_rsa` 是错的/历史）。
2. **`HF_ENDPOINT` 必须设镜像**，否则 HF 直连超时。
3. **`--lora` 必须逗号分隔单次传**（新 llama.cpp 不支持重复 `--lora`，只认最后一个）。
4. **Qwen3.6 是推理模型**：先吐 `reasoning_content` 可能占满 `max_tokens` 导致 `content` 为空 → 表现为"输出空/LoRA 没生效"假象。解法：关思考 `chat_template_kwargs:{"enable_thinking":False}`（推荐）或把 `max_tokens` 提到 ~1100。
5. **`convert_lora_to_gguf.py` 第一个位置参数是本地目录**（含 adapter_model.safetensors），不是 HF repo id；只有 `--base`（本地目录），没有 `--base-model-id`；**输出目录必须提前 mkdir**，否则末尾 `FileNotFoundError`。
6. **G1 判据**：同族 tensor 数一致（teichai/btl3/n7=992，cybersec=512）。
7. **回退预案**：rag_n7 行为不过 → doc 改 `None`；teichai 退化 → agent 改 `None`。
8. **`pkill -f llama-server` 经 SSH 会杀掉你自己的会话**（命令行字符串匹配）→ 用 `pkill -x`。

## 7. 文档地图

### 7.1 当前权威（读这些）
| 文档 | 用途 |
|---|---|
| `AGENT_ONBOARDING.md`（本文件） | 总入口：进度/现状/运行/陷阱/地图 |
| `screwshell/README.md` | 包级总览（架构图、能力、运行法） |
| `screwshell/docs/SPEC.md` | 架构规格（权威） |
| `screwshell/docs/HANDOFF_EXPERT_ROSTER.md` | 阵容+回退+G1–G5 闸定义+实例要点（权威交接入口） |
| `screwshell/docs/LORA_SOURCE_VERIFICATION.md` | hermes_s2 错配铁证 |
| `screwshell/docs/OFFICIAL_TREE_WHITELIST.md` | 349 adapter 扫描与四专家选型依据 |
| `screwshell/docs/PATH_D_IMPLEMENTATION.md` | 执行手册（启动命令、DEFAULT_SKILL_MAP，含阵容变更 banner） |
| `screwshell/docs/PATH_D_HANDOFF.md` | 实例逐阶段真实执行记录（含转换墙补丁） |
| `screwshell/docs/VLLM_ROCM_FEASIBILITY.md` | 为什么不走 vLLM |
| `screwshell/docs/{COMPETITION_STRATEGY,PPT_OUTLINE,SUBMISSION_CHECKLIST,VIDEO_SCRIPT}.md` | 竞赛策略/材料（提交截止 2026-08-06） |
| `screwshell/bench/LORA_GGUF_GATES.md` | G1–G5 闸结果（权威） |
| `screwshell/bench/LORA_GGUF_GATES_RECON.md` | 文档漂移对账与闭环记录 |
| `screwshell/bench/benchmark_pathd.json` | path-D 权威性能原始数据 |
| `screwshell/bench/BENCHMARK_STATUS.md` | 性能引用护栏（path-D 数 vs 9B 历史基线） |
| `.workbuddy/memory/MEMORY.md` | 项目长期记忆（最紧凑的真相源） |

### 7.2 已归档（历史/已过时，标记为 removed）
位于 `screwshell/docs/_archive/`：
- `INSTANCE_FINDINGS_AND_Z_PLAN.md` — 旧 9B 实例勘察 + 曾被否决的 vLLM 倾向（path-D 已取代）。**保留**。
- ~~`root_docs_mirror/`~~ — **已删除 (removed)**。原根 `docs/` 的 4 个 md 副本，已合并去重。
- ~~`root_bench/`~~ — **已删除 (removed)**。原根 `bench/` 原始数据副本（9B-PEFT 历史）。
- ~~`root_demo_workspace/`~~ — **已删除 (removed)**。原根 `demo_workspace/` 副本（demo 语料）。

> 说明：早期仓库在根目录有一套与 `screwshell/` 重复的 `docs/`、`bench/`、`demo_workspace/`。2026-07-29 已把根副本合并去重，规范来源统一为 `screwshell/`，原根副本归档到 `_archive/`。

## 8. 待办 / 开放项
- G1–G4 远程运行时仅能在 GPU 实例复验，本机只覆盖 G5 逻辑与文档同步闸。
- `rag_n7` 行为验收与热切成本已在闸文档记录，但**尚未在实例上独立重测**（依赖 G4 数字）。
- 竞赛材料需在 **2026-08-06** 前提交；提交后 `COMPETITION_STRATEGY.md` 可归档。
- 若未来引入新专家，务必同步更新：`DEFAULT_SKILL_MAP`、`bench/benchmark_pathd.json`、`HANDOFF_EXPERT_ROSTER.md`、并让 G5 两道同步闸继续兜底（勿手动绕过）。
