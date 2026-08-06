# T10 — KV 失效 re-prefill 真机实测结论

**结论一句话**：per-request lora 换帽 **100% 摧毁前缀 KV**（每步一次全量 re-prefill，实测 +1656 tok / **+2.35 s**）；而 roomy 的全局 `POST /lora-adapters` toggle **完全不影响 KV**（缓存全命中，且专家确实换上了）。两条路径成本相差 **415 倍**。另外发现一个 **P0 正确性 bug**：混用两条路径会让专家**静默失效、退回基座模型**。

- 原始数据：`bench/kv_reprefill.json`
- 复现脚本：`scripts/measure_kv_reprefill.py`（纯 stdlib，`python3 measure_kv_reprefill.py --reps 5 --prefix-tokens 1500`）
- 环境：W7900 · `Qwen3.6-27B-Q4_K_M.gguf` · llama.cpp build `b1-272700b` · `n_ctx=8192` · `total_slots=4`
- 采样：固定前缀 1647 tok（全 prompt 1660 tok）、`n_predict=1`、`temperature=0`、**`id_slot=0` 固定**（消除 4 slot 路由混淆）、每组 5 次

---

## 1. 中位数对比表

| 组 | 场景 | `prompt_n`（实际预填充） | `cache_n`（命中） | `prompt_ms` | 判定 |
|---|---|---:|---:|---:|---|
| **A** | 冷启动（`cache_prompt=false`） | **1660** | 0 | 2401.4 | 全量 prefill 基线 |
| **B** | 仅 `cache_prompt`，不换 lora | **4** | 1656 | 160.3 | warm 命中基线 ✅ |
| **C0** | per-request lora，**同一顶帽子**重复 | **4** | 1656 | 174.0 | 命中 ✅ |
| **C** | per-request lora，**每步换帽** | **1660** | **0** | 2513.5 | **KV 全失效** ❌ |
| **D** | roomy 全局 `POST /lora-adapters` toggle | **4** | 1656 | 195.9 | 命中 ✅ |
| **E** | 知识注入（前缀不变，尾部追加） | 610 | 1347 | 934.1 | 部分命中 ✅ |

A–D 四组 5 次采样**零方差**（每次数值完全相同），无需担心抖动。

**判据裁决**（蓝图 §5.2 T10：`median(prompt_n[换帽后]) > 0.5 × median(prompt_n[冷启])` ⇒ 失效）

| 路径 | 比值 | 结论 |
|---|---:|---|
| C（per-request 换帽） | `1660 / 1660` = **1.00** > 0.5 | **KV 失效** |
| D（全局 toggle） | `4 / 1660` = **0.0024** < 0.5 | KV 存活 |

**每次 per-request 换帽的真实成本：多付 1656 个 token 的 prefill = +2353 ms。** 相对 warm 基线是 **415×**。

> 注：团队任务书里的判据写成"`> 0.5 × median(B)`"，B 是 warm 基线（=4）。按该式任何非零值都会被判失效，应以蓝图原文的**冷启基线**为准。两种写法在本次数据下结论一致（C 失效、D 存活），因为差距是 415 倍量级，不在判据敏感区。

---

## 2. 真机 `timings` 字段真实名称（蓝图 §3.10 需按此校正）

`POST /completion` 响应实测字段（**全部存在，无缺失、无降级**）：

| 字段 | 存在 | 说明 |
|---|:--:|---|
| `timings.prompt_n` | ✅ | 真正被预填充的 token 数 —— T10 核心测量量 |
| `timings.cache_n` | ✅ | **本版本额外提供**：直接命中 KV 的 token 数 |
| `timings.prompt_ms` / `prompt_per_second` | ✅ | prefill 耗时 / 吞吐 |
| `timings.predicted_n` / `predicted_ms` / `predicted_per_second` | ✅ | decode 侧 |
| `tokens_evaluated` | ✅ | prompt 总 token 数 |
| `tokens_cached` | ✅ | slot 内缓存 token 数（含本次生成，非命中数） |

⚠️ **两处需要修正蓝图 §3.10 的写法**：

1. `/completion` 端点**没有** `usage` 对象（那是 `/v1/chat/completions` 才有的 OAI 形状）。蓝图写的
   `cached_tokens = max(0, usage.prompt_tokens - timings.prompt_n)`
   在该端点上要写成 `max(0, tokens_evaluated - timings.prompt_n)`。两种算法本次实测结果一致。
2. 本版本直接给了 `timings.cache_n`，**可以省掉减法**。建议 `GenStats.cached_tokens` 的回填顺序改为：
   `timings.cache_n` → 缺失则 `tokens_evaluated - timings.prompt_n` → 再缺失则 `usage.prompt_tokens - timings.prompt_n` → 都没有则 `0`。

另：`generation_settings.lora` **只反映请求级 lora 覆盖**，走全局 toggle 路径时它恒为 `[]`。**不能**用它判断当前生效的是哪顶帽子（本次实验踩过这个坑，见 §3）。

---

## 3. 附加发现（P0 正确性 bug）：混用两条换帽路径 ⇒ 专家静默失效

`prompt_n` / `cache_n` 只能证明"缓存有没有命中"，**不能**证明"权重真的换了"。为此加了正确性探针：固定 `seed=42` + 贪心解码，把生成内容与三份 ground truth（base / btl3 / cybersec，均由已验证可信的"冷启 + per-request lora"路径取得）逐字对拍。

| 探针 | 场景 | 步数 | 结果 |
|---|---|---:|---|
| **P1** | 纯全局路径（`POST /lora-adapters` toggle） | 12 | ✅ 全对 —— 冷启/命中缓存都换对了帽子 |
| **P2** | 纯 per-request 路径 | 8 | ✅ 全对 |
| **P3** | **混用**：per-request 打底 → 转全局路径（命中缓存） | 12 | ❌ **6/12 错，3/3 试次稳定复现** |
| **P4** | 混用反向：全局打底 → 转 per-request | 4 | ✅ 全对（缓存被清，换帽正确） |

**P3 失效细节**：slot 上一次请求用了 per-request `lora` 覆盖，之后改走全局路径（请求体不带 `lora` 字段）且命中缓存时——

- 全局明明设了 `btl3=1.0`，实际生成结果**逐字等于基座模型**（既不是 btl3 也不是上一顶 cybersec）；
- 该错误状态**会持续**：紧接着的第二次 warm 请求依然是基座；
- 只有一次 `cache_prompt=false` 的冷启请求才能恢复正确。

即：**换帽子的动作静默丢失，agent 以为自己戴着专家帽，实际在裸跑基座**，且 HTTP 层没有任何错误信号（`prompt_n`/`cache_n` 一切正常）。

> 这解释了我在中途一度得出"陈旧 KV 污染"的错误假设——真实机制不是复用了旧权重的 KV，而是**adapter 根本没挂上**。
> 补充：本次实验中途曾有两个脚本实例并发争抢 slot 0 并互相篡改全局 lora，产生过一批失真数据，已全部废弃；最终 `bench/kv_reprefill.json` 来自单实例干净运行（`errors: []`）。

---

## 4. 对 T6 / T8 的含义

### T6（P1 prefill 瘦身 + 固定前缀 KV 复用）

- **"固定前缀 KV 复用"在当前 roomy + per-request lora 组合下收益恒等于 0**（`cache_n` 实测恒为 0）。蓝图 §946 的预判成立：此档必须把重心全部压到**裁剪 + 压缩**。
- 但存在一条更划算的路：**改走全局 toggle 路径（D）**。同样是换帽，D 让 1656 tok 全部命中，每步省 2.35 s。若 orchestrator 能从"chat 注入 lora 数组"改成"先 `POST /lora-adapters` 再发不带 `lora` 的请求"，固定前缀复用的收益就**从 0 变成满额**——这比单纯瘦身 prompt 的收益大得多。
  - ⚠️ 前提是必须**彻底二选一，绝不混用**，否则触发 §3 的静默失效。
  - ⚠️ 另一前提：D 是**全局**状态，多会话/多 slot 并发下会互相踩踏；`total_slots=4` 的当前配置需要评估。这是 T6 落地前要架构层面裁决的点。
- C5/R6 的滑窗问题（`memory.history(limit=8)`）依然独立成立：即便走 D 路径，滑窗仍会让前缀每轮变化。E 组证明了**尾部追加式**的变动可以保住前缀命中（1347/1660 命中），所以"稳定窗口 + 变动内容后置"的设计方向是对的。

### T8（P0 §5 叙事重构）

建议叙事按下面三笔账写，全部有本次实测数字支撑：

1. **控制面 ≈ 0.65 ms** —— 数字**是真的**，但它专指 `POST /lora-adapters` 这一条全局 toggle 路径（本次实测 toggle 本身 0.6 ms 量级）。
2. **激活态 decode 税 15–25%** —— 沿用既有实测，本次未复测。
3. **换帽的 prefill 账，取决于走哪条路**：
   - 走 per-request `lora` 注入（当前 roomy 实现）：每次换帽 **一次全量 re-prefill = +1656 tok / +2.35 s**（1.6k 前缀实测），是控制面数字的 **3600 倍**；
   - 走全局 toggle：**0**（前缀 KV 全命中）。

   于是"按步付费"的论点更硬了：**贵的从来不是换帽这个动作，而是换帽把前缀缓存打掉。** 选对路径可以让这笔钱直接归零——这正是"本地部署优化"赛道该讲的原创发现。
4. 可选加分项：§3 的静默失效 bug 是一个真实的、可复现的本地推理栈陷阱，写进 TRUTH/踩坑记录比藏起来更有说服力。

VRAM 18.9 GB / 加载 9 s 两个数字本次未触及，原样保留。

---

## 5. 收尾

- 全程只读测量：未改 server 配置、未重载模型。
- 全局 lora scale 已复位到进场快照 `[{0:0.0},{1:0.0},{2:1.0}]`（`lora_state_restored` 字段可查）。
- 残留的临时脚本与并发实例已清理，`/tmp/kv.py` 保留供复跑。
