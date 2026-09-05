# HANDOFF: 观测维度自选切片器（Dimension Slicer）设计

> 交接文档 · 目标 agent：**UI / 观测台前端 + 数据分析 agent**
> 交接人：主 agent · 日期：2026-08-05
> 状态：设计任务（尚未实现）· 优先级：P2 增强（非 bug 修复）
> 相关 commit：`c69c015`（#1/#3/#4 修复）、`e49fda9`（revert datetime）、`b9c9993`（GPU 单 y）

---

## 0. TL;DR（给接手的 agent）

当前调优页签的 A/B 对比**只支持 3 种硬编码的窗口切分方式**（`half` / `run` / `minutes`），且切分维度写死在 `split_ab_windows` 里。需求是：**让观测维度可自选**——不限于"按时间/按 run_id"，而是能按任意可用的事件字段（对话 run_id / 单次调用 request_id / 操作会话 operational_session_id / 入口 entry / 专家 adapter / 时间 / 成败 ok 等）做通用切片，并让**其他页签（概览/实时/流水）的观测也复用同一套维度切片逻辑**。

本文档给出：现状、数据 schema、设计目标、候选方案、边界与验收建议。接手 agent 需据此产出**决策完整的设计方案**（含是否推进/回退的权衡），不要直接改代码。

---

## 1. 现状（代码事实，已核对）

### 1.1 A/B 切分：`screwshell/ui/analysis.py` `split_ab_windows()`

```python
def split_ab_windows(events, mode="half", window_min=10.0) -> (list_a, list_b):
    # mode 三选一：
    #   "half"    → 按 ts 排序，前一半 A / 后一半 B
    #   "run"     → 按 run_id 最后一次变化为界切分
    #   "minutes" → A=[now-2w, now-w), B=[now-w, now)
```
- 纯函数，已单元测试，无 i18n、无全局状态。
- 调用点：`app.py` 内 `run_ab()`（点击"运行对比"）和 `set_baseline()`（点击"将 A 设为基线"）。

### 1.2 UI 接线：`screwshell/ui/app.py` 调优页签（~L1324-1341）

```python
with gr.Tab(T("zh", "tab_tuning")):
    ab_mode = gr.Dropdown(
        choices=[("按时间对半分","half"), ("按 run_id 变化为界","run"),
                 ("按分钟窗口","minutes")],
        value="half", ...)
    ab_win = gr.Number(value=10, ...)
    ab_run_btn = gr.Button("运行对比")
    ab_base_btn = gr.Button("将 A 设为基线")
    ab_compare_md = gr.Markdown(...)
```
- `run_ab(mode, window_min)` → `split_ab_windows(recent, mode=mode)` → `compare_windows(a,b)` → `fmt_ab_compare(...)`。
- 维度选择**只有这一个下拉，硬编码 3 个选项**。

### 1.3 流水页签已有"入口/专家/成败"3 维筛选（可作参考/可复用模式）

`app.py` `_STREAM_FILTER` + `_stream_match(e)`：
```python
f["entry"]   # "all" / "opencode" / "ui"（注意：这里把 "api" 归并到 "ui"）
f["expert"]  # "all" / 具体 adapter 名
f["ok"]      # "all" / "ok" / "fail"
```
- 这套已经证明**维度筛选在事件流上是可行的**，且 UI 已做。可参考它的下拉→过滤→渲染模式。

### 1.4 事件 schema（relay `/v1/observ/events` 返回，`RequestEvent`）

每次请求落一条事件，字段（已实测实例返回，2026-08-05）：
```
adapter            # 命中的 LoRA 专家名，如 "btl3" / "cybersec" / "rag_n7" / "基础"
benchmark          # bool，是否压测流量（会话健康判定会排除它）
boundary_reason    # 会话边界原因（"no_reusable_prefix"/"explicit_reset"/"model_reload"/"first"/""）
cache_signal_valid # bool
cached_tokens      # int
completion_tokens  # int
decode_ms          # float
decode_tps         # float（解码速度）
entry              # 入口："ui" / "opencode"（或旧 "api"）
error              # 错误信息 or None
kv_hit_rate        # float 0~1（KV 命中率）
model              # str
ok                 # bool（本次请求是否成功）
operational_session_id  # 操作会话 id（"cache-reuse segment"，跨多个 run 共享）
prefill_ms         # float
prompt_tokens      # int
queue_wait_ms      # float
request_id         # 单次调用 id
route              # 路由（可能 null）
run_id             # 浏览器/UI 身份（对话级）
status_code        # int
stream             # bool
switch_ms          # float or None（专家切换耗时）
switched           # bool
thinking           # bool
thinking_ms        # float or None
tool_calls         # list
ts                 # float（unix 时间戳）
ttft_ms            # float（首字延迟）
user_msg           # str
```

**可作为"切片维度"的候选字段**（按用户需求"对话/调用/时间 + 自选"）：
| 维度 | 字段 | 粒度 | 说明 |
|---|---|---|---|
| 对话（run） | `run_id` | 粗 | 浏览器/UI 一次会话 |
| 操作会话 | `operational_session_id` | 中 | 共享 warm KV 前缀的一段 |
| 单次调用 | `request_id` | 细 | 单次 chat/completion |
| 入口 | `entry` | 分类 | ui / opencode |
| 专家 | `adapter` | 分类 | 命中的 LoRA 专家 |
| 成败 | `ok` | 分类 | 成功/失败 |
| 时间 | `ts` | 连续 | 时间窗口 |
| 流式/非流式 | `stream` | 分类 | bool |
| 路由 | `route` | 分类 | 可能 null |
| 是否切换专家 | `switched` | 分类 | bool |

---

## 2. 需求（用户原始反馈，原话要点）

> 调优页签，第一个窗口切分方式有 3 个选项，我认为**其他页签的观测维度也应该能拆分成 对话/调用/时间 维度**，而且**应该能自选维度，而不是已 xx 为界**。

拆解为：
1. **切分维度可自选**：不止"按时间/按 run_id"，要能选任意可用字段（如按专家、按入口、按成败）。
2. **维度分层**：至少 对话（run）→ 调用（request）→ 时间（ts）三类粒度。
3. **全站复用**：其他页签（概览/实时/流水）的观测也能用同一套维度切片，而不是只有调优页签 A/B 用。

---

## 3. 设计目标（GOALS）

- **G1 通用维度描述**：定义一种"切片器"抽象，能按任意事件字段分组/切分事件，不写死字段名。
- **G2 粒度分层**：至少支持 对话(run_id) / 操作会话 / 单次调用(request_id) / 时间(ts)，且能自选。
- **G3 全站一致**：概览、实时、流水、调优 四个页签共用同一套切片机制（单一实现，防 drift）。
- **G4 保持"诚实输出"铁律**：样本不足不出结论；差异标注"含混杂因素非因果证明"；不造假数据。
- **G5 向后兼容**：现有 `split_ab_windows(half/run/minutes)` 的调用和测试不破坏，或平滑迁移。
- **G6 可测试**：纯函数（gradio-free）进 `analysis.py`，补单元测试。

---

## 4. 候选方案

### 方案 A：通用分组切片器（推荐，最小侵入）

把 `split_ab_windows` 泛化为"先按维度分组，再在组内切 AB"：
- 新增纯函数 `slice_events(events, dimension, ...)` 返回 `{group_key: [events]}`。
- `dimension` 取值：`"run"`(run_id) / `"session"`(operational_session_id) / `"request"`(request_id) / `"entry"` / `"adapter"` / `"ok"` / `"time"` / `"stream"` / `"switched"`。
- A/B 对比 = 在"当前选中的维度"下，把 `slice_events` 结果按时间序分成前/后两窗口，再 `compare_windows`。
- **优势**：改动集中、纯函数、可测、向后兼容（保留 `mode="half"` 作为默认时间切分）。
- **注意**：分组后每组的样本量会变小，需强化 `sample_count_ok` 的低样本纪律提示。

### 方案 B：多维度透视（Pivot Table，更重）

把事件流变成一个可按任意 2-3 维透视的表格（类 SQL group by），A/B 只是其中一种聚合视角。
- **优势**：表达力最强，能看"每个专家 × 每个入口"的组合指标。
- **劣势**：UI 复杂度大增（多选维度、行列选择器）、实现量大、与现有单一对比展示冲突、易过度设计。**不建议一期做**。

### 方案 C：复用流水页签的 `_STREAM_FILTER` 模式扩展

把流水页签现有的 entry/expert/ok 筛选抽成通用 `DimensionFilter`，供所有页签用；A/B 的切分维度也用同一套枚举。
- **优势**：全站一致性最彻底（G3 最强）。
- **劣势**：`_STREAM_FILTER` 目前是过滤（布尔保留/丢弃），不是分组/切分；A/B 要的是"切成两半对比"，语义不同，需新抽象，不能直接复用。

### 推荐
**方案 A 为主，吸收方案 C 的维度枚举一致性**：先定义统一的 `DIMENSIONS` 枚举（供所有页签下拉共用），再实现 `slice_events()` 分组器，A/B 基于它切窗。二期如需透视再上方案 B。

---

## 5. 具体改动建议（供设计 agent 细化，勿直接执行）

### 5.1 新增 `DIMENSIONS` 常量（`analysis.py` 或新模块）
```python
# 统一维度枚举，供所有页签下拉共用
DIMENSIONS = {
    "time":     {"label_i18n": "ab_dim_time",     "field": "ts",        "kind": "continuous"},
    "run":      {"label_i18n": "ab_dim_run",      "field": "run_id",    "kind": "categorical"},
    "session":  {"label_i18n": "ab_dim_session",  "field": "operational_session_id", "kind": "categorical"},
    "request":  {"label_i18n": "ab_dim_request",  "field": "request_id", "kind": "categorical"},
    "entry":    {"label_i18n": "ab_dim_entry",    "field": "entry",     "kind": "categorical"},
    "adapter":  {"label_i18n": "ab_dim_adapter",  "field": "adapter",   "kind": "categorical"},
    "ok":       {"label_i18n": "ab_dim_ok",       "field": "ok",        "kind": "categorical"},
    "stream":   {"label_i18n": "ab_dim_stream",   "field": "stream",    "kind": "categorical"},
    "switched": {"label_i18n": "ab_dim_switched", "field": "switched",  "kind": "categorical"},
}
```

### 5.2 新增 `slice_events(events, dimension, ...)`（纯函数）
- `dimension == "time"`：保留现有 `minutes`/`half` 的时间窗口逻辑。
- 其它 categorical 维度：按 `field` 的值分组返回 `{key: [events]}`；`None`/空值归到 `"unknown"` 组。
- **纪律**：分组后每组样本数 < 阈值时不单独下结论（复用/强化 `sample_count_ok`）。

### 5.3 A/B 改造
- 保留 `split_ab_windows` 的 `half/run/minutes`（或把 `run` 重映射为 `slice_events(dimension="run")` 后取时间前/后）。
- `run_ab` 的入参从 `mode` 扩展为 `(dimension, ...)`；下拉改为从 `DIMENSIONS` 生成选项。
- 展示 `fmt_ab_compare` 需说明"按 X 维度切分"。

### 5.4 全站复用
- 概览/实时页签的指标卡、分位数、趋势，可加"按维度"下拉，聚合逻辑复用 `slice_events`。
- 流水页签的 `_STREAM_FILTER` 维度枚举改为引用 `DIMENSIONS`，保持一致。

---

## 6. 边界与风险（设计时必须权衡）

- **样本稀释**：维度切分越细，每组样本越少，越容易触发"样本不足"。需清晰的低样本 UI 提示。
- **`entry` 归一化**：现 `_STREAM_FILTER` 把 `"api"` 归并到 `"ui"`（`app.py:876`），`slice_events` 需决定是否同样归一化，保持口径一致。
- **连续 vs 分类维度**：`time` 是连续（要分桶/窗口），其它是分类（直接分组）。处理逻辑不同，`DIMENSIONS` 里的 `kind` 字段是设计要点。
- **`None`/空值**：`route`、`adapter`（基础专家时可能 None）、`thinking_ms` 等有空值，分组要定义 `"unknown"` 桶，不能丢数据。
- **向后兼容**：现有测试 `tests/test_*.py` 依赖 `split_ab_windows(half/run/minutes)` 签名，改造时保留或平滑迁移 + 更新测试。
- **不要过度设计**：方案 B 透视表是一期边界之外的，接手 agent 应明确一期只做"单维度分组 + A/B 切窗 + 全站复用维度枚举"，避免 scope 膨胀。

---

## 7. 交付物要求（接手 agent 输出）

1. **决策完整的设计方案**：明确选方案 A（或给出推翻它的论证），给出 `DIMENSIONS`、`slice_events` 的签名与行为、A/B 改造、全站复用的具体改动点。
2. **补齐 i18n**：新增 `ab_dim_*` 等文案（zh + en）。
3. **测试计划**：为 `slice_events` 各维度 + 边界（空值/样本不足/`entry` 归一化）补纯函数单测。
4. **不直接改生产代码**：先出方案，等确认后再实现（本任务当前是设计交接，不是实现令）。
5. 方案产出后，更新 `docs/TRUTH.md`（如涉及架构/能力描述）与 `docs/SPEC.md`（交付物需反向同步）。

---

## 8. 关键文件索引（接手 agent 必读）

- `screwshell/ui/analysis.py` — `split_ab_windows` / `compare_windows` / `sample_count_ok`（A/B 核心）
- `screwshell/ui/app.py` — 调优页签接线（L1324-1341）、`run_ab`/`set_baseline`（L1162-1177）、流水页签 `_STREAM_FILTER`/`_stream_match`（L873-887）、`dashboard_values`/`DASH_NAMES`（L1041-1093）
- `screwshell/observ/event.py` — `RequestEvent` 事件 schema（切片维度字段来源）
- `tests/test_*.py` — 现有 analysis 单测（`test_phase1_observ.py` 等），改造时保持绿
- `docs/TRUTH.md` — 唯一权威信源，方案确认后反向同步

---

*交接结束。接手 agent 请先读 §1（现状）确认代码事实，再产出 §7 的设计方案，勿直接改代码。*
