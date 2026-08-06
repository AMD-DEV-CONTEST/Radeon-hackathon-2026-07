# 3. JSON-RPC Notification 契约

> 守护进程→调用方的单向推送（无 `id`，fire-and-forget）。
> 调用方连接守护进程后会持续收到 notification，直到断开。
> 实现源码：`crates/domain/src/telemetry_service.rs`、`crates/daemon/src/bootstrap.rs:193-219`

守护进程产生两类 notification：`telemetry`（周期状态推送）与 `alert`（阈值告警）。
调用方实现时，**收到 notification 不要当作 Request 的 Response**（见 [`envelope.md` §1.5](envelope.md#15-id-配对规则调用方实现要点)）。

## 3.1 `telemetry`

周期性硬件状态推送。守护进程采集循环按 `telemetry.interval_secs`（默认 5s）每轮发一条。

**触发条件**：`telemetry.interval_secs > 0`。设为 `0` 关闭推送（仅拉取模式）。

**结构**：
```json
{
  "jsonrpc": "2.0",
  "method": "telemetry",
  "params": { <整个 StateSnapshot 序列化为对象> }
}
```
- **无 `id`**。
- `params`：Named 对象，即整个 `StateSnapshot`（字段见 [`data-model.md`](data-model.md)）。
- `timestamp` 是采集时刻，调用方可据此判断数据新鲜度。

**示例（节选）**：
```json
{"jsonrpc":"2.0","method":"telemetry","params":{
  "timestamp":"2026-07-28T05:41:48Z",
  "thermal":{"zones":[{"name":"thermal-ddr","tempC":62.245},{"name":"thermal-cpu","tempC":61.659}]},
  "cpu":{"load_avg":[1.58,2.32,1.15],"core_freq_mhz":[1500.0]},
  "memory":{"totalBytes":7424344064,"usedBytes":2960527360,"freeBytes":1149628416}
}}
```

## 3.2 `alert`

阈值告警。当硬件状态越过配置阈值时，守护进程**立即**（采集轮评估后）推送。一个采集轮可能产生多条（多个越限实体）。

**触发条件**（`crates/domain/src/alert_service.rs`）：
- **温度**：任一 thermal zone `temp_c >= alerts.temp_c`（默认 75.0°C）。
- **磁盘**：任一真实文件系统 `usage_pct >= alerts.disk_usage_pct`（默认 90.0%）。

**结构**：
```json
{
  "jsonrpc": "2.0",
  "method": "alert",
  "params": {
    "kind": "<thermal | disk>",
    "target": "<zone 名 或 磁盘挂载点>",
    "current": <当前值>,
    "threshold": <阈值>
  }
}
```
- **无 `id`**。
- `kind`：`"thermal"` 或 `"disk"`。
- `target`：温度 zone 名（如 `"thermal-cpu"`）或磁盘挂载点（如 `"/"`）。
- `current`：当前值（温度 °C 或使用率 %）。
- `threshold`：触发的阈值。

**示例（温度告警）**：
```json
{"jsonrpc":"2.0","method":"alert","params":{"kind":"thermal","target":"thermal-cpu","current":80.5,"threshold":75.0}}
```

**示例（磁盘告警）**：
```json
{"jsonrpc":"2.0","method":"alert","params":{"kind":"disk","target":"/","current":95.2,"threshold":90.0}}
```

## 3.3 调用方实现建议

1. **telemetry**：用于持续监控大屏，按 `timestamp` 去重/排序，断线重连后先 `get_state` 拿一次全量再续听。
2. **alert**：触发通知（webhook/邮件/日志），建议带去抖（同一 entity 短时间内重复告警合并）。
3. **连接保活**：notification 是被动推送，调用方应定期发 `ping` 确认连接存活；长时间无 telemetry 也可能意味着连接断了。
