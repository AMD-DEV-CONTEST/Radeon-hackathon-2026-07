# 2. HTTP 错误码契约

> REST 网关的 HTTP 状态码 + 错误响应体。
> 实现源码：`crates/api-http/src/error.rs`

## 2.1 成功响应

HTTP 200，body 是 JSON-RPC 的 `result`（直接透传后端 `serde_json::Value`）。

## 2.2 错误响应格式

非 200 状态码，body：
```json
{"error": "<string> | {object}"}
```

## 2.3 JSON-RPC 错误码 → HTTP 状态码

后端守护进程返回的 JSON-RPC `error.code`，映射为 HTTP 状态码：

| JSON-RPC code | HTTP 状态码 | HTTP 含义 | JSON-RPC 含义 |
|--------------|------------|----------|--------------|
| -32601 | 404 Not Found | 资源不存在 | MethodNotFound |
| -32602 | 400 Bad Request | 请求参数错 | InvalidParams |
| -32000 | 500 Internal Server Error | 服务端错 | ExecError |
| -32001 | 403 Forbidden | 禁止访问 | ShellDisabled |
| -32002 | 403 Forbidden | 禁止访问 | ShellDenied |
| -32003 | 504 Gateway Timeout | 网关超时 | Timeout |
| -32004 | 429 Too Many Requests | 限流 | RateLimited |
| 其它 | 500 Internal Server Error | 兜底 | — |

JSON-RPC 错误码完整定义见 [`../jsonrpc/errors.md`](../jsonrpc/errors.md)。

响应体（服务端错误）：
```json
{"error": {"code": -32002, "message": "command matches deny pattern: mkfs"}}
```

## 2.4 网关自身错误（非后端错）

| 场景 | HTTP 状态码 | 响应体 |
|------|-----------|--------|
| 守护进程响应超时 | 504 Gateway Timeout | `{"error":{"code":-32003,"message":"响应超时（N 秒）"}}` |
| 守护进程连接关闭 | 502 Bad Gateway | `{"error":"daemon 连接关闭"}` |
| transport 错误 | 502 Bad Gateway | `{"error":"transport: <msg>"}` |
| 协议错误 | 502 Bad Gateway | `{"error":"protocol: <msg>"}` |

## 2.5 客户端侧错误（请求本身）

| 场景 | HTTP 状态码 | 说明 |
|------|-----------|------|
| `POST /exec` body 非 JSON 或缺 `cmd` | 400 Bad Request | axum 反序列化失败 |
| 未知路径 | 404 Not Found | axum 路由 |

## 2.6 示例

**403（shell 被拒）**：
```sh
$ curl -i -X POST http://board:8080/exec -H 'Content-Type: application/json' -d '{"cmd":"mkfs /dev/x"}'
HTTP/1.1 403 Forbidden
content-type: application/json

{"error":{"code":-32002,"message":"command matches deny pattern: mkfs"}}
```

**504（命令超时）**：
```sh
$ curl -i -X POST http://board:8080/exec -d '{"cmd":"sleep 100"}'
HTTP/1.1 504 Gateway Timeout
content-type: application/json

{"error":{"code":-32003,"message":"command timed out (10s)"}}
```

**404（未知路径）**：
```sh
$ curl -i http://board:8080/nonexistent
HTTP/1.1 404 Not Found
```
