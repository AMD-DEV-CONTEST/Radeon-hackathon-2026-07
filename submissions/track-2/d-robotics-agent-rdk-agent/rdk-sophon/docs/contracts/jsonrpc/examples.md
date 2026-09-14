# 5. JSON-RPC 示例集

> 实战请求/响应示例，覆盖每个方法 + notification + 错误场景。
> 所有示例均为可直接发给守护进程的 NDJSON 行（一行一条，以 `\n` 结尾）。
> 用 `nc <board-ip> 7777` 即可复现。

## 5.1 准备：连接守护进程

守护进程默认监听 `0.0.0.0:7777`（TCP）。从开发机：
```sh
nc <board-ip> 7777
```
连接后，逐行发 JSON-RPC 请求（每行一个 `\n` 结尾），守护进程逐行返回响应。
连接保持期间，还会收到 `telemetry`/`alert` notification（无 `id`）。

## 5.2 ping

**请求**：
```json
{"jsonrpc":"2.0","id":1,"method":"ping"}
```
**响应**：
```json
{"jsonrpc":"2.0","id":1,"result":{"pong":true,"ts":"2026-07-28T07:48:54Z"}}
```

## 5.3 get_state（完整状态）

**请求**：
```json
{"jsonrpc":"2.0","id":2,"method":"get_state"}
```
**响应**（节选，完整字段见 [`data-model.md`](data-model.md)）：
```json
{"jsonrpc":"2.0","id":2,"result":{
  "timestamp":"2026-07-28T05:41:14Z","hostname":"ubuntu","uptime_secs":56221.73,
  "thermal":{"zones":[{"name":"thermal-ddr","tempC":62.245},{"name":"thermal-cpu","tempC":61.659}]},
  "cpu":{"load_avg":[1.87,2.4,1.17],"core_usage":[0,0,0,0,0,0,0,0],"core_freq_mhz":[1500.0]},
  "memory":{"totalBytes":7424344064,"usedBytes":2954145792,"freeBytes":1119498240,"swapTotalBytes":0,"swapUsedBytes":0},
  "disks":[{"mount":"/","fs_type":"ext4","totalBytes":30966890496,"usedBytes":19720384512,"freeBytes":9741590528,"usage_pct":63.68}],
  "net":[{"name":"wlan0","up":true,"mac":"18:ce:df:79:40:53","addrs":["192.168.128.10"],"rxBytes":304664629,"txBytes":1410732}]
}}
```

## 5.4 get_thermal

```json
{"jsonrpc":"2.0","id":3,"method":"get_thermal"}
```
```json
{"jsonrpc":"2.0","id":3,"result":{"zones":[{"name":"thermal-ddr","tempC":63.075},{"name":"thermal-cpu","tempC":62.538}]}}
```

## 5.5 exec_shell（成功）

```json
{"jsonrpc":"2.0","id":4,"method":"exec_shell","params":{"cmd":"uname -a"}}
```
```json
{"jsonrpc":"2.0","id":4,"result":{"exit":0,"stdout":"Linux ubuntu 6.1.83 #2 SMP PREEMPT ... aarch64 GNU/Linux\n","stderr":""}}
```

## 5.6 exec_shell（被 deny 拦截）

```json
{"jsonrpc":"2.0","id":5,"method":"exec_shell","params":{"cmd":"mkfs /dev/sda1"}}
```
```json
{"jsonrpc":"2.0","id":5,"error":{"code":-32002,"message":"command matches deny pattern: mkfs"}}
```

## 5.7 exec_shell（未启用）

配置 `[shell] enabled = false` 时：
```json
{"jsonrpc":"2.0","id":6,"method":"exec_shell","params":{"cmd":"echo hi"}}
```
```json
{"jsonrpc":"2.0","id":6,"error":{"code":-32001,"message":"raw shell is disabled in the daemon config"}}
```

## 5.8 exec_shell（超时）

配置 `shell.timeout_secs = 1`，命令 `sleep 10`：
```json
{"jsonrpc":"2.0","id":7,"method":"exec_shell","params":{"cmd":"sleep 10"}}
```
```json
{"jsonrpc":"2.0","id":7,"error":{"code":-32003,"message":"command timed out (1s)"}}
```

## 5.9 exec_shell（缺参数）

```json
{"jsonrpc":"2.0","id":8,"method":"exec_shell","params":{}}
```
```json
{"jsonrpc":"2.0","id":8,"error":{"code":-32602,"message":"missing `cmd` string param"}}
```

## 5.10 未知方法

```json
{"jsonrpc":"2.0","id":9,"method":"get_power"}
```
```json
{"jsonrpc":"2.0","id":9,"error":{"code":-32601,"message":"unknown method: get_power"}}
```

## 5.11 telemetry notification（被动收到）

连接后守护进程每 5s（`telemetry.interval_secs`）推一条：
```json
{"jsonrpc":"2.0","method":"telemetry","params":{"timestamp":"2026-07-28T05:41:48Z","thermal":{"zones":[{"name":"thermal-cpu","tempC":62.0}],"...":"..."}}
```
**注意无 `id`**——调用方不要为此发响应。

## 5.12 alert notification（被动收到）

温度超阈值（`alerts.temp_c`）时收到：
```json
{"jsonrpc":"2.0","method":"alert","params":{"kind":"thermal","target":"thermal-cpu","current":80.5,"threshold":75.0}}
```

## 5.13 一次连接的完整时序示例

```sh
# 开发机
$ nc board 7777
{"jsonrpc":"2.0","id":1,"method":"ping"}              # 请求
{"jsonrpc":"2.0","id":1,"result":{"pong":true,"ts":"...Z"}}   # 响应
{"jsonrpc":"2.0","method":"telemetry","params":{...}}          # 被动 telemetry（无 id）
{"jsonrpc":"2.0","method":"telemetry","params":{...}}          # 5s 后又一条
{"jsonrpc":"2.0","id":2,"method":"get_thermal"}        # 请求
{"jsonrpc":"2.0","id":2,"result":{"zones":[...]}}              # 响应
^C
```

## 5.14 用 sophonctl 代替 nc（推荐）

手敲 JSON 易错，推荐用 `sophonctl`（底层走同一协议）：
```sh
sophonctl --host board:7777 state
sophonctl --host board:7777 exec uname -a
```
CLI 契约见 [`../cli/sophonctl.md`](../cli/sophonctl.md)。
