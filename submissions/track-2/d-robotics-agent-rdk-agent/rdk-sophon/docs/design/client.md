# 6. client crate 设计文档

> DDD 层：api 共享客户端。依赖 `shared`、`infra`。
> 源码：`crates/client/`

## 6.1 职责

`client` 是 JSON-RPC 客户端库，供 `api-cli`/`api-http`/`api-ws` 三种入口与未来远程客户端复用。
封装 send/recv 循环、id 递增、**id 匹配响应**、超时、收到 notification 转发回调（不误当响应）。

## 6.2 模块结构

```
client/src/
├── lib.rs          # pub use 重导出
├── client.rs       # Client
├── builder.rs      # ClientBuilder
└── error.rs        # ClientError
```

## 6.3 Client（`client.rs`）

```rust
pub struct Client {
    transport: Mutex<Box<dyn Transport>>,
    id_counter: AtomicI64,
    default_timeout: Duration,
    on_notification: Mutex<Option<NotificationCb>>,  // type NotificationCb = Box<dyn Fn(JsonRpcMessage)+Send+Sync>
}
```

- `new(transport)`：默认超时 30s。
- `with_timeout(t) -> Self`。
- `on_notification(f)`：设置 notification 回调（WS 出站转发 telemetry 用）。
- `call(method, params) -> Result<Value, ClientError>`：默认超时。
- `call_timeout(method, params, timeout) -> Result<Value, ClientError>`。

### call 流程（`client.rs:53-97`）
1. `id = id_counter.fetch_add(1)`，构造 `Request`。
2. `transport.send(req)`。
3. 循环 `transport.recv()` 到 deadline：
   - `Response` 且 `id` 匹配 → `Ok(result)` 或 `Err(Server{code,message})`。
   - `Response` 但 id 不匹配 → 丢弃继续等（异步乱序防御）。
   - `Notification` → 转 `on_notification` 回调（若有）或跳过。
   - `Request` → 忽略（服务端不应发请求给客户端）。
4. deadline 到 → `Timeout{secs}`；`None`（连接关）→ `Closed`。

## 6.4 ClientBuilder（`builder.rs`）

- `new()` 默认超时 30s；`timeout(d) -> Self`。
- `tcp(addr) -> Result<Client>`：`TcpStream::connect` + `TcpTransport`。
- `unix(path) -> Result<Client>`：`UnixStream::connect` + `UnixTransport`。
- `stub(t: StubTransport) -> Client`：测试用。

## 6.5 ClientError（`error.rs`）

```rust
pub enum ClientError {
    Transport(String),
    Protocol(String),
    Server { code: i32, message: String },
    Timeout { secs: u64 },
    Closed,
}
```
HTTP 网关据此映射 HTTP 状态码（见 `../contracts/http/errors.md`）。

## 6.6 设计约束

- client **不得**依赖 `application`/`daemon`（仅作为 RPC 调用方）。
- **必须**校验响应 id（防止乱序拿错响应）。
- 收到 notification **不得**当响应（必须跳过或转回调）。

## 6.7 复用

| 入口 | 用法 |
|------|------|
| `api-cli`（sophonctl） | `ClientBuilder::tcp(host)` 或 `unix(socket)` |
| `api-http`（probe-http-gateway） | `ClientBuilder::unix(daemon_sock)`，handler 调 `client.call` |
| `api-ws`（probe-ws-outbound） | 不用 Client（要收 notification 而非 request/response），直接用 `UnixTransport::recv` |
