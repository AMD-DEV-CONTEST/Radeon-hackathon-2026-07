# ScrewShell 观测台 — 施工计划 V3（展示改造：四视图 + 趋势分位数 + 因果行动提示）

> 执行者：HY3。自包含文档。前置：`BUILD_OBSERVATORY_PLAN_V2.md`（V2 已交付 f724f98/e7aad4e）、`TTFT_BREAKDOWN_REPORT.md`（P0 分析）、`TTFT_OPTIMIZATION_PLAN.md`（P1 施工中）。
> 来源：2026-08-05 02:15 用户 UI 面板解读调研（12 模块 = 4 问；4 参照系对标：llama-hud / vLLM+Grafana / Langfuse+Phoenix / opencode TUI）。
> 生成：2026-08-05。

---

## 0. 背景与结论

### 0.1 用户痛点（策划/PM 视角，本计划的验收尺子）
- 观测台把 12 类信息**平铺成一面文字墙**，非技术用户看不懂每块是什么、更不知道该怎么用。
- 实测证据（用户贴的 UI 内容）：「解码速度 25.9 tok/s ⚠️ 正常 15–25」——**健康值被标 ⚠️**（v16 `e7aad4e` 已把阈值改为 floor-only ≥20，但部署机若仍显示旧文案 = 跑的是旧代码，P0 后一并同步）。⚠️ 符号语义不可靠 = 小白失去信任的起点。
- 慢的因果链未可视化：首字延迟 30238ms ↔ 推理槽 37248 token ↔ ⚠️会话过长 39762 tok，三个数字明明指向同一根因（长 prompt prefill），面板上却互不关联。

### 0.2 调研结论（4 参照系，抄什么）
| 参照系 | 做法 | V3 抄什么 |
|---|---|---|
| llama-hud（llama-server 终端仪表盘） | Stats / Slots / Detail **按视图分层**，0.5~2s 轮询 | §2.1 四视图（概览/实时/流水/调优） |
| vLLM + Grafana（生产标准） | **折线趋势 + p50/p95 分位数**（不用均值）+ 按模型拆请求率 + KV 占用率 | §2.3 趋势图 + §2.4 分位数 |
| Langfuse / Arize Phoenix | 一次请求 = **trace 瀑布**（每步延迟/token/成败）+ 成功率 + 评分 | §2.6 因果提示 + P5（可选）瀑布 |
| opencode TUI | 消息按 part 渲染（正文/工具/思考分开）、彩色状态点、长内容折叠 | §2.7 状态语义规范 |

### 0.3 V2 现状盘点
- **已有（保留不动）**：✓/⚠️ 语义标记、GPU/tok/s 双时序图、推理槽行、专家分布、切换记录、工具调用流、活动流（跨前端）、证据/审计/任务计划、中英双语、2s 定时刷新、`/v1/observ/*` 全部数据端点。
- **缺口（V3 目标）**：① 文字墙无分层；② TTFT / KV 命中无趋势图（只有 tok/s 有）；③ 全是均值无分位数（均值被 30–172s 长尾拖爆，`TTFT_BREAKDOWN_REPORT` 已证明）；④ ⚠️ 只标"不正常"不解释原因、不给行动；⑤ 阈值散落硬编码在 `app.py` 三个函数里（曾致误报）。

### 0.4 V3 目标（一句话）
> **小白打开面板 10 秒读懂四件事：服务坏没坏（成功率）、这次慢不慢（首字延迟 + 原因）、谁在干活（专家分布）、系统在自动调优什么（governor 动作/告警）；任何 ⚠️ 都自带"为什么 + 怎么办"；调优变更可 A/B 对比、可查配置版本、可回滚。**

### 0.5 需求依据（"实时监控并调优"的项目原文与缺口证据）
用户需求来源（2026-08-05 02:25 复核，全部原文可查）：

- **`docs/Layer2_Implementation_Map.md` §5 Phase 3（持续调优闭环 = 方向 2）**："在面板做 **A/B 前 vs 后对比**（如关 thinking 的 ack 提升、换帽 KV 收益），体感差 → 定位哪层 → 改运行层配置 → 下一轮验证。**调优变更必须能记录配置版本并回滚**。" → **V3 原稿完全没覆盖此需求**。
- 同文档 §2 三平面边界：观测层"驱动 e2e 优化闭环：体感差 → 面板定位是哪层 → 改运行层配置"；观测层**只接收事件、落盘和展示**（改配置是运行层的事）→ V3 的"面板给建议不改配置"设计与此一致，但缺"配置版本记录"这一观测层该做的部分。
- **`docs/TRUTH.md` L93 + `docs/AUTOTUNE.md` L3**：保守档位机（governor）已实现并真机验证——tok/s 低→降 ctx；空答率高→实时关 thinking；显存>90%→KV 量化；换装超上限→`governor_alert`。这是"实时调优"的**已有引擎**，但：
  - **UI 路径下 governor=None（orchestrator L207 注释自述"the UI runs with no governor"）→ `observe()` 与 `swap_cap_exceeded()` 都不会执行，governor 事件（含 `governor_alert`）在 UI 场景根本不产生**。⚠️ 修正表述：`orchestrator.py` L243–247 的 `on_event("governor_alert")` 只在 governor 非 None（真机 tight 模式验证）路径下发出；`ui/app.py` `drain_events`（L512–543）无 governor 分支属于**防御性缺口**（将来启用 governor 时事件会被丢弃），但**不是当前"看不到调优"的原因**——当前原因就是 governor 没挂、且无任何 UI 告知"调优未启用"。
- **`docs/TRUTH.md` L74 + `screwshell/eval/`**：`bench/eval_e2e.py` 已可对答案质量/引用/RAG 做 **A/B 与回归裁决**（T3 度量闸），目前是离线 CLI，未进面板。

**结论：V3 原稿只做了"监控展示"（Layer2 Phase 1 的增强），缺 Layer2 Phase 3 的"调优"半边。本节以下新增 §2.8–§2.11、P4 阶段、验收与风险，全部为补齐此需求。**

---

## 1. 现状 → 目标对照（12 模块去向表）

| 现 UI 元素 | 现状位置（`screwshell/ui/app.py`） | V3 去向 |
|---|---|---|
| 调查中… / 第 i/n 步 | `_status_block`（orchestrator phase 事件） | 实时页顶部，保留 |
| 推理槽 slot（623/37248） | `_slots_line`（`/v1/observ/slots`） | 实时页，**兼作慢的因果证据**（§2.6） |
| 请求/成功率/首字延迟/切换/解码/KV/排队/专家分布 | `_fmt_metrics`（`/v1/observ/summary`） | 概览页 4 数字卡 + 专家分布行（§2.2） |
| 错误摘要 | `_fmt_metrics`（summary.errors） | 概览页错误行（仅显示，触发行动文案见 §2.5） |
| GPU 折线 / tok/s 折线 | `_gpu_df` / `_tps_df`（`gpu_history` + events） | 实时页，保留 |
| 切换记录 | `_fmt_lora`（recent events switched） | 流水页，保留 |
| 工具调用流（→tool_result / 调 read()） | `_fmt_tools` | 流水页，保留 |
| 活动流（[opencode]…⚠️会话过长） | `_fmt_observ`（events，>20000 警告） | 流水页，保留 |
| 证据 / 审计 / 任务计划 | `ctx.evidence` / `ctx.gate.audit` / plan 事件 | 流水页，保留 |
| —（新增） | — | 概览页 TTFT/KV **趋势折线**（§2.3）+ **分位数行**（§2.4）+ **⚠️ 行动文案**（§2.5） |
| —（新增，需求 P4） | governor 动作事件（`governor_alert` 已被 orchestrator 发出但 UI 丢弃；`set_ctx/set_thinking/set_kv_quant` 未发射） | 实时页 **自动调优（governor）视图**：当前档位/最近动作/告警（§2.8） |
| —（新增，需求 P4） | `eval/eval_e2e.py`（离线 CLI）+ observ 历史 | 调优页 **A/B 对比 + 配置版本**（§2.9） |

---

## 2. 设计

### 2.1 四视图（gr.Tabs，默认选中概览）
- **概览 Overview**：4 张数字卡（成功率、首字延迟、解码速度、KV 命中；每卡 = 数值 + ✓/⚠️ + 一行行动文案）+ 专家分布一行 + 全局(server)行 + 错误摘要 + 顶部健康总分（§2.10）。
- **实时 Live**：状态块（含推理槽行）+ GPU 折线 + tok/s 折线 + **TTFT 折线 + KV 命中折线**（§2.3）+ 自动调优（governor）卡（§2.8）。
- **流水 Stream**：切换记录 / 工具调用 / 活动流 / 证据卡片 / 审计 / 任务计划（V2 内容原样搬入）+ 入口/专家/成败筛选（§2.10）。
- **调优 Tuning**：A/B 对比（两窗口 TTFT/decode/KV/成功率并排 + 样本数 + 可设基线，§2.9）+ 配置版本（含生效方式标注 + 回滚命令，§2.9）。

### 2.2 数字卡口径（沿用 v16 阈值语义："越高越好只设下限"）
| 卡 | 读数 | 判断 | 行动文案（⚠️ 时） |
|---|---|---|---|
| 成功率 | ok_rate | <0.95 ⚠️ | "有 5%+ 请求失败，看概览页错误行定位是哪个专家" |
| 首字延迟 | avg_ttft_ms | ≥5000 ⚠️ | "慢的常见原因：资料太长 / 刚切过专家 / 在排队"（§2.6 自动补具体证据） |
| 解码速度 | avg_decode_tps | <20 ⚠️ | "生成变慢，常见原因：显存不足或正跑超长上下文" |
| KV 缓存命中 | kv_hit_rate | <0.8 ⚠️ | "缓存没续上，常见原因：频繁切专家 / 会话过长（建议开新会话）" |

### 2.3 趋势图补齐（TTFT、KV 命中）
- **纯 UI ring buffer**（仿 `_TPS_HIST`，maxlen=180，零后端）：从 `_poll_observ_once()` 已拉取的 recent events 里，每请求取 `ttft_ms` / `kv_hit_rate` 灌入 `_TTFT_HIST` / `_KV_HIST`。
- 两张 `gr.LinePlot`（x=时间 %H:%M:%S，高度 150），中文标题"首字延迟（ms）"、"KV 缓存命中率"。
- 后端 history 重建：优先复用 relay `gpu_history` 同款后端采样路径；**若 relay 无历史端点 → 静默空图，不得报错**（与 `_obs_offline` 同哲学）。

### 2.4 分位数 p50/p95（P3，替代/补充均值）
- **方案 A（推荐，零后端）**：UI 端从 recent events 计算 p50/p95（stdlib `statistics` 或手写 percentile，用 `max`/`sorted`），概览页显示"首字延迟 p50 1.7s · p95 88.8s"。
- **方案 B（需 store 小改）**：`store.summarize` 加 `p50_ttft_ms`/`p95_ttft_ms` 字段 + relay 只读透传 + UI 显示；**仅允许加聚合字段，绝不动 `_COLS`/INSERT/schema 迁移**。
- 验收尺子：与 `TTFT_BREAKDOWN_REPORT.md` 已知分布一致（中位 ~1.66s / p90 ~88.8s / max 172s）；样本数不足（events n 窗口短）时显示"样本不足"，不伪造（沿用 metrics.py 铁律"Never fabricate a measurement"）。

### 2.5 阈值集中配置（新文件 `screwshell/ui/thresholds.py`）
```python
OBS_THRESHOLDS = {
    "ttft_ms":  {"judge": lambda v: v < 5000,  "warn": "首字延迟偏慢", "action": "…"},
    "decode_tps": {"judge": lambda v: v >= 20, "warn": "生成偏慢",     "action": "…"},
    "kv_hit":   {"judge": lambda v: v >= 0.8,  "warn": "缓存续接不足", "action": "…"},
    "switch_ms": {"judge": lambda v: v < 1000, "warn": "切换耗时异常", "action": "…"},
    "prompt_tokens": {"warn_at": 20000, "warn": "会话过长", "action": "建议开新会话"},
}
```
- `app.py` 三个函数（`_fmt_metrics`/`_fmt_tps`/`_fmt_observ`）全部改读本模块，**删除硬编码阈值**。
- 语义规范（§2.7）：⚠️ 行必须带 `action` 文案；✓ 行保持简洁。
- ⚠️ 过渡关系（自审补）：`prompt_tokens: 20000` 是 **P0 现状快照**（集中化不改值）；P4 按 T17 升级为"接近 ctx 90%"（取 llama-server 实际 n_ctx），届时改 thresholds.py 一处即可。
- **i18n（自审补）**：所有新增文案（数字卡行动句、健康总分、governor 卡、调优页、A/B 纪律文案）必须进 `ui/app.py` 的 I18N 双语字典（L52–129）；缺失 key 时 fallback 中文并打日志，不允许 KeyError 崩 UI。

### 2.6 因果提示（慢 = 三连查，一行自动输出）
当首字延迟 ⚠️ 时，概览页自动追加一行，从**已有数据**取证据：
- 推理槽 `n_prompt_tokens` 大 → "资料过长（N token）→ 建议缩短提问范围或开新会话"；
- 近期切换记录密集（recent 内 switched ≥3）→ "刚频繁切换专家 → 缓存反复失效"；
- events 里 `prompt_tokens > 20000` → "会话过长 ⚠️"。
取命中的第一条（优先级 会话过长 > 资料过长 > 切换密集），输出"可能原因：…｜建议：…"。

### 2.7 状态语义规范（写进代码注释 + TRUTH）
- ⚠️ = "需关注"，**必须**附行动文案；✓ = "健康"，不附文案。
- 阈值语义统一"越高越好只设下限 / 越低越好只设上限"（v16 已立，V3 固化到 thresholds.py 集中声明）。
- 任何新指标进面板，必须同时进 thresholds.py（judge + action 成对），否则不允许渲染。

### 2.8 自动调优（governor）可视化 —— 需求核心，P4
- **governor 状态卡（实时页，结构参照 T13）**：摘要行（模式 roomy/tight/auto + 启用态，UI 场景未启用则显示"自动调优未启用"+ 说明）+ 最近动作列表（时间 + 动作 + 原因）+ 最近告警。
- **动作-指标叠加视图（参照 T11）**：在 tok/s / VRAM 折线上叠加 governor 动作标记（降档/关 thinking/KV 量化/告警），用户一眼看到"哪一刻自动系统做了什么、指标如何响应"。**实现方式（自审修正）**：现有 `gr.LinePlot`（pandas df）不支持线上叠加标记 → 用 `gr.Plot` + plotly scatter（plotly 是 gradio 的传递依赖，仍零新依赖，P4 开工前先本地验证 import 可用）；若 plotly 不可用 → 退化为"折线图 + 下方并列一条动作事件时间轴"（纯 LinePlot 分格），不阻塞交付。只读渲染 events，零后端。
- **稳定性行（参照 T12）**：近 30 分钟是否反复升降档（升了又降 = 不稳定），是则提示"调优参数可能过激"。
- **事件补齐（最小改动，D1 已拍板 = 加，2026-08-05）**：
  1. `ui/app.py` `drain_events` 补 `governor_alert`（+`governor_action`）分支——**防御性正确**（UI 路径 governor=None 时事件不产生，补了也不可见；但它保证将来任一入口启用 governor 后事件不丢）；
  2. `orchestrator.py` 在 `observe()` 返回非空 action 时 `on_event("governor_action", {kind, reason})` —— **本任务书唯一允许触碰 orchestrator 的一处：只加发射、不改任何行为**（`set_ctx/set_thinking/set_kv_quant` 的*执行*逻辑零改动）。✅ 用户已批准（D1=A），无降级分支。
- **⚠️ UI 场景 governor 未启用 = 既定决策（D2=A，2026-08-05）**：见 §0.5 修正——UI 路径 governor 未挂，**P4 的可见主交付是"未启用明示 + 未启用时引导"**，动作透明化是"启用后"的能力；**不在本任务书范围**：UI 路径启用 governor（行为变更：自动降 ctx/关 thinking）需单独立计划并重跑真机 A/B 验收。

### 2.9 调优闭环：A/B 对比 + 配置版本（需求原文 Phase 3，P4）
- **A/B 对比视图（调优页，结构参照 T18/T19）**：选定"改动前窗口 vs 改动后窗口"（如关 thinking 前后、换帽前后、加 `--flash-attn` 前后），面板并排展示 TTFT / decode / KV 命中 / 成功率 / 首 token 分布（p50/p95）差异；任一窗口可"设为基线"（T19）。数据源 = observ DB 既有 `request_events`（ttft_ms/decode_tps/kv_hit_rate/ok），**零新埋点**；窗口划分 = 用户选时间范围或打标记（run_id 前后）。
- **实验纪律（遵循 T1–T6，面板强约束）**：① 单变量——一次对比只改一个配置，版本号里注明"改了什么"（T1）；② 会话粘性——同一 run_id 不跨变体（T2）；③ 单主指标 + 护栏——面板上只标 1 个主指标判胜负，TTFT/成功率/KV 是护栏（T3）；④ 样本量——显示两窗口样本数，样本不足显示"样本不足，暂不判胜负"（T4）；⑤ 回滚优先——对比页顶部常驻"回滚到版本 N"命令入口（T5/T6 的护栏阈值展示为建议，人确认后执行）。
- **配置版本记录（观测层只读职责；写入方 = D3 已定：`/props` 轮询快照，2026-08-05）**：观测层按固定间隔（如每 60s 或检测到 llama-server 重启时）从 `/props` + 进程启动参数采集配置快照，生成版本号 + 时间 + **生效方式标注（热更新 / 需重启，T9）**；面板可查历史、可对比两版本 diff。**零存储零迁移**（快照存内存 ring / 复用 events 流），不碰 observ 库 schema。运行层变更点写入（更精确的历史）留作后续需要时再升级——升级需走独立小计划（带迁移）。**回滚 = 给出"回滚到版本 N 的配置命令"，由人/运行层执行**（T10：Azure 自主调优的"推荐即复制脚本"是业界标准交互；遵守三平面边界，观测层不改运行层配置）。
- 边界：A/B 与版本记录**全部只读 observ/配置史**；不引入 eval_e2e 联动（T7 判例库留给 P5）。

### 2.10 UX 增强（小白 10 秒原则的补充）
- **健康总分（概览页顶部，两级制 T15）**：成功率 + 首字延迟 + KV 命中三态合成一个"正常/需关注（黄）/异常（红）"大状态（业界 dashboard 惯例），一眼给结论；黄红两级各配一行"看哪个卡"。
- **趋势异常提示**：不只看当前值——近 10 分钟 TTFT 持续上升（斜率>阈值）时概览卡附"⚠️ 延迟在上升"；token 用量 vs 基线比 >1.3 提示"输入在膨胀"（T16 算法模板；数据源 = P2 的 `_TTFT_HIST` ring buffer，纯 UI 计算）。
- **会话过长语义化（T17）**：⚠️会话过长从硬编码 20000 升级为"prompt 接近 ctx 90%"（取 llama-server 实际 n_ctx，超 90% 告警），与 governor 的 ctx 档位联动；文案改为"接近上下文上限，建议开新会话"。
- **流水页筛选**：活动流/工具流按入口（opencode/UI/pi）、专家、成败过滤（Gradio Dropdown 或 CheckboxGroup）。
- **颜色 + 符号双通道**：⚠️ 行同时着色（黄=需关注/红=异常），色盲友好；✓ 用绿。仅在 Markdown 里包 HTML span 着色，**不引入任何新依赖**。
- **每视图空态**：无数据时显示"暂无数据（原因：…）"而非空白；P2 趋势图无历史时静默空图（已有约定）。

### 2.11 联网补充调研（2026-08-05 二轮，P4/UX 的设计依据）
按"调优闭环 / 自动调优透明化 / 实验对比"三主题检索，可抄模式如下（编号供施工引用）：

**调优闭环（A/B + 配置版本）**
- **T1 单变量原则**：一次只改一个配置（prompt 版本与模型版本分开版本化）；A/B 只改一个变量，否则无法归因、回滚困难（aissn.com 灰度模板）。
- **T2 会话粘性（sticky）**：同一会话命中一个变体后不得中途翻转（翻转 = 无意义数据）。对应实现：按 run_id/会话哈希分桶，P4 的窗口划分沿用此原则（dev.to playbook）。
- **T3 单主指标 + 护栏指标**：只设 1 个主指标判胜负（alpha 0.05）；latency/cost/拒绝率是护栏——只能否决加冕、不能创建胜利；预注册阈值，禁止"看结果挑指标"（dev.to：5 个主指标 ≈ 23% 假阳性）。
- **T4 样本量纪律**：n_per_arm = 16σ²/MDE²（α=0.05, power=0.80）；LLM 输出高方差，所需样本远大于常规转化测试；"跑一周"不是计划。→ P4 面板必须显示样本数 + "样本不足不判胜负"（延续 metrics.py 不伪造铁律）。
- **T5 回滚路径 > 发布路径**：优化回滚能力（配置 flag flip 即回滚）；canary 每步小爆炸半径。配置版本记录的目标就是"一次切换可回滚"（dev.to；letsbuildsolutions 部署模式风险表）。
- **T6 护栏自动回滚**：p99 延迟 +40% / 拒绝率 +5pp / 成本超预算 → 自动切回稳定版（dev.to）；CSDN 案例：连续 5 个 Bad Case 自动回滚。→ P4 面板给出"回滚触发条件建议"（不自动执行，人确认）。
- **T7 判例库（golden dataset）**：把线上典型问题沉淀为可回放样本集（真实输入 + 期望/不合格样例 + 风险标签），每次调优先跑判例库防回归（aissn；Langfuse golden dataset：同 dataset 版本 + 同 evaluator → 读 deltas）。→ 对应 `bench/eval_e2e.py` 的既有能力，P5 接入。
- **T8 影子评测优先**：新配置先 shadow（复制流量、不影响用户）再灰度（letsbuildsolutions 模式表：shadow 永远先跑、成本最低）。
- **T9 热更新 vs 重启分级**：配置变更先尝试动态更新、不行才重启（停机降 30–98%，阿里云 Flink Autopilot）。→ 配置版本记录必须标注每项参数"生效方式：热更新（如 LoRA toggle / thinking）/ 需重启（如 --flash-attn / --cache-type / ctx）"。
- **T10 推荐即命令**：Azure PostgreSQL Autonomous tuning = 系统给推荐卡片 + 用户**复制 SQL 脚本**应用，系统不自动执行。→ 证实 §2.9"回滚 = 展示命令、人执行"是业界标准交互，非权宜。

**自动调优透明化（governor 视图）**
- **T11 期望带 + 实际线 + 修正线三线图**（Pcnautic Autopilot Tuning）：橙色期望区间 / 红色实际值 / 蓝色修正动作量叠加——用户一眼看到"自动系统在干什么、纠偏多少"。→ governor 视图 = 指标实际曲线 + 修正动作事件叠加。
- **T12 稳定性指示**（Pcnautic）：不稳定标志 true/false、上升时间、超调、稳定时间、稳态误差。→ governor 卡加"稳定性"行：最近是否反复升降档（如 30 分钟内降档又回升 = 不稳定）。
- **T13 摘要卡 + 覆盖度 + 最近动作 + 最近问题**（Xapix Autopilot Dashboard）：自动系统面板的标准结构。→ governor 卡 = 摘要（模式/启用态）+ 最近动作列表 + 最近告警。
- **T14 收敛产出可复用计划**（Flink Autopilot）：自动调优收敛后输出可保存复用的"资源计划"。→ 调优页支持把一轮 A/B 结论存为"配置建议卡"。

**监控 / UX**
- **T15 两级告警**：warning + alert 双阈值、无数据处理、5/15 分钟聚合窗口（Langfuse Monitors；LangSmith Alerts 同）。→ 健康总分用 黄=需关注 / 红=异常 两级（升级 §2.10 颜色双通道）。
- **T16 token 基线比**：每 15 分钟比较 avg token/请求 vs 基线，>1.3 warning / >2.0 critical（letsbuildsolutions）。→ §2.10"趋势异常提示"的具体算法模板。
- **T17 context 90% 告警**：prompt token 接近 context window 的 90% 时告警（letsbuildsolutions，"context length creep"）。→ ⚠️会话过长从硬编码 20000 升级为"接近 90% ctx"（与 governor 的 ctx 档位联动），语义化。
- **T18 对比视图三层**（Langfuse Compare）：聚合图表（质量动了没、代价多大）+ 逐项对比表（哪条变差了）+ 回归工作清单（筛 correctness 下降 / 成本升 >10% 的项）。→ P4 A/B 视图结构照此：聚合指标并排 + 逐请求对比 + 可筛选清单。
- **T19 baseline 机制**（Langfuse）：指定某 run 为 baseline，其余 run 与之对比；对比结果可标注/评论。→ P4 支持"设为基线"。
- **T20 失败聚类**（LangSmith Engine：把生产失败聚成 issues）→ 仅 P5 可选。

---

## 3. 边界（铁律，违反即退回）

- **可动**：`screwshell/ui/app.py`（主战场）、新增 `screwshell/ui/thresholds.py`、P3 方案 B 时 `screwshell/observ/store.py`（只加聚合字段 + 测试）、**P4 唯一例外（✅ D1 已批准）**：`orchestrator.py` 加一行 `on_event("governor_action", ...)`（纯观测发射，零行为变化）。
- **仍不动**：`orchestrator.py`（除上述一行）、`inference_coordinator.py`、`mol_engine*`、`router.py`、`gateway/relay.py` 行为（如需 events n 加大，只允许加**只读参数** n，默认值不变）、`RequestEvent` 字段语义、部署脚本、llama-server 参数（P1 施工中，本计划不叠加）。
- **零新依赖**（pandas/gradio 已有；分位数用 stdlib）。
- **数据源只用现成端点**：`/v1/observ/summary`、`/v1/observ/events`、`/v1/observ/slots`、`/v1/observ/gpu_history`；P4 配置版本降级采集再加只读 `/props`（llama-server 原生）。不得为 UI 新增埋点。
- UI 纯展示改造 → **部署 = scp `ui/app.py`（+ `thresholds.py`）后重启 UI 进程**；OBSERV_DIR 无 schema 变更，`requests.db` 无需迁移——**唯一例外（自审修正）**：P4 配置史表若采纳"运行层写入"方案，需在 observ 库**新增一张表（带 schema 迁移，遵守 P0.5 教训）**，只读展示；不采纳则 P4 用 `/props` 轮询快照（零存储），二者选一在 §8 决策。P4 不涉及、不改 `request_events` 既有表。

---

## 4. 分阶段与验收（每阶段一 commit，验收全过后进下一阶段）

### P0 阈值集中化 + 语义修正（纯重构，行为不变）
- 建 `ui/thresholds.py`；`_fmt_metrics`/`_fmt_tps`/`_fmt_observ` 改读集中阈值；⚠️ 文案补行动句。
- 验收：与 v16 行为完全一致（`tps ≥ 20`、`kv ≥ 0.8` 等）；新增 `tests/test_thresholds.py`（≥5 例：judge 边界、action 存在性、prompt 20000 警告）；`pytest tests/` 全绿。

### P1 四视图布局（gr.Tabs）
- 概览/实时/流水/调优四个 Tab；V2 全部组件按 §1 归位；默认 Tab=概览；2s 定时刷新与中英双语不受影响。
- ⚠️ **四处输出元组必须同步改（自审补）**：`dashboard_values()` 的 10 元组返回序、`respond()` 生成器的 `yield`、`auto_refresh()` 的返回值、`apply_lang()` 的 `gr.update` 列表——任何一处不同步都会错位渲染。建议把"组件 id 顺序"抽成常量表，四处共用。
- 验收：三 Tab 均渲染且定时刷新正常；`apply_lang`/`auto_refresh`/`respond` 输出元组与 Tab 组件一一对应（用组件 id 断言）；新增文案中英双语齐全（i18n 全 key 单测）。

### P2 趋势图补齐（TTFT、KV 命中）
- `_TTFT_HIST`/`_KV_HIST` ring buffer + 两张 LinePlot 进实时页；后端 history 重建优先、无则静默。
- 验收：连续对话后两图有数据点；UI 重启后能尽力从 relay 重建（无则空图不报错）；`pytest` 全绿。

### P3 分位数 + 因果提示
- 概览页分位数行（方案 A 优先，样本不足显示"样本不足"）；§2.6 因果提示接入首字延迟卡；健康总分（§2.10）上线。
- 验收：⚠️ 首字延迟必有"可能原因｜建议"行；分位数量级与 TTFT_BREAKDOWN_REPORT 一致；若走方案 B：`store.summarize` 新字段 + `test_summarize_percentile` 单测。

### P4 自动调优可视化 + 调优闭环（需求核心，Layer2 Phase 3）
- §2.8：`drain_events` 补 governor 事件分支（防御性）；orchestrator 一行 `governor_action` 发射（✅ D1 已批准）；实时页 governor 状态卡（模式/最近动作/告警；未启用时明示 + 引导）。
- §2.9：调优页 A/B 对比视图（observ 历史 + run_id/时间窗口划分）+ 配置版本记录（写入方见 §2.9/§8 决策）。
- §2.10：趋势异常提示、流水筛选、颜色双通道。
- **验收分级（自审补，本机无真实 observ 数据）**：① pytest 层 = 纯函数单测（窗口切分/样本数/percentile/配置快照序列化）；② 本机层 = 用 fixture 造 events/配置 JSON 喂 UI 格式化函数，断言 A/B 并排输出与 governor 卡渲染文本；③ 真机层 = 部署后用真实 `requests.db` 跑一次 10 秒检查。三层全部通过才关 P4。
- 验收：governor 事件分支有测试钉（mock 事件进 `drain_events`）；A/B 视图能用同一专家两窗口数据画出对比（fixture）；配置版本可查可导出回滚命令；**UI 场景 governor 未启用时面板明示，不假装在调优**（诚实铁律）。

### P5（可选，增强，本计划不含死线）
- Langfuse 式单次调查 trace 瀑布（plan→step→tool→final 链路，数据源 = observ events 的 tool_calls + 阶段事件）；**判例库（T7）**：把典型问题样本沉淀为可回放集，接 `bench/eval_e2e.py` 每次调优前回归；失败聚类（T20，LangSmith 式 issues）；**调用预算制**（Layer2 §4 愿景：按 session 限 token——面板展示"本会话 token 用量 vs 预算"，数据源 RunMetrics 已累加）+ **thinking 用量**（每请求 thinking 开关/预算消耗，RequestEvent 已有 thinking 字段）。**仅当 P0–P4 全绿且用户确认后再开工**，需单独小计划。

---

## 5. 三道闸与文档

- ① `pytest tests/` 全绿（重定向到文件跑，禁管道——见 MEMORY.md 铁律）；预计 257 + 新增 ≥8 → 若新增测试，**同步 bump `scripts/verify_bugfixes.py` §8 阈值（≥200→新高）+ TRUTH.md §3 基线**。
- **测试矩阵（自审补，新增文件与归属阶段）**：
  | 文件 | 阶段 | 覆盖 |
  |---|---|---|
  | `tests/test_thresholds.py` | P0 | judge 边界、action 存在性、i18n key 齐全、prompt 20000 快照 |
  | `tests/test_ui_layout.py` | P1 | 组件 id 顺序常量表与四处元组一致（纯函数层） |
  | `tests/test_percentile.py` | P3 | percentile 正确性、样本不足分支（方案 B 再加 store 字段测试） |
  | `tests/test_gov_events.py` | P4 | `drain_events` governor 分支、orchestrator emit（mock observe→action） |
  | `tests/test_ab_windows.py` | P4 | 窗口切分/run_id 粘性/样本数/护栏阈值纯函数 |
  | `tests/test_config_snapshot.py` | P4 | 配置快照序列化 + 生效方式标注（若走存储方案：迁移测试） |
- ② `scripts/verify_bugfixes.py` EXIT=0（§8 断言 passed≥阈值）。
- ③ `git fsck --full` 无 missing/broken。
- TRUTH.md §8.3 追加 **v17** 行：V3 阶段 0–4 落地（P5 可选不含）+ 阈值集中化 + 分位数口径 + governor 事件接通 + A/B/配置版本 + 部署机旧阈值文案核对结论 + **决策记录：D1 加 / D2 不启用（UI 明示）/ D3 /props 轮询快照 / D4 A/B 主指标=TTFT（2026-08-05 02:39 拍板）**。
- 提交策略：P0→P5 每阶段一个 commit；**全部验收后一次 push**（沿用 gh_helper 凭据绕过法，见 MEMORY.md「git push 凭据坑」；推送后删临时 helper，API 核对 `origin/main == HEAD`）。

---

## 6. 验收清单（用户 10 秒检查，交工时逐条打勾）

- [ ] 打开 7860：右侧四个页签（概览/实时/流水/调优），默认概览
- [ ] 概览 4 张数字卡一眼读懂；「25.9 tok/s」显示 ✓（不再误报）
- [ ] 任何 ⚠️ 下方有一行「可能原因 + 建议」
- [ ] 实时页 TTFT、KV 命中折线随对话增长
- [ ] 实时页有「自动调优」卡：governor 动作/告警可见，动作标记叠加在指标折线上；**UI 场景未启用时明示"未启用"**
- [ ] 调优页 A/B 对比（两窗口 TTFT/decode/KV/成功率并排 + 样本数 + 可设基线）+ 配置版本（含生效方式标注）可查、可导出回滚命令
- [ ] A/B 视图遵循实验纪律：单主指标、样本不足显示"暂不判胜负"、护栏阈值只作建议
- [ ] 概览页健康总分一眼给出 正常/需关注/异常（黄红两级）
- [ ] 流水页切换/工具/活动流/证据/审计/计划齐全，且可按入口/专家/成败筛选
- [ ] ⚠️/✓ 有颜色+符号双通道（色盲友好）
- [ ] 所有新增文案中英双语一致（i18n 无缺失 key）
- [ ] 中英双语切换正常；2s 定时刷新正常；无任何新依赖

## 7. 风险

- **events 窗口短**：relay `/v1/observ/events?n=20` 样本不足 → p50/p95 与趋势图失真 → P3 前置：relay 允许 `n` 调大（只读参数，默认 20 不变，需 1 个测试）。
- **Gradio Tab + 多图排版**：真机 7860 窄屏可能破版 → P1 先本地原型确认再部署。
- **P3 方案 B 边界漂移**：store 只加聚合字段，若发现需要改 `_COLS`/迁移 → **立即停止，回报用户**（与 P0.5 同一教训：schema 演进必须带迁移，见 2026-08-05 日志）。
- **部署机旧代码**：若真机 UI 仍显示「正常 15–25」文案，说明实例跑的是 e7aad4e 之前版本 → P0 完成后再 scp 同步，避免叠加混淆。
- **P4 决策已全部拍板（✅ 2026-08-05 02:39，§8）**：D1 加 / D2 不启用 / D3 /props 轮询 / D4 TTFT——施工无需再等决策；§2.8/§2.9/§3 已按拍板结果定案。
- **plotly 依赖（自审补）**：动作叠加视图依赖 `gr.Plot`+plotly（gradio 传递依赖）；P4 开工前先本地 `import plotly` 验证，不可用则退化上下排布（§2.8 已写死退路）。
- **本机无真实观测数据（自审补）**：P4 的 A/B 视图、governor 卡在本机验收依赖 fixture 造数（§4 验收分级），真实数据验证只能真机做——验收清单上"真机层"不可跳过。
- **A/B 对比的因果性**：窗口对比 ≠ 受控实验（混杂因素：任务难度/上下文长度差异）。面板只展示"前后差异"，结论措辞必须写"差异（含混杂因素）"而非"因果证明"——沿用 TTFT_BREAKDOWN_REPORT 的诚实铁律；样本量纪律（T4）不足时明确"暂不判胜负"。
- **二轮调研引入的复杂度**：T9 生效方式标注需要配置史记录"热更新/重启"分类；若走运行层写入方案 → observ 库新增配置史表（带迁移，遵守 schema 演进教训）；T17 需要 llama-server 实际 n_ctx（`/props` 已有），无则回退硬编码 20000。

---

## 8. 决策点汇总（✅ 2026-08-05 02:39 用户已全部拍板，P4 施工无需再等决策）

| # | 决策 | 选项 | 拍板结果（02:39） |
|---|---|---|---|
| D1 | orchestrator 加一行 `governor_action` 事件发射 | A. 加（纯观测，零行为变化） / B. 不加（P4 只展示 `governor_alert`） | ✅ **A · 加**（§2.8/§3 的降级分支作废） |
| D2 | UI 场景是否启用 governor 自动调优 | A. 不启用（仅明示"未启用"） / B. 启用（行为变更，单独立计划） | ✅ **A · 不启用**（P4 主交付 = 未启用明示 + 引导；启用另立计划） |
| D3 | 配置史写入方 | A. 运行层变更点写入（observ 库新表带迁移） / B. `/props` 轮询快照（零存储零迁移） | ✅ **B · /props 轮询快照**（§2.9 写入方定案；运行层写入留作需要精确历史时再升级） |
| D4 | A/B 主指标 | 从 TTFT / 成功率 / KV 命中 / 首 token 分布中选 1 个（T3 纪律） | ✅ **TTFT**（当前唯一真实痛点，TTFT_BREAKDOWN_REPORT 佐证） |
