# 1. JSON-RPC 信封契约

> 协议：JSON-RPC 2.0 over NDJSON（换行分隔的 JSON，一行一条）。
> 本文档定义**信封结构**，外部调用方据此构造请求、解析响应。
> 实现源码：`crates/shared/src/protocol/message.rs`

## 1.1 消息类型

每条消息是 `Request`、`Response`、`Notification` 三者之一（反序列化时按字段自动判别）：

| 类型 | 有 `id`? | 有 `method`? | 有 `result`/`error`? | 用途 |
|------|---------|-------------|---------------------|------|
| Request | ✓ | ✓ | ✗ | 调用方 → 守护进程，期望响应 |
| Response | ✓ | ✗ | ✓（二选一） | 守护进程 → 调用方，回应 Request |
| Notification | ✗ | ✓ | ✗ | 守护进程 → 调用方，单向推送（telemetry/alert） |

## 1.2 Request 结构

```json
{
  "jsonrpc": "2.0",
  "id": <number | string>,
  "method": "<方法名>",
  "params": { ... }            // 可选，省略时不序列化
}
```

- `jsonrpc`：固定 `"2.0"`。
- `id`：`number`（i64）或 `string`。**必须**提供，响应会原样回带以便配对。建议用递增整数。不要用 `null`。
- `method`：方法名，见 [`methods.md`](methods.md)。
- `params`：`Named`（对象）或 `Positional`（数组），主用 Named。无参数的方法省略此字段。

**示例（无参）**：
```json
{"jsonrpc":"2.0","id":1,"method":"get_state"}
```
**示例（带命名参数）**：
```json
{"jsonrpc":"2.0","id":2,"method":"exec_shell","params":{"cmd":"uname -a"}}
```

## 1.3 Response 结构

```json
// 成功
{
  "jsonrpc": "2.0",
  "id": <同 request 的 id>,
  "result": <任意 JSON 值>
}
// 失败
{
  "jsonrpc": "2.0",
  "id": <同 request 的 id>,
  "error": {
    "code": <int>,
    "message": "<string>",
    "data": <可选, 省略时不序列化>
  }
}
```

- `result` 与 `error` 二选一（互斥），在同一响应顶层（`payload` 用 `#[serde(flatten)]`）。
- `id` 与请求的 `id` 一致，调用方据此配对。守护进程**不会**为 notification 产生响应。
- `error.code` 是整数，见 [`errors.md`](errors.md)。

**示例（成功）**：
```json
{"jsonrpc":"2.0","id":2,"result":{"exit":0,"stdout":"Linux ...\n","stderr":""}}
```
**示例（失败）**：
```json
{"jsonrpc":"2.0","id":2,"error":{"code":-32002,"message":"command matches deny pattern: mkfs"}}
```

## 1.4 Notification 结构

```json
{
  "jsonrpc": "2.0",
  "method": "<telemetry | alert>",
  "params": { ... }
}
```

- **无 `id`** 字段（fire-and-forget，调用方不应回复）。
- `params`：Named 对象。结构见 [`notifications.md`](notifications.md)。
- 调用方连接守护进程后，会**持续收到** notification，直到断开。

**示例（telemetry）**：
```json
{"jsonrpc":"2.0","method":"telemetry","params":{"timestamp":"2026-07-28T07:48:54Z","thermal":{"zones":[{"name":"thermal-cpu","tempC":62.0}]},...}}
```

## 1.5 id 配对规则（调用方实现要点）

调用方发 Request 后，可能**先收到 notification 再收到响应**（守护进程异步推送 telemetry）。实现时：
1. 为每个 Request 生成唯一 `id`。
2. 收 Response 时**比对 `id`**：匹配才采纳为该 Request 的结果；不匹配的迟到响应丢弃。
3. 收 Notification 时**不要**当作响应，转发给上层或跳过。

`client` crate 的 `Client::call` 已实现此逻辑。

## 1.6 序列化行为细节

- `params`/`error.data` 为 `None` 时**不序列化**该字段（`skip_serializing_if`）。
- `Notification` 无 `id` 字段（不会被序列化出 `"id":null`）。
- 数字 `id` 是整数（`i64`）；若调用方发字符串 `id`，原样回带。

## 1.7 消息大小限制

单条消息（一行 JSON）最大 **4 MiB**（`MAX_MESSAGE_BYTES`，`crates/shared/src/protocol/mod.rs:19`）。
超限的行，守护进程返回 `TransportError::TooLarge` 并断开该连接。调用方应避免发送超大消息，
守护进程也应保证 `telemetry` 推送的 `StateSnapshot` 不超此限（当前远小于此）。
