# 3. HTTP/REST 示例集

> 实战 curl 示例，覆盖每个路由。
> 假设网关跑在板子 `192.168.128.10:8080`。

## 3.1 准备：启动网关

板端：
```sh
probe-http-gateway --listen 0.0.0.0:8080 --daemon-sock /run/probe-daemon/probe.sock
```
（需先启动 `probe-daemon`。）

## 3.2 健康检查

```sh
curl http://192.168.128.10:8080/healthz
```
```json
{"pong":true,"ts":"2026-07-28T07:48:54Z"}
```

## 3.3 拉取完整状态

```sh
curl http://192.168.128.10:8080/state | jq .
```
（节选，完整字段见 [`../jsonrpc/data-model.md`](../jsonrpc/data-model.md)）
```json
{
  "thermal": {"zones": [{"name": "thermal-ddr", "tempC": 63.075}]},
  "cpu": {"load_avg": [1.87, 2.4, 1.17], "core_freq_mhz": [1500.0]},
  "memory": {"totalBytes": 7424344064, "usedBytes": 2954145792, "freeBytes": 1119498240}
}
```

## 3.4 单片段

```sh
curl http://192.168.128.10:8080/thermal
```
```json
{"zones":[{"name":"thermal-ddr","tempC":63.075},{"name":"thermal-cpu","tempC":62.538}]}
```

```sh
curl http://192.168.128.10:8080/memory
```
```json
{"freeBytes":1149628416,"swapTotalBytes":0,"swapUsedBytes":0,"totalBytes":7424344064,"usedBytes":2960527360}
```

## 3.5 立即刷新

```sh
curl -X POST http://192.168.128.10:8080/refresh
```
```json
{"ok":true,"ts":"2026-07-28T07:48:54Z"}
```

## 3.6 执行 shell

```sh
curl -X POST http://192.168.128.10:8080/exec \
  -H 'Content-Type: application/json' \
  -d '{"cmd":"date"}'
```
```json
{"exit":0,"stdout":"Tue Jul 28 03:48:54 PM CST 2026\n","stderr":""}
```

```sh
curl -X POST http://192.168.128.10:8080/exec \
  -d '{"cmd":"uname -a"}'
```
```json
{"exit":0,"stdout":"Linux ubuntu 6.1.83 #2 SMP ... aarch64 GNU/Linux\n","stderr":""}
```

## 3.7 错误场景

**shell 未启用 → 403**：
```sh
curl -i -X POST http://192.168.128.10:8080/exec -d '{"cmd":"echo hi"}'   # 配置 enabled=false
# HTTP/1.1 403 Forbidden
# {"error":{"code":-32001,"message":"raw shell is disabled in the daemon config"}}
```

**命中 deny → 403**：
```sh
curl -i -X POST http://192.168.128.10:8080/exec -d '{"cmd":"mkfs /dev/x"}'
# HTTP/1.1 403 Forbidden
# {"error":{"code":-32002,"message":"command matches deny pattern: mkfs"}}
```

**命令超时 → 504**：
```sh
curl -i -X POST http://192.168.128.10:8080/exec -d '{"cmd":"sleep 100"}'  # timeout=10
# HTTP/1.1 504 Gateway Timeout
# {"error":{"code":-32003,"message":"command timed out (10s)"}}
```

**body 缺 cmd → 400**：
```sh
curl -i -X POST http://192.168.128.10:8080/exec -d '{}'
# HTTP/1.1 400 Bad Request
```

## 3.8 浏览器/脚本集成

- 浏览器直接访问 `http://board:8080/state` 可看到 JSON（建议装 JSON 格式化插件）。
- Prometheus/Grafana 等监控可用 `/state` 或各单片段做 JSON 抓取，定时拉取。
- 注意：HTTP 网关**不推送** telemetry/alert notification，要推送走 JSON-RPC 直连或 WebSocket 出站。
