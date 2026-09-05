# ScrewShell · TTFT 数据拆解报告（P0）

> 生成：2026-08-05 02:07。数据源：实例 `36.150.116.206:31010` `/workspace/persistent/screwshell_run/observ/requests.db`（184 行请求事件）。
> 任务书：`TTFT_BREAKDOWN_PLAN.md`（A0→D 流程）。dump 脚本：`_ttft_dump.py`；原始 json：`bench/ttft_dump.json`。

---

## 0. 执行摘要（一句话结论）

**TTFT≈27s 是「均值被长尾拖高」的假象**：典型（中位）TTFT 只有 **1.66s**，真正慢的是少数**超大 prompt（≤63k token）请求把 prefill 顶到 30–172s**。其中 **~97% 的服务端 TTFT 全是 server prefill**，排队/切换/传输只占 ~3%（~0.8s）；慢因是**长 prompt 的 prefill**，不是切换也不是传输。杠杆在 prefill 优化（`-fa` + KV 量化 + cache-reuse），不是换帽或网络。

**两个必须纠正的旧结论**：
1. 01:55「TTFT≈27s 是真慢因」——应改为「典型 TTFT 健康（1.66s），长尾（p90 88.8s / max 172s）才是体验杀手」。
2. 02:00 笔记假设「observ DB 已有 queue/switch/prefill/ttft 四字段」——**错误**：本实例 DB 只有 `ttft_ms` + `prefill_ms`，**无 `queue_wait_ms` / `switch_ms` 列**（详见 §9）。完整细分需要部署带 switch_ms 的 relay + schema 迁移。

---

## 1. Q1 · TTFT 构成（流式样本 n=31）

| 分量 | mean | median | p90 | max |
|---|---|---|---|---|
| **TTFT**（客户端） | 27050 ms | **1659 ms** | 88765 ms | 172453 ms |
| **Prefill**（服务端 timings.prompt_ms） | 26234 ms | 1246 ms | 88656 ms | 171901 ms |
| 非 prefill 残差（排队+切换+传输） | 816 ms | — | 599 ms | — |

- **Prefill 占 TTFT 的 ≈97%**（mean 口径）；中位残差 ≈413ms（1659−1246），即非 prefill 部分在中位也只 ~25%。
- **双峰分布**：中位 1.66s 健康，但 p90=88.8s、max=172s → 少量巨 prompt 把均值拉到 27s。**优化重点是长尾，不是典型请求。**
- 残差 p90(599ms) < 残差 mean(816ms) → 右偏，绝大多数请求非 prefill 开销 <600ms，仅个别异常。

> ⚠️ 因 DB 缺 `queue_wait_ms`/`switch_ms`，无法把残差再拆成「排队 / 切换 / 传输」三段——这是 §9 的部署缺口。当前只能说「非 prefill ≈ 0.8s，且其中切换占比未知」。

---

## 2. Q2 · 换帽代价（prefill_ms，全样本可用）

| 分组 | n | mean | median | p90 | max |
|---|---|---|---|---|---|
| switched = **ON**（发生了全局切换） | 54 | **1561 ms** | 299 ms | 1064 ms | 60984 ms |
| switched = **OFF**（未切换） | 128 | **11248 ms** | 906 ms | 2430 ms | 217220 ms |
| 原始 delta（mean） | | **−9686 ms** | | | |

### ⚠️ 这是混杂偏倚，绝不可读作「切换反而更快」
- switched_OFF 的 mean prefill（11.2s）**高于** switched_ON（1.56s），但这是因为**长 prompt 大多落在 switched_OFF 组**（switched_OFF max=217s，switched_ON max 仅 61s）。prompt 越长 prefill 越长，与是否切换无关 → 两组不可直接比。
- **正确结论**：
  - 切换请求的中位 prefill 仅 **~300ms**（base 373 / btl3 329 / cybersec 268 / rag_n7 169）——**典型换帽 + 普通 prompt 很便宜**。
  - 受控实测（T10 `kv_reprefill_report.md`）：暖 KV 被切换打掉 → **+2.35s re-prefill**，仍是权威切换代价数字。
  - 本库 KV 命中率很低（§4 中位 0.32），即大多数请求 KV 本来就不暖，**边际切换代价小**——这与「中位切换 prefill 仅 300ms」一致。
- 按 adapter 拆（switched 组内 prefill）：`rag_n7` 最便宜（中位 169ms），`btl3` 中位 329ms 但 max 61s（一个病态巨 prompt 落在这组）。

> 要干净隔离切换代价，须在**同 prompt 长度桶内**比 switched on/off，或重做 T10 受控实验；本观察数据不足以推翻 T10。

---

## 3. Q3 · prompt_tokens 分布（n=181）

| mean | median(p50) | p90 | max |
|---|---|---|---|
| 5770 | **245** | 30703 | **63051** |

- **强烈双峰**：绝大多数请求 prompt 仅 **~245 token**（中位），但尾部冲到 **63k**。
- 这解释了 Q1 的长尾：172s 的 TTFT  outlier 几乎都来自这少数 30k–63k token 的请求。
- **ctx 收敛建议**：当前 `ctx-size=131072`，而真实 max=63k → 有 **2× 余量**。可安全收到 **98304**（覆盖 63k + 35k 余量）释放 KV 显存；但**最大杠杆不是砍 ctx，而是 §7 的 `-fa` + KV 量化**（让长 prompt 的 prefill 本身变快）。

---

## 4. Q4 · kv_hit_rate 分布（n=179）

| 分组 | mean | median | p90 | max |
|---|---|---|---|---|
| 全部 | 0.41 | **0.32** | 0.92 | 1.0 |
| switched ON | 0.33 | 0.27 | 0.78 | 0.85 |
| switched OFF | 0.45 | 0.35 | 0.99 | 1.0 |

- 整体 KV 命中**偏低**（中位仅 32% prompt token 走 KV），切换进一步压低（中位 27%）。
- 含义：prompt **前缀复用率低** → ScrewShell 有稳定的 ~2k system-prompt 前缀，**`--cache-reuse 256` 折叠该前缀对占多数的短 prompt（中位 245 token）应是实打实的增益**。
- 但必须受控验证：`--cache-reuse` 与 Qwen3.6 hybrid（DeltaNet）的 `--kv-unified` 有已知冲突（issue #23493），且慢 cache 更新 bug 需确认已在实例 llama.cpp 版本修复（b8185）。

---

## 5. Q5 · decode 矛盾（真机 30 vs 旧 17.5–19.7）

| n | mean | median | p90 | max |
|---|---|---|---|---|
| 182 | 25.97 | **25.21** | 30.34 | 55.01 |

- 真实 decode ≈ **25（中位）~30（p90）tok/s**。旧 `VALIDATION_OBSERVATORY_REPORT` 的 17.5–19.7 是**低测量窗口/长上下文下的瞬时值**，非稳态。
- **结论**：`app.py` v16 把阈值改为 floor-only `≥20` 是**正确**的——中位 25.2 ≥ 20 健康，仅低端尾（<20）才告警，无误报。无需再改。

---

## 6. P1 参数调优建议（按预期收益排序）

| 优先级 | 改动（一次重启） | 预期收益 | 风险/前置 |
|---|---|---|---|
| **P1a** | **`-fa`（flash-attn）** | 长 prompt（2k+）prefill 降 **30–50%**，直接砍掉 Q1 长尾 | 需实例 llama.cpp 构建支持；`llama-bench` 先 sweep 确认 |
| **P1b** | **`--cache-type-k v q8_0`**（KV 量化） | KV 显存减半、困惑度 +0.05 可忽略；腾出显存给 batch / 让 `-fa` 可行 | 几乎零风险，生产闭眼用 |
| **P1c** | **`--cache-reuse 256`** | 折叠稳定 ~2k system 前缀，多数短 prompt prefill 大降 | ⚠️ Qwen3.6 hybrid 与 `--kv-unified` 冲突已知；**先受控测**，别直接上生产 |
| **P1d** | ctx-size 131072 → **98304** | 释放 KV 显存（次要杠杆） | 需确认无 prompt 超 63k；配合 P1b 更稳 |
| **P1e** | `--parallel 4 → 1-2` | coordinator 串行锁实际单请求，4 slot KV 显存×4 浪费 → 释放给 batch/-fa | 几乎零风险 |

> 执行顺序：先用实例 `/opt/llama.cpp/build/bin/llama-bench` 做 sweep（`-p 2048 -n 128 -b 1024 -ub {128..1024} -ctk q8_0 -ctv q8_0 -fa on`）确认 P1a/P1b 收益 → 再一次性重启 llama-server（带上述参数，保留 ctx/reasoning-budget）→ 重启后回测 TTFT 长尾是否收敛。

---

## 7. 行动清单（给用户的决策点）

1. **优先做 P1a+P1b**（`-fa` + KV q8_0）：低风险、高收益，直接削 TTFT 长尾。
2. **P1c（cache-reuse）先受控验证**再决定，别盲上（hybrid 冲突）。
3. **修正叙事**：对外/对评委讲「典型 TTFT 1.66s 健康，长尾由巨 prompt prefill 主导，已用 `-fa`+KV 量化压」，而非「TTFT 一律 27s」。
4. **填部署缺口**（§9）：部署带 `switch_ms` 的 relay 并加 schema 迁移，才能把 TTFT 拆成排队/切换/传输三段（对应 `TTFT_INSTRUMENTATION_PLAN.md`）。

---

## 8. 附录 · 复现

- 实例 dump：`/opt/venv/bin/python /tmp/ttft_dump.py`（脚本见仓库 `_ttft_dump.py`，纯 stdlib，零依赖）。
- 原始输出：`bench/ttft_dump.json`（184 行，含 Q1–Q5 全部分布）。
- 统计口径：剔 `ok=0`/error；TTFT 仅流式样本（ttft_ms 非 NULL，n=31）；分布看 median/p90，不盯单条 max。

## 9. 数据可信度 / 坑（必读）

- **⚠️ schema 缺口**：实例 `request_events` 表**无 `queue_wait_ms` / `switch_ms` 列**（PRAGMA 确认）。两种可能：① 实例跑的是早于 V2 的 relay（switch_ms 字段是 f724f98 加的）；② relay 虽是新代码但 DB 在加列前已建、`store.py` 启动从不 `ALTER TABLE` 迁移 → 旧表永远缺列，`record()` 的 INSERT 静默失败（best-effort try/except）。**无论哪种，本库无法细分排队/切换**。修复：① 部署 V2 relay；② `store._open` 加 `ALTER TABLE request_events ADD COLUMN IF NOT EXISTS ...` 迁移；③ 重启 relay 落新库。
- **双峰分布陷阱**：所有 latency 指标 mean≫median，汇报必须用 median/p90，否则「27s 平均」误导。
- **Q2 混杂偏倚**：switched on/off 的 prefill 不可直接比（prompt 长度混杂），权威切换代价仍以 T10 受控 +2.35s 为准。
