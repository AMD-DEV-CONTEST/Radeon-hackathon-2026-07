# 1. HTTP/REST 路由契约

> 协议：HTTP/1.1 + JSON。
> REST 网关二进制 `probe-http-gateway`，把守护进程的 JSON-RPC 包成 HTTP。
> 实现源码：`crates/api-http/src/routes.rs`

## 1.1 启动参数

```
probe-http-gateway --listen 0.0.0.0:8080 --daemon-sock /run/probe-daemon/probe.sock --timeout 10
```
- `--listen`：HTTP 监听地址，默认 `0.0.0.0:8080`。
- `--daemon-sock`：本地守护进程的 Unix socket 路径，默认 `/run/probe-daemon/probe.sock`。
- `--timeout`：连守护进程的响应超时（秒），默认 `10`。

网关作为本地 daemon 的 Unix 客户端，对外暴露 REST。适合 curl / 浏览器 / 脚本访问。

## 1.2 路由表

| HTTP 方法 | 路径 | 请求体 | 后端 JSON-RPC | 响应体 | 说明 |
|-----------|------|--------|--------------|--------|------|
| GET | `/healthz` | 无 | `ping` | `{"pong":true,"ts":...}` | 健康检查 |
| GET | `/state` | 无 | `get_state` | `StateSnapshot` JSON | 完整状态 |
| GET | `/thermal` | 无 | `get_thermal` | `Thermal` 或 `null` | 温度 |
| GET | `/cpu` | 无 | `get_cpu` | `CpuInfo` 或 `null` | CPU |
| GET | `/memory` | 无 | `get_memory` | `MemoryInfo` 或 `null` | 内存 |
| GET | `/disk` | 无 | `get_disk` | `[DiskInfo]` 或 `null` | 磁盘 |
| GET | `/net` | 无 | `get_net` | `[NetInfo]` 或 `null` | 网络 |
| GET | `/bpu` | 无 | `get_bpu` | `BpuInfo` 或 `null` | BPU |
| POST | `/refresh` | 无 | `refresh_state` | `{"ok":true,"ts":...}` | 立即刷新 |
| POST | `/exec` | `{"cmd":"<string>"}` | `exec_shell` | `{"exit":?,"stdout":str,"stderr":str}` | 执行 shell |

各响应体字段定义见 [`../jsonrpc/data-model.md`](../jsonrpc/data-model.md)。

## 1.3 请求/响应格式

- 所有响应 `Content-Type: application/json`。
- `POST /exec` 请求体是 JSON 对象：`{"cmd": "uname -a"}`。
- 成功：HTTP 200 + JSON body。
- 失败：见 [`errors.md`](errors.md) 的状态码 + `{"error": ...}`。

## 1.4 `/exec` 细节

请求体 struct：`ExecBody { cmd: String }`（`routes.rs:68-71`）。
响应体 struct：`ExecResp { exit: Option<i32>, stdout: String, stderr: String }`（`routes.rs:73-78`）。
若后端返回的 JSON 反序列化为 `ExecResp` 失败，兜底为全空（`exit: null`, `stdout: ""`, `stderr: ""`）。

## 1.5 限制

- HTTP 网关是**同步请求/响应翻译**，不支持守护进程的 notification（`telemetry`/`alert`）推送。要接收推送，用 JSON-RPC 直连或 WebSocket 出站。
- 网关本身不做鉴权，依赖网络层隔离。生产建议放在反向代理后或加 mTLS。
