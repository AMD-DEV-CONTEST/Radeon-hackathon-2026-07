# ScrewShell 观测台 — 施工计划 V2（V1 部署补课 + 慢诊断 P0 + 联网发现落地）

> 执行者：HY3。自包含文档。前置：`BUILD_OBSERVATORY_PLAN.md`（V1，代码已交付待部署）、`HANDOFF_SLOWNESS_DIAGNOSIS.md`（慢诊断）、`VALIDATION_OBSERVATORY_REPORT.md`（真机可达性证据）。
> 生成：2026-08-05。

---

## 0. 背景与 V1 审阅结论

### 0.1 V1 已交付（本地代码 + 测试，**真机未部署**）
- 改动：`store.py`（gpu_samples 表 + record/recent_gpu）、`relay.py`（GPU 采样线程 + gpu_history/slots/expert/llama_metrics 四端点）、`app.py`（GPU 历史消费 + 槽位行 + 阈值 15–25 + 全局行）、`cli.py`（--metrics 透传，合理偏差）、3 个部署脚本、`tests/test_observ_gpu.py` ×11。
- 审阅实测：`tests/test_observ_gpu.py` → **11 passed**（复跑确认）；HY3 自报全量 250 passed（待本计划阶段 0 前复核）。
- **关键缺口**：TRUTH v14 声称"实例重置 SSH 不可达"——**过时**。`VALIDATION_OBSERVATORY_REPORT.md` 已实测 `root@36.150.116.206:31010` **SSH 可达**（公钥已加回）。V1 部署因此跳过，**本计划阶段 0 先补课**。

### 0.2 V2 范围（慢诊断 P0 + 联网发现）
| 项 | 内容 | 来源 |
|---|---|---|
| 0 | V1 真机部署 + 8 条验收（补课） | V1 §9 |
| 1 | `switch_ms` 记录（切换耗时）→ R2 判读"慢在切专家 vs 生成" + 证实/证伪诊断根因① | 诊断 §7 + 联网复核 |
| 2 | 反馈真空修复升级：**思考流显示**（真空期显示模型思考过程，优于状态提示） | 联网复核判断③ |
| 3 | reasoning-budget 评估 + 27 tok/s 基线复测（并入 llama-server 唯一一次重启） | 联网复核判断② |
| 4 | opencode 路径雷区验证（prefill × enable_thinking 互斥） | 联网复核判断④ |

### 0.3 边界（本计划有意扩展 V1）
- **新增可动**：`inference_coordinator.py`（switch_ms 计时）、`observ/event.py`（RequestEvent 加 switch_ms 字段）。
- **仍不动**：`orchestrator.py`、路由/切换逻辑本身、`RequestEvent` 既有字段语义。
- **零新依赖**；实例离线禁 pip。
- llama-server **只重启一次**（阶段 3 统一：`--metrics` + reasoning 参数评估结果一起生效），阶段 0/1/2/4 不碰它。

---

## 阶段 0：V1 真机部署 + 验收（补课，先做）

### 0.0 ⚠️ 前置检查：SSH 连通性重测（第一道门）

**背景**：SSH 可达性存在**矛盾证据**——00:30 验证报告实测可达（公钥已加回）；但 HY3 施工时实测被拒（host key 变 + publickey 拒），**疑似 00:30 后实例二次重置**。以**本次实测为准**。

```bash
ssh -o ConnectTimeout=10 -p 31010 root@36.150.116.206 "echo OK && hostname && ls /workspace/persistent/screwshell_run | head"
```
- **可达** → 继续 0.1。
- **不可达** → **立即停止，回报用户**（需重新加公钥 / 确认实例状态；可能 `/workspace/persistent/screwshell_run` 又清了，需先核对部署基线）。禁止反复重试、禁止擅自改服务端配置。
- 若 `/workspace/persistent/screwshell_run` 内容异常（被清空）→ 在回报中说明，等用户决定先恢复部署还是先加公钥。

### 0.1 scp 同步（实例 `/workspace/persistent/screwshell_run/`）
```bash
scp -P 31010 screwshell/observ/store.py screwshell/observ/__init__.py \
    root@36.150.116.206:/workspace/persistent/screwshell_run/screwshell/observ/
scp -P 31010 screwshell/gateway/relay.py screwshell/gateway/cli.py \
    root@36.150.116.206:/workspace/persistent/screwshell_run/screwshell/gateway/
scp -P 31010 screwshell/ui/app.py \
    root@36.150.116.206:/workspace/persistent/screwshell_run/screwshell/ui/
scp -P 31010 tests/test_observ_gpu.py \
    root@36.150.116.206:/workspace/persistent/screwshell_run/tests/
```
> ⚠️ 部署脚本 3 个（含 `--metrics`）**本阶段先不推**——`--metrics` 生效要重启 llama-server，留给阶段 3 一次做。

### 0.2 重启 relay + UI（照 HANDOFF_OBSERVATORY.md §6 环境变量，勿用旧脚本）
```bash
export MOL_BACKEND=llamacpp MOL_LLAMACPP_URL=http://127.0.0.1:18090
export MOL_RELAY_MODE=1 RELAY_TRUST_TOKEN=screwshell-relay-devtoken
export OBSERV_DIR=/workspace/persistent/screwshell_run/observ
# relay: nohup /opt/venv/bin/python -m screwshell.gateway.relay > relay.log 2>&1 &
# UI:   nohup /opt/venv/bin/python -m screwshell.ui.app --workspace ... --base ... --port 7860 --no-rag > ui.log 2>&1 &
```

### 0.3 V1 验收（8 条，逐条留证据）
- [ ] `curl :18090/v1/observ/gpu_history?n=10` → 采样线程 2s 周期后 ≥4 条样本
- [ ] **重启 relay 后再 curl** → 历史仍在（SQLite 冷启动回查）
- [ ] `/v1/observ/slots` → 4 slot；UI 状态块生成时"处理中(prog/total)"/空闲"空闲"
- [ ] `/v1/observ/expert` → current_expert；LoRA 面板无回归
- [ ] 面板 decode≈17–20 显示 ✓（15–25 窗口）
- [ ] UI 重启后 GPU 图有历史线（从后端恢复）
- [ ] 实例全量 `pytest tests/ -q` → ≥250 passed（复核 HY3 自报）
- [ ] 未动 loras/、零新依赖、三进程健康

---

## 阶段 1：`switch_ms` 记录（诊断 P0-3 证据 + R2 判读）

**目的**：让观测台/DB 直接回答"慢在切专家还是生成"；同时证实/证伪诊断文档"每步切 LoRA = 数秒"根因（联网判断①指向：全局 toggle 是 ms 级且 KV 保留）。

### 1.1 `screwshell/core/inference_coordinator.py` — 计时（L242/L331 两处）
```python
if switched:
    t0 = time.time()
    await asyncio.to_thread(self.engine.activate, target)
    self._current_expert = target
    ev.switch_ms = round((time.time() - t0) * 1000, 1)   # 新增
ev.switched = switched
```
> 两处（chat 与 streaming 路径）都要加。

### 1.2 `screwshell/observ/event.py` — RequestEvent 加字段
- L52–57 延迟区新增：`switch_ms: Optional[float] = None  # time the global LoRA switch took`

### 1.3 `screwshell/observ/store.py` — 落库 + 聚合
- `_COLS`（L29–34）加 `"switch_ms"`
- `summarize()` 返回值加 `"avg_switch_ms"`（照 `_avg("ttft_ms")` 模式）；空表分支（L112–118）同步加 `"avg_switch_ms": None`

### 1.4 `screwshell/ui/app.py` — 指标面板显示
- `_fmt_metrics` 中文 lines 加：`f"切换耗时 {sw_s}"`（有值显示，n/a 省略；`_ok_warn(sw < 1000)` 标注"切换应<1s"）

### 1.5 测试（并入 `tests/test_observ_gpu.py` 或新增 `tests/test_switch_ms.py`）
- coordinator：mock `engine.activate` 睡 0.01s → 事件 `switch_ms` ≈10ms；未切换（同专家）→ None
- store：`summarize().avg_switch_ms` 聚合正确
- 注意 `event.py` 改字段后，`from_dict` 白名单自动兼容旧记录（`known` 过滤）

---

## 阶段 2：反馈真空修复升级 — 思考流显示

**目的**：真空期（切专家/首 token 前）不再空白，UI 流式显示模型思考内容（Claude Code/OpenCode 同款体验）。

### 2.1 第一步：验证流式 chunk 结构（真机，不改代码）
```bash
curl -s -N -X POST http://127.0.0.1:8080/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model":"m","messages":[{"role":"user","content":"用三步规划一个调查"}],"stream":true,"max_tokens":200}' \
  | head -40
```
- 观察 chunk 里 thinking 内容出现在哪个字段：`delta.reasoning_content`（deepseek 格式）？还是 `delta.content` 带 `<think>` 标签？
- **决策分叉**：
  - 有 `reasoning_content` → 走 2.2 UI 显示
  - 只有 `<think>` 标签混在 content → 可在 UI 解析标签，或给 llama-server 加 `--reasoning-format deepseek`（并入阶段 3 重启）
  - 无 thinking 流（版本不支持）→ **退回诊断 P0-1 原始方案**（提交即显示"切换/连接中"，靠阶段 1 的 switch_ms 数据提示），本阶段降级

### 2.2 UI 显示（`screwshell/ui/app.py` respond 流式生成器）
- 流式循环中识别 thinking chunk → 写入 `_UI_STATE["thinking"]` 累积文本
- `_status_block` / 主气泡：真空期显示 `思考中: {前 80 字}…`（可滚动更新）
- 收尾：回答开始时清空 thinking 缓冲

### 2.3 测试
- 离线 mock 流式 chunk（含/不含 reasoning_content 两种）→ UI 状态块渲染断言
- 不引入新依赖

---

## 阶段 3：reasoning-budget 评估 + 基线复测（llama-server 唯一一次重启）

**目的**：确认 17.5–19.7 tok/s 是否被思考拖慢；对照社区基线 27 tok/s 定"正常"阈值；同时让 `--metrics` 生效（V1 的 4b）。

### 3.1 评估流程（重启前先在现网测，重启后复测）
1. **重启前**：现网（budget 4096）实测 decode_tps 若干样本（记录）
2. **重启**（带 `--metrics`，**reasoning 参数先不动**，单独看 --metrics 是否生效）：`curl :8080/metrics | grep -oE "^llama[a-z_:]*" | sort -u` → 枚举真实指标名，若 501 停做全局行（V1 预案）
3. **关思考复测**：`chat_template_kwargs: {"enable_thinking": false}` 请求 → 对比 decode_tps
4. **决策**（写进交付报告）：
   - 若关思考后 ≈27 tok/s → 思考是主因 → 方案：**保留思考 + 阶段 2 思考流显示**（体验优先）或全局 budget 调小（如 1024，性能优先），用户拍板
   - 若关思考后仍 17–20 → 另有瓶颈（ctx 131072 / KV 量化 / 线程）→ 排查下一层，阈值维持 15–25

### 3.2 部署脚本落 `--metrics`（V1 遗留）
- `deploy/w7900/run_roomy_server.sh` / `run_gateway.sh`（cli `--metrics`）/ `llama-swap-managed.yaml` 三处已改好，本阶段 scp 到实例并重启 llama-server
- ⚠️ 重启 = 2–3 分钟加载 + 全 KV 失效；**挑低峰期**；保留原命令快照回滚

### 3.3 风险
- 若 `/metrics` 501（llama.cpp 版本不支持）→ 全局行停做，UI 显示 n/a（V1 预案），不影响其他项

---

## 阶段 4：opencode 路径雷区验证

**目的**：确认 opencode 直连 relay 是否踩 `prefill-assistant × enable_thinking` 互斥（社区案例"完美风暴"）。

### 4.1 验证（真机）
```bash
# 用 opencode 配置（本机 C:\Users\djb\.config\opencode\opencode.json, model screwshell-base）发真实请求
# 或直接模拟 opencode 请求形状走 relay：
curl -s -X POST http://127.0.0.1:18090/v1/chat/completions \
  -H "X-Relay-Token: screwshell-relay-devtoken" -H "Content-Type: application/json" \
  -d '{"model":"screwshell-base","messages":[{"role":"user","content":"读一下 config 文件"}],"stream":true}' \
  | head -30
```
- 观察：是否正常流式返回；llama-server 日志有无 prefill/thinking 冲突告警；耗时是否异常

### 4.2 若踩雷（预案）
- relay 侧统一注入 `chat_template_kwargs: {"enable_thinking": false}`（对外部前端默认关思考，UI 走 orchestrator 不受影响）——最小改动点：relay `_handle` 构造 body 时补 kwargs
- 或改本机 opencode 配置（`chat_template_kwargs`）——不碰 relay

### 4.3 测试
- relay 层：mock 请求体注入逻辑 → 断言 kwargs 存在（若走 4.2 方案）

---

## 阶段 5：收尾（三道闸 + 提交）

1. **三道闸**：① 本机全量 `pytest tests/`（重定向文件；新增 switch_ms/thinking 测试后基线 250 → 250+N）② `scripts/verify_bugfixes.py` EXIT=0 ③ `git fsck` 无 missing
2. **TRUTH.md** §3 基线更新 + **v15 行**（V1 部署验收 + V2 全部落地，含 reasoning 决策结论）
3. **提交 + push**：V1 未 push 的提交（3fcf869/d21f08a/d6b0fd1）+ 本轮施工合一个提交；push origin/main
4. 交付：施工报告（阶段 0–4 每项证据 + reasoning 决策 + opencode 验证结论）

---

## 验收总清单（全部通过才算完工）

- [ ] 阶段 0：V1 8 条验收全过（含 relay 重启后 gpu_history 仍有历史）
- [ ] 阶段 1：事件含 switch_ms；面板显示"切换耗时"；`summarize.avg_switch_ms` 有值
- [ ] 阶段 1 数据回答：切换耗时是 ms 级还是 s 级（根因①定案）
- [ ] 阶段 2：真空期显示思考流（或确认版本不支持 → 降级 P0-1 状态提示并注明）
- [ ] 阶段 3：`--metrics` 生效（或 501 停做）；关思考 vs 开思考 decode_tps 对照数据；reasoning 决策已记录
- [ ] 阶段 4：opencode 路径正常（或雷区已修 + 测试）
- [ ] 三道闸全绿 + TRUTH v15 + push 完成
- [ ] 全程零新依赖、未动 orchestrator/路由/既有事件语义

---

## 附：关键文件行号（改动点速查）

- `inference_coordinator.py`：L242 / L331（activate 计时点，两处）
- `event.py`：L52–57（延迟区，加 switch_ms）
- `store.py`：`_COLS` L29–34；`summarize` L112–118（空表分支）/ L125–147（聚合）
- `app.py`：`_fmt_metrics` L341–368（加切换行）；respond 流式循环（阶段 2，位置实施时定位）；`_UI_STATE` L174–177
- `relay.py`：`_handle` L176–187（阶段 4 注入点）
- 部署脚本：`run_roomy_server.sh` / `run_gateway.sh` / `llama-swap-managed.yaml`（--metrics 已加，待 scp）
