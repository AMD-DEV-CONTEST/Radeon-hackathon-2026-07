# ScrewShell 自动调优系统（autotune）文档

> **文档状态说明**：本文件记录 *autotune* 子系统当前内容。其中 **L1 + L2 已实现并可测**（#1、#2 完成）；**L2 护栏 tuner/doctor（#4）与一键 CLI（#5）已实现**；**#7 重启换装实测已完成并拍板走 A（动态换装 + 三道闸）**；**L3 运行时治理（#6）已实现、已接进 `Orchestrator`，并于 2026-07-30 在 W7900 真机端到端验证通过**（tight 模式真实重启换装 4 专家全通过，证据 `_e2e_evidence/*.log`，详见 §6.6）。
> 本文件从属于唯一信源 `docs/TRUTH.md`（§1.6 为权威摘要）；冲突时以 TRUTH.md + 代码为准。
> 代码 `screwshell/autotune/` 永远是最低层事实——本文与代码冲突时以代码为准。

---

## 0. 它解决什么问题

ScrewShell 跑在单张 AMD W7900（48GB）上，用 **MoL（同一冻结 27B 基座 + 多个 LoRA 专家热切换）** 实现"多专家技能"。但"这一张卡到底能装下几个专家、用哪种量化、装不下时怎么办"，不能靠拍脑袋。

`autotune` 把这件事做成**可探测、可规划、可插拔**的子系统：

- **探测**本地/远程显卡的真实显存与算力 →
- **规划**底模量化 + LoRA 阵容（借鉴 llmfit 的四维评分，而不是简单档位表）→
- **如实降级**（装不下就承认装不下，退为纯基座，不硬撑——即"阵容铁律"）→
- （规划中）**运行时治理**：显存紧张时动态换装专家、反馈调参。

它同时兑现了 README 的承诺 *"plug-and-play: drop a GGUF adapter in, gain a skill"*——把 LoRA 封装成带 `manifest.json` 的技能包，路由阵容从目录**扫描生成**，社区丢个文件夹进来就多一个技能。

---

## 1. 三层架构总览

| 层 | 职责 | 模块 | 实现状态 |
|---|---|---|---|
| **L1 SkillPack** | 底模 / LoRA 封装成带 `manifest.json` 的技能包；目录扫描生成路由阵容；底模指纹钉死防错配 | `skillpack.py` | ✅ 已实现 |
| **L2 探测 + 规划** | 硬件探测（rocm-smi / nvidia-smi）、量化推荐、四维评分选型、降级阶梯 | `hardware.py` `planner.py` | ✅ 已实现 |
| **L3 运行时治理** | 双档 LoRA 调度（宽裕热切 / 紧张重启换装 + 步骤聚类）+ 保守档位机（tok/s / 空答率 / 显存水位反馈） | `governor.py` + `core/orchestrator.py` | ✅ 已实现并接进 orchestrator |

> `tuner.py`（降级调优）、`doctor.py`（部署前预检）、`__main__.py`（一键 CLI + 人话报告）属任务 #4、#5，**已实现**：`tuner.resolve()` 把 `PlanResult` 落成可执行的 `DeploymentSpec` 并强制"阵容铁律"，`doctor.preflight()` 做部署前护栏（底模/权重文件存在性、指纹校验、端口占用），`__main__.py` 串起 detect→scan→plan→doctor→tuner 一键出报告。

---

## 2. L1 SkillPack —— 把"底模 / LoRA"变成可插拔技能包

### 2.1 `manifest.json` schema

每个技能包是一个文件夹，内含 `manifest.json`：

```json
{
  "name": "btl3",                         // 包名（唯一）
  "kind": "lora",                         // "lora" | "base"
  "skill": "tool",                        // 旧式单技能标签（兼容字段，建议用下面的 skills）
  "skills": ["tool", "code"],             // 本包服务的规范技能标签，可多个（如 btl3 同时管 tool+code）
  "base_fingerprint": "Qwen/Qwen3.6-27B", // 底模指纹，钉死基座版本（防 hermes_s2 式静默错配）
  "vram_gb": 0.8,                         // 该 LoRA 额外占用的显存（GB），底座另算
  "domain_tags": ["code", "tool"],         // 领域标签
  "route_keywords": ["code", "refactor"],  // 路由关键词（供 SkillRouter 匹配）
  "smoke_test": {                         // 一条冒烟用例
    "prompt": "Explain why this benchmark is slow and propose a fix.",
    "expect_contains": ["function", "benchmark"]
  }
}
```

**字段要点**
- `skills`（列表）优先于 `skill`（单值）。一个包可以服务多个规范技能——这正是首版设计踩的坑：btl3 实际管 `tool`+`code`，若只写单值 `skill` 会被算成只覆盖 4/5 技能、误判为 `reduced`。
- `base_fingerprint` 为空 = "不校验"（兼容老包）；非空则必须和**已部署底模**完全一致，否则该包在扫描时被直接丢弃。
- GGUF 权重文件本身**不在仓库内**，用户自备；`manifest.json` 只是元数据。

### 2.2 扫描与构建路由阵容

```python
from screwshell.autotune import scan_skillpacks, build_skill_map

packs = scan_skillpacks("screwshell/autotune/skillpacks")   # {包名: SkillPack}
skill_map = build_skill_map(packs, deployed_base="Qwen/Qwen3.6-27B")
# -> {"base": None, "tool": "btl3", "code": "btl3", "security": "cybersec",
#     "doc": "rag_n7", "agent": "teichai_plan"}
```

`build_skill_map` 永远把 `"base"` 映射到 `None`（冻结基座、不挂适配器）；**指纹不符的 LoRA 包被静默丢弃**——这就是 hermes_s2 防护。

路由层提供接驳点：`SkillRouter.from_packs(packs_dir, deployed_base=...)`（懒导入调用上述逻辑，**保留**旧的 `DEFAULT_SKILL_MAP` 作兜底）。⚠️ 现状核对（2026-08-04）：`from_packs` **尚无生产调用方**——默认阵容仍由 `DEFAULT_SKILL_MAP` 直接驱动；该接口为 skillpack 扫描→路由的预留接驳点，接线上线前勿将其描述为已生效。

### 2.3 加一个新专家（即插即用三步）

1. 在 `screwshell/autotune/skillpacks/<你的名字>/` 放 `adapter.gguf` 和 `manifest.json`；
2. `base_fingerprint` 写死 `"Qwen/Qwen3.6-27B"`，`skills` 填它服务的规范技能；
3. 重扫目录——路由阵容自动多一项，无需改任何路由代码。

### 2.4 hermes_s2 防护（为什么要有指纹）

历史事故：某 LoRA 在错误底模上静默加载，跑起来才发现能力错位。现在 `base_fingerprint` 在**加载期**就拦掉错配包，而不是等到运行时才爆。

---

## 3. L2 硬件探测 + 规划器

### 3.1 硬件探测 `detect()`

`hardware.py` 优先 `rocm-smi`（AMD），回退 `nvidia-smi`（NVIDIA），再回退 `unknown`。
**纯 stdlib（不 import torch/CUDA）**，所以能在部署主机（rocm-smi 所在地）上跑，也能在本地用 mock 跑单测。

产出 `HardwareProfile`：`vendor` / `name` / `vram_total_gb`，以及派生的：
- `vram_usable_gb` = 总显存 − 2GB 系统/KV 预留；
- `recommend_quant()` = 在可用显存内挑**质量最高**的量化；
- `estimate_toks()` = 粗略解码速度（tok/s）估算；
- `fit_score()` = 某需求显存能否装下的 0~1 分。

底模按量化的显存占用（规划估值，GB，Qwen3.6-27B GGUF）：

| 量化 | Q2_K | Q3_K_M | Q3_K_L | Q4_K_S | Q4_K_M | Q5_K_M | Q6_K | Q8_0 |
|---|---|---|---|---|---|---|---|---|
| 显存 | 11.0 | 14.0 | 15.5 | 16.5 | 18.9 | 21.0 | 24.0 | 29.0 |

> ⚠️ 这些是**规划估值**。真实加载地板由 `scripts/bench_restart_swap.py` 在实机上测（见 §6）。

### 3.2 规划器 `plan()` 与四维评分

```python
from screwshell.autotune import detect, scan_skillpacks, plan

prof = detect()
packs = scan_skillpacks("screwshell/autotune/skillpacks")
res = plan(prof, packs, target_base="Qwen/Qwen3.6-27B")
print(res.report)          # 人话部署报告
```

`plan()` 在底模占用后的预算内，**贪心**挑选 LoRA 包（优先补齐未覆盖的规范技能、优先小包以装更多专家），然后给四维评分：

| 维度 | 含义 |
|---|---|
| `fit` | 底模+LoRA 能否装进可用显存（0~1） |
| `speed_toks` | 预估解码速度（tok/s） |
| `quality` | 量化质量（Q8 > Q4 > Q2） |
| `coverage` | 5 个调查技能（tool/code/agent/security/doc）被覆盖的比例 |

### 3.3 降级阶梯（"阵容铁律"）

覆盖度决定降级档位，**绝不为装不下而硬撑**：

| 档位 | 条件 | 行为 |
|---|---|---|
| `full` | coverage = 1.0 | 全量阵容，所有技能有专属专家 ✅ |
| `reduced` | 0 < coverage < 1.0 | 只保留装得下的专家；未覆盖技能回退底模原生能力 |
| `base_only` | coverage = 0 | 显存连一个 LoRA 都装不下 → **如实降级为纯基座（native thinking）**，不挂载任何专家 ⚠️ |

`PlanResult.report` 直接输出人话报告（中文），就是给非技术用户看的那一版。

---

## 4. 当前用法（程序化 API）

### 4.1 一键 CLI（已实现，任务 #5）

在部署主机上直接跑，输出人话报告 + 部署前护栏 + 部署规格；`--json` 可出机读结果。预检有阻断项时退出码非 0。

```bash
python -m screwshell.autotune \
    --packs-dir screwshell/autotune/skillpacks \
    --model /workspace/persistent/screwshell_run/models/Qwen3.6-27B-Q4_K_M.gguf \
    --loras-dir /workspace/persistent/screwshell_run/loras \
    --deploy-base Qwen/Qwen3.6-27B --port 8080
```

### 4.2 程序化 API

```python
from screwshell.autotune import detect, scan_skillpacks, plan
from screwshell.core.router import SkillRouter

prof = detect()
packs = scan_skillpacks("screwshell/autotune/skillpacks")
res = plan(prof, packs, target_base="Qwen/Qwen3.6-27B")
print(res.report)

# 用扫描结果覆盖路由阵容（兜底仍是 DEFAULT_SKILL_MAP）
router = SkillRouter.from_packs("screwshell/autotune/skillpacks",
                                deployed_base="Qwen/Qwen3.6-27B")
```

---

## 5. 测试状态

- `tests/test_autotune.py`：L1/L2/governor 单测（硬件探测回退、SkillPack 扫描、规划器降级阶梯、hermes_s2 指纹防护、tuner 阵容铁律、doctor 预检、CLI 装配、governor 双档/聚类/档位机——全部用 mock profile / 临时目录，**无需 GPU**）。
- `tests/test_orchestrator_l3.py`：L3 接驳集成测试 7 项（紧张档走 restart_with / 宽裕档走 activate / 挂载幂等 / 聚类保持依赖 / 降 ctx / 空答率关 thinking / 换装上限），无 torch 依赖。
- 全量 `tests/`：**133 passed / 1 skipped / 1 failed**（2026-08-03 本地基线，实测 `pytest tests/ -q` → `133 passed, 1 skipped, 1 failed`）。failed = `tests/test_eval_gate.py::test_run_eval_isolates_case_crash`，根因 `screwshell/eval/harness.py:84` 把 `orchestrator_factory` 调在 `try/except` 之外、单 case 崩溃未隔离，属已知代码 bug，待测修（不在本 autotune 子系统范围内）。
- 运行：`python -m pytest tests/ -q`

---

## 6. L3 运行时治理（已实现并接进 orchestrator）

### 6.1 L3 运行时治理 `governor.py`（#6，被 #7 阻塞）

- **双档 LoRA 调度**
  - **宽裕档**（如 W7900 48GB）：维持现状，全部 adapter 预载，`scale` 热切（仓库权威值 **~0.65ms**，非旧栈的 8.04ms），零改动。
  - **紧张档**（装不下全套）：llama-swap 式**重启换装** + 按专家聚类 TaskCard 步骤（把"每步一换"压到"每专家一换"）。实测代价：**单次换装 ≈ 4.6–5.1s**（W7900 48G，27B-Q4_K_M 重载整套底模 + 单 LoRA），4 专家任务最坏总等待 ≈ **19.4s**——远低于此前预判的 48–120s。
- **保守档位机**：tok/s 持续偏低 → 降 ctx；空答率高（思考占满假空坑）→ 调 max_tokens / 关思考；显存 >90% → KV 量化。**不做在线连续优化**（小白场景要"不出事"，不是榨最后 5%）。
- **已落地（2026-07-30）**：`screwshell/autotune/governor.py` 含 `select_mode` / `cluster_steps`（依赖感知贪心聚类，最小化换装次数且保持拓扑序）/ `Governor.observe`（三档反馈）/ `LlamaServerLifecycle`（重启换装的进程生命周期，仅杀自己进程组、takeover 显式可选）。单测见 `tests/test_autotune.py`（#6 段）。

### 6.2 #7 重启代价实测（决定紧张档走 A 还是 B）

换装重启的真实代价 = **重载整套 27B 底模 + LoRA**，不是"切换延迟"。已写好测量 harness `scripts/bench_restart_swap.py`（已加固：**只杀自己拉起的进程组，绝不误伤其他 agent 的服务**；默认拒绝在 8080 无 `--takeover` 时启动）。

- **已在 W7900 完成 #7 实测**（`--takeover` 占用那个空闲的 8080 服务，跑完干净清理自己）。

### 6.2.1 实测真值（2026-07-30，W7900 48G，27B-Q4_K_M + 单 LoRA）

| 指标 | 数值 |
|---|---|
| 单次换装（重载整套底模 + 单 LoRA）→ `to_serve_s` | **4.6 – 5.1 s** |
| 4 专家任务最坏总等待（每专家各重载一次） | **19.4 s** |
| 对比：宽裕档 `scale` 热切 | ~0.65 ms（毫秒级，零重启） |

> 此前预判"单次 12–30s、4 专家 48–120s"严重高估；**实测为准**。

### 6.2.2 决策：**走 A（动态换装 + 三道闸）**

理由：最坏仅 ~19s/4 专家，且配合**预测式预热身**（把 5s 重载藏到 ReAct 工具调用延迟后）大部分死等可被掩盖；相比 B（固定单专家）放弃 MoL 差异化不划算。三道闸：
1. **预测式预热身**：在工具执行空隙按 RouteDecision 序列预换下一个专家（进程级翻版 LoRAX 异步预取，通用所有硬件）。
2. **换装次数硬上限**：单任务超过 N 次换装即预警/建议收窄范围。
3. **带预估的进度 UI**：显示"专家 2/4，预计还需 ~18s"，而非一句模糊的"正在切换"。

### 6.4 governor 接进 `Orchestrator`（运行时换装驱动）

`core/orchestrator.py` 在构造时可选接入 `Governor` + `LlamaServerLifecycle`：

- **模式选择**：`Orchestrator._resolve_mode()` 决定 `roomy` / `tight`。
  - 显存装得下整套 → `roomy`：每步 `engine.activate()` 热切（~0.65ms，零重启）。
  - 装不下 → `tight`：每步 `LlamaServerLifecycle.restart_with(lora_path)` 重启换装（实测 ~5s/次）。
  - 幂等：已挂载的专家再次 `_mount` 是 no-op，避免 ReAct 循环里重复重启。
- **步骤聚类**：`run()` 执行前用 `cluster_steps()` 重排 TaskCard 步骤，**合成类技能（doc/agent）依赖前面所有步骤**，因此排到最后；其余步骤按专家聚合，把"每步一换"压到"每专家一换"，且保持拓扑序（不破坏步骤间因果依赖）。
- **保守档位机**：每次生成后把 `RuntimeMetrics`（tok/s、空答率、显存水位）喂给 `Governor.observe()`：
  - tok/s 持续偏低 → 降 ctx 档（转发给 `lifecycle.ctx_tokens`，下次重启生效；宽裕档仅发事件）；
  - 空答率高（思考占满假空坑）→ **实时关 thinking**（每请求生效）；
  - 显存 >90% → 触发 KV 量化（转发 `lifecycle.kv_quant`）；
  - 换装次数超 `max_swaps_per_task` → 发 `governor_alert` 事件。
- 所有模式切换 / 换装 / 档位调整都通过 `on_event(...)` 流式上报，UI 可据此做"诚实进度提示"。

### 6.5 CLI 暴露 L3 模式开关

运行时 CLI（`screwshell/cli.py`）新增：

```bash
python -m screwshell.cli --workspace <ws> \
    --l3-mode tight \            # auto | roomy | tight
    --launch-cmd '/opt/llama.cpp/build/bin/llama-server \
        --model /workspace/persistent/screwshell_run/models/Qwen3.6-27B-Q4_K_M.gguf \
        --lora {lora} --host 127.0.0.1 --port 8080 -ngl 99 -fa on -c {ctx}' \
    --takeover                   # 允许杀掉目标端口上已存在的 server（紧张档）
```

- `--l3-mode tight` **必须**配合 `--launch-cmd`（否则直接报错退出）——紧张档要自己掌控 server 生命周期。
- 模板支持 `{lora}` / `{ctx}` / `{kv}` 占位符；`{lora}` 留空时自动剥离 `--lora` 以跑纯基座。
- `--takeover` 仅在确认目标端口的服务可被接管时再开（如本会话那台 W7900 的空闲服务）。
- 部署规划 CLI（`python -m screwshell.autotune`）也新增 `--l3-mode`，会基于显存 vs 阵容负载**预测**运行时模式并打印，便于部署前核对。

### 6.6 真机端到端验证（2026-07-30，W7900 tight 模式，已通过）

**验证内容**：`python -m screwshell.cli --l3-mode tight --launch-cmd '...' --takeover` 在 W7900 上真实运行——不是 mock。原始日志证据在仓库 `_e2e_evidence/`（`run_tight.log` 自然语言整轮、`drive_multi.log` 确定性四专家换装）。

**结果**：
- 自然语言查询两轮均 EXIT=0，进度 UI 事件齐全（`[MoL restart-swap]` / `[MoL] mount` / `[plan]` / `[tool]` / `[step done]` / `[stats]`），stats 正确报 `switches=2`。
- 确定性驱动强制 agent→security→code→doc 四专家换装：teichai_plan (4.62s) → cybersec (4.57s) → btl3 (4.90s) → rag_n7 (5.07s)，每次均真实重启 `llama-server --lora <正确gguf>`，reload 与 §6.2.1 基准（4.6–5.1s）一致。

**真机暴露并修复的 3 个 bug（mock 测不出，教训：llamacpp 路径需要真机冒烟）**：
1. `app.py` llamacpp 后端曾跳过 lora 目录扫描 → `engine.adapters` 空 → `_mount` 查不到路径 → 每次"换装"重启成 base。已修：llamacpp 分支扫描目录、只解析 `.gguf`（safetensors 自动跳过）。
2. tight 模式 `_mount` 造了 `SwitchRecord` 未 append 进 `engine.switch_log` → stats 报 `switches=0`。已修。
3. CLI `vram=NoneGB` 显示瑕疵（llamacpp 无本地 VRAM 内省）→ 改显示 `n/a`。

**已知限制 / 环境坑**（同步收录于 TRUTH.md §6）：
- 路由名 `rag_n7` vs 磁盘目录 `n7` 不一致，真机靠 symlink 兜住，根治待对齐。
- llamacpp 后端无 VRAM 内省 → governor "显存>90% KV 量化"分支不触发。
- Qwen3.6-27B 默认 thinking 开启 → 首生成 content 空是预期，governor 会自动关 thinking。
- teichai planner 倾向把任务压成单 agent step，自然语言查询通常只见 2 次换装；多专家验证需确定性驱动。
- 远程当前代码在 `/workspace/persistent/screwshell_run`（`/workspace/persistent/screwshell` 是旧快照勿用）。

### 6.3 待办清单（任务系统）

| # | 任务 | 状态 |
|---|---|---|
| 1 | `hardware.py` 硬件探测 | ✅ 完成 |
| 2 | L1 SkillPack + L2 planner | ✅ 完成 |
| 3 | 单测 + 本文档 AUTOTUNE.md | ✅ 完成（10 passed；本文档） |
| 4 | `tuner.py` + `doctor.py` | ✅ 完成 |
| 5 | 一键 CLI + 人话报告 | ✅ 完成（`__main__.py`） |
| 6 | `governor.py` L3 运行时治理 | ✅ 完成（决策=A：双档调度 + 步骤聚类 + 保守档位机，已单测） |
| 7 | W7900 实测重启换装代价 → 拍板 A/B | ✅ 完成（实测走 A） |
| 8–11 | governor 接进 orchestrator + CLI 暴露 L3 开关 + 集成测试 + torch 解耦 | ✅ 完成 |
| 12–16 | W7900 真机端到端验证（含 3 个真机 bug 修复） | ✅ 完成（见 §6.6） |
| 待办 | `rag_n7`↔`n7` 命名对齐（改 router 映射或目录名）；llamacpp 真机冒烟纳入例行验证防"只过 mock" | ⏳ 未做 |

---

## 7. 相关文件索引

- `screwshell/autotune/__init__.py` — 包导出
- `screwshell/autotune/hardware.py` — `HardwareProfile` / `detect` / 量化表
- `screwshell/autotune/skillpack.py` — `SkillPack` / `scan_skillpacks` / `build_skill_map`
- `screwshell/autotune/planner.py` — `plan` / `PlanResult` / 降级阶梯
- `screwshell/autotune/doctor.py` — `preflight` / `PreflightReport`（部署前护栏）
- `screwshell/autotune/tuner.py` — `resolve` / `DeploymentSpec`（阵容铁律落地）
- `screwshell/autotune/__main__.py` — 一键 CLI 入口（`python -m screwshell.autotune`）
- `screwshell/autotune/skillpacks/<name>/manifest.json` — 4 个示例包（btl3 / cybersec / rag_n7 / teichai_plan）
- `screwshell/core/router.py` — `SkillRouter.from_packs()`（预留接驳点，尚无生产调用方，见 §2.2 现状核对）
- `screwshell/core/orchestrator.py` — L3 接驳：`_resolve_mode` / `_mount` / `_order_steps` / `_observe` / `shutdown`
- `screwshell/cli.py` — 运行时 CLI，`--l3-mode` / `--launch-cmd` / `--takeover`
- `tests/test_autotune.py` — L1/L2 单测
- `tests/test_orchestrator_l3.py` — L3 接驳集成测试（紧张档走 restart_with / 宽裕档走 activate / 聚类 / 档位机）
- `scripts/bench_restart_swap.py` — #7 重启换装代价测量 harness

---

## 8. 会话决策记录（2026-07-31）：autotune "该不该做" 的争议与终裁

> 附录：记录一次对 autotune 方案的外部审阅 + 三轮内部讨论，结论是把本会话的判断固化下来，供后续 agent / 提交前复查参考。代码真值永远在 `screwshell/autotune/` 与 `core/orchestrator.py`，本文冲突时以代码 + TRUTH §1.6 为准。

### 8.1 争议起点

- **原始诉求**：用户想"用网上现成最新技术，串起本地个人用户的部署"，痛点是"llama.cpp 一堆官方 flag，个人不同硬件不知道开哪些、设多少"。
- **最初提案**：纯 server-flag 调优器（flash-attn / 量化 KV cache / prompt cache reuse / 推测解码 / 流式），靠探测 + 微基准 + 公式选参数。
- **外部审阅三问（2026-07-31 前）**：
  1. 仓库身份混淆 + 27B 栈未跑通，autotune 是空中楼阁；
  2. `--fit` 差异化叙事漏洞（RDNA3 env 护栏依赖真机实测，否则悬空）；
  3. 与 8/5 提交截止的优先级冲突（应先跑通 e2e）。

### 8.2 经代码核实，审阅继承的两处过时事实

- "LoRA 待转 GGUF" —— **v2 时错、v7 已部分回归**：v2 阶段 `docs(SPEC): sync to TRUTH v2 — autotune/L3, T1 converted` 把 TRUTH §2 的"待转化(T1)"修正为四专家全转。但 **2026-08-02 TRUTH v7 回写现实**：`teichai_plan` 实际无 GGUF 权重来源、router 静默降级 base，故仅 `btl3`/`cybersec`/`rag_n7` 三专家常驻，teichai 为数据缺口（非 bug）。即"4 专家全转完（G1 PASS）"对 teichai 不成立——详见 `bench/LORA_GGUF_GATES.md` 现状注记与 TRUTH §2。
- "真机可能不在手边" —— 真机实例 `36.150.116.206:31010`（W7900 / ROCm 7.2.4 / 51.5GB）存在，G1–G5 即在上面跑；只是当时未确认是否仍在线。

### 8.3 审阅说对的硬事实

- `bench/day4_e2e.json` 是 9B-PEFT 栈、退休专家（BENCHMARK_STATUS.md L31 自证"path-D 之前"）——即当时 27B 上的 agent e2e 确为零。若 autotune 早于 e2e 则属空层。
- **隐藏真瓶颈**：day4_e2e.json 中 q1=180s、q2=102s（9B 成绩），暴露真瓶颈在 **agent 层串行 LLM 调用**，不是 server flag；180s 直接威胁 3–5 分钟 demo 视频录制。

### 8.4 终裁（用户更新代码后反转）

用户本轮提交后，autotune 已是 **L1/L2/L3 三层 + W7900 真机验证的产物**（见 §1 / §6.6 / `tests/test_orchestrator_l3.py`）。裁决：

1. autotune 是"本地部署规划器（L1/L2）+ 运行时治理（L3）"，**不是** server-flag 调优器 → "重造 `--fit`" 的担忧不构成问题（它从没想抢 `--fit` 的算层数）。
2. 差异化根基是实的：W7900 重启实测 4.9s、双档调度真机验证，都是用户自己机器上的真数，不是二手文档。
3. 审阅对"设计的 autotune"的攻击成立，但对"建成的 autotune"不成立——靶子已换。

### 8.5 提交前收尾待办（非新设计，是收尾）

1. （已修）TRUTH §2 teichai_plan 状态 → 无权重来源、降级 base（现实 3/4 可用；router 仍 `agent→teichai_plan` 静默降级）。
2. （已核对）`docs/AUTOTUNE.md` 本身 UTF-8 可读、与代码对齐，无需重写。
3. （已做）L1/L2/L3 + 双档调度已反向同步进 `docs/SPEC.md`（2026-08-02 与 TRUTH 对齐）。
4. （确认）`--l3-mode` / `--launch-cmd` / `--takeover` 是否已在实际用户入口（ui/app.py）文档化；主 README 启动命令仍是最简版。
5. （不阻塞）demo 录制前确认真机实例 `36.150.116.206:31010` 当前是否在线。

### 8.6 外部调查证据位置（子代理产出，未纳入仓库）

- 各 flag 硬件依赖公式：`C:\Users\dd\AppData\Local\Temp\opencode\autotune-flag-formulas.md`
- ROCm/RDNA3 坑 + OSS 自动调优先例：`C:\Users\dd\AppData\Local\Temp\opencode\autotune-rocm-priorart.md`
- 本会话决策摘要另存：`D:\git\screwshell\.omo\drafts\autotune-decision-2026-07-31.md`
## 9. 一键调优闭环（tune-loop，2026-08-06）

> 在调优页加「一键调优」按钮：读当前 llama-server 参数 → 按预设目标（快/省显存/大上下文/平衡）→ 单参数逐个调 → 自动重启 → A/B 对比调优前后 → 效果差自动回滚上一版 → 循环直到收敛或喊停。全程可看进度、可回滚。

### 9.1 架构与模块清单

| 模块 | 文件 | 职责 |
|---|---|---|
| ServerConfig 一等字段 | `screwshell/gateway/config.py` | `cache_type_k/v`/`flash_attn`/`parallel`/`n_batch` 一等字段；`to_argv()` 条件追加全参 argv（list 形式，无 shell 注入） |
| Lifecycle 重启原语 | `screwshell/autotune/governor.py` | `start_argv(argv, takeover)` 从 argv list 启动（无 shell）+ 接管外部生产 server + 返回 `(ok, to_serve)` 硬失败信号 |
| 综合打分 | `screwshell/autotune/scorer.py` | `score(events, gpu_samples, weights)` 加权（TTFT 0.4/decode 0.2/KV 0.2/ok 0.2），T4 样本纪律 MIN_N=16 不足返回 None |
| 预设映射 | `screwshell/autotune/mapper.py` | `preset(name, current)` → `TuneGoal`（speed/vram/ctx/balance 确定性）；`parse_natural_language` 二期 |
| 调优状态机 | `screwshell/autotune/cycle.py` | 闭环 idle→…→done/abort；注入式 lifecycle/scorer/planner/benchmark_generator/event_collector；落盘 `OBSERV_DIR/tune_state.json` |
| relay 端点 | `screwshell/gateway/relay.py` | `POST /v1/tune/{start,stop,status}` 变更型鉴权 + 409 + 状态落盘；start 后台 `asyncio.to_thread(cyc.run)` |
| UI | `screwshell/ui/app.py` | 一键调优/停止按钮 + 4 预设需求面板 + 进度/历史（2s 轮询）+ i18n zh+en |

### 9.2 单参数顺序（简单→复杂）

`ctx → cache-type → flash-attn → parallel → n-batch → threads → n-gpu-layers → reasoning-budget`。每步重启 + 打分 + 保留/回滚；一期**单参数逐个**，不做多参数组合/网格搜索。

### 9.3 铁律（贯穿全链路）

1. `reasoning_budget` 绝不 `-1`（config `__post_init__` 强制 4096）。
2. `--jinja` 必须保留（to_argv 已首位输出）；cycle apply 前二次校验。
3. 阵容铁律：显存不足不强挂 LoRA。
4. 无 shell 注入：argv 一律 list + `Popen(list)`，绝不 `shell=True`。
5. 跨机器重启**只走 relay tune 端点**，UI 不直接 kill/启动 llama-server。
6. 不改 observ schema：归因用时间窗（restart_ts 之后）+ 现有 `X-Benchmark` 标记，不加列。

### 9.4 失败升级（绝不静默停在宕机 server）

重启失败 → 回滚 `last_good_argv`；回滚重启也失败 → 还原调优前 `original_argv`；再失败 → `ABORT` + `server_may_be_down=True`（status 明示，evidence 留 `llama_server.log` tail）。收敛：连续 2 轮 `|Δ|<5%` 或最多 8 轮；`stop()` 保留当前已应用配置。

### 9.5 闭环真正可打分

每次重启成功、进入 collect 前，`cycle` 经 relay 驱动 `MIN_N` 条 `X-Benchmark:1` chat-completions，轮询 observ 直到 ≥MIN_N 条 benchmark 事件落库，**然后**才 collect + score。否则闭环永远"样本不足"无法比较。

### 9.6 范围边界（一期不做）

- 不做多参数矩阵/网格搜索。
- 不改 orchestrator 行为（mapper 只走规则，不引 engine/LLM）。
- 不在本机 UI 直接重启 llama-server（跨机器铁律）。
- 不自动覆盖 dirty worktree；不碰未提交改动。
- 本机不装 GPU/llama 依赖；真实闭环在实例验收。
- 不新增重型依赖（scorer/mapper/cycle 用 stdlib）。
- 二期做自然语言需求解析（S3 冲突，标二期）。
