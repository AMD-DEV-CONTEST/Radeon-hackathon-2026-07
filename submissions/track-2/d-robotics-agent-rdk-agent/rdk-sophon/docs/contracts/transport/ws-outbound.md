# 3. WebSocket 出站契约

> 板子主动外连云端 WebSocket broker，把守护进程的 telemetry/alert notification 转发到云端。
> 独立二进制 `probe-ws-outbound`。
> 实现源码：`crates/api-ws/src/`

## 3.1 用途

板子在 NAT 后或需要云端统一管理时，板子**主动外连**云端 broker。
`probe-ws-outbound` 作为本地 daemon 的 Unix 客户端，订阅 daemon 的 telemetry/alert broadcast，把 notification 转成 WS 文本帧发云端。

## 3.2 启动参数

```
probe-ws-outbound --broker-url ws://broker.example.com/board-001 \
                 --daemon-sock /run/probe-daemon/probe.sock \
                 --backoff-start 1 \
                 --backoff-max 30
```
| 参数 | 默认 | 说明 |
|------|------|------|
| `--broker-url` | 无（必填） | 云端 WebSocket URL，如 `ws://broker.example.com/board-001` |
| `--daemon-sock` | `/run/probe-daemon/probe.sock` | 本地 daemon 的 Unix socket 路径 |
| `--backoff-start` | `1`（秒） | 重连初始退避 |
| `--backoff-max` | `30`（秒） | 重连最大退避 |

## 3.3 帧格式（与 NDJSON 不同）

WebSocket 传输**不用** NDJSON 换行分隔——WS 帧自带边界，**一帧一条 JSON-RPC 文本**，无需 `\n`。
- 上行（板→云）：每条 `telemetry`/`alert` notification 序列化为 JSON 文本，作为一个 WS text 帧发送。
- 下行（云→板）：当前忽略（"未来扩展"，可扩展为云端下发指令转发给 daemon）。

编解码见 `crates/api-ws/src/codec.rs`。

## 3.4 行为

1. 连云端 broker：`tokio_tungstenite::connect_async(broker_url)`。
2. 连本地 daemon：`UnixStream::connect(daemon_sock)` + `UnixTransport`，直接 `recv`（**不用 `client::Client`**，要收 notification 而非 request/response）。
3. daemon 的 `run_session` 已用 `select!` 把 broadcast notification 转发给本连接——本进程据此收到 telemetry/alert。
4. 收到 notification → `codec::encode` 成 JSON 文本 → 通过 mpsc 喂给 WS 写任务 → 写到云端。
5. WS 读端处理 Ping/Pong/Close/控制帧；`Close` 或错则结束本次会话。

## 3.5 重连

`run_with_reconnect` 包住 `run_once`：
- 会话正常断开（broker 关闭）→ 立即重连。
- 会话异常 → 指数退避：`backoff_start` 起每次翻倍，封顶 `backoff_max`。
- 永不退出（除非 Ctrl-C）。

## 3.6 与 daemon 的关系

- **不修改 daemon**：复用 daemon 现有 `run_session` 的 broadcast 转发路径，WS 出站作为普通 Unix 客户端连进去。
- daemon 的 `Broadcaster` 容量 256，慢消费者可能 `Lagged`——`run_session` 已处理（重订阅不静默丢）。

## 3.7 安全

- WS 当前是明文 `ws://`（非 `wss://`）。生产建议云端用 TLS 终结 + 板端用 `wss://`，或加 broker 端鉴权。
- daemon 侧授权由 Unix socket 权限控制（WS 出站进程须能访问 socket）。

## 3.8 典型部署

```
板子                              云端
┌────────────────────┐          ┌──────────────┐
│ probe-daemon        │          │ broker        │
│  (Unix sock)        │          │ (ws server)   │
│      ▲              │          └──────▲───────┘
│      │ subscribe    │                 │ WS
│ probe-ws-outbound ──┼─────────────────┘ (主动外连)
└────────────────────┘
```

云端 broker 收到 telemetry/alert notification 后，可分发到多个订阅者（监控大屏、告警系统等）。
