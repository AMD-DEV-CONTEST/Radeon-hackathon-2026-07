# 2. 传输通道契约

> 守护进程支持多种传输通道，所有通道共用同一套 JSON-RPC over NDJSON 协议。
> 调用方选一种通道连守护进程即可，行为一致。
> 实现源码：`crates/daemon/src/main.rs`、`crates/infra/src/transport/`

## 2.1 通道总览

| 通道 | 默认 | 启用配置 | 帧格式 | 典型场景 |
|------|------|---------|--------|---------|
| TCP | `0.0.0.0:7777` | `[tcp].enabled` | NDJSON | 局域网/USB 网卡/SSH 隧道/云端 |
| Unix socket | `/run/probe-daemon/probe.sock` | `[unix].enabled` | NDJSON | 本地 CLI、板端进程间 |
| Serial | 不启用 | `[serial]` section 存在 | NDJSON | 调试 UART |
| WebSocket 出站 | — | 独立二进制 `probe-ws-outbound` | WS 帧文本 | 板子主动外连云端 broker |

所有传输适配器实现 `Transport` trait，dispatcher 不知消息来自哪种传输——**传输中立**。

## 2.2 TCP

- 绑定 `[tcp].bind`，默认 `0.0.0.0:7777`，可被 `--tcp-bind` 覆盖。
- 覆盖场景：网络（笔记本→板子）、USB 网络共享（RNDIS/CDC-ECM，板子多出网卡即 TCP）、SSH 隧道（`ssh -L 7777:localhost:7777 board` 转发到本地 TCP）。
- 多连接，每连接 spawn 一个 `run_session`，共用同一 dispatcher/broadcaster。
- accept 失败退避 200ms。

**SSH 隧道用法**（开发机）：
```sh
ssh -L 7777:localhost:7777 x5-root
# 然后本地连
sophonctl --host 127.0.0.1:7777 state
```

## 2.3 Unix socket

- 路径 `[unix].path`，默认 `/run/probe-daemon/probe.sock`，可被 `--unix-path` 覆盖。
- 绑定前 `remove_file` 清理旧 socket，绑定后 `set_permissions(0o600)`。
- **授权**：由 socket 路径的文件系统权限控制（0600，daemon 用户所有）。无网络层鉴权。
- 适合板端本地 CLI（`sophonctl`）、板端进程间通信。
- 多连接，同 TCP。

## 2.4 Serial / UART

- `[serial]` section 存在则启用，`path`（设备路径如 `/dev/ttyS1`）+ `baud`（如 `115200`）必填。
- 默认 8N1，读超时 250ms。如需 7E1 等需改配置/源码。
- **单连接模式**：不走 accept 循环，直接 spawn 一个 `run_session`。
- 阻塞 `serialport` crate，读在专用线程，经 `tokio::mpsc` 桥接到 async。
- 帧格式同 NDJSON——UART 发文本 JSON 行，可从 tty 直接调试。
- 打开失败仅 warn，不退出 daemon。

## 2.5 WebSocket 出站（独立二进制）

板子主动外连云端 broker，详见 [`ws-outbound.md`](ws-outbound.md)。

## 2.6 Stub（仅测试/dry-run）

内存通道，`StubTransport::pair() -> (a, b)`，a 发 b 收、b 发 a 收。仅供测试与 `--dry-run`。

## 2.7 多通道并存

守护进程可同时启用多个通道（如 TCP + Unix + Serial），各自独立 accept/spawn session，共用同一 `RpcDispatcher`/`Broadcaster`。一条通道上的 `exec_shell` 命令、`telemetry` 推送对所有已连接客户端可见（broadcast）。

## 2.8 连接生命周期

- 客户端连接 → 守护进程 spawn `run_session`。
- session 内 `tokio::select!`：读请求→dispatch→回发响应，同时转发 broadcast notification。
- 客户端断开（EOF/IO 错）→ session 结束。
- 守护进程 `ctrl_c` → `CancellationToken` 通知所有 accept 循环与采集循环退出。

## 2.9 选择建议

| 场景 | 推荐通道 |
|------|---------|
| 笔记本连板子（局域网） | TCP |
| USB 网络共享 | TCP |
| 通过 SSH 隧道 | TCP（本地端口转发） |
| 板端本地调试 | Unix socket |
| 调试 UART | Serial |
| 云端管多板 | WebSocket 出站（板子主动外连 broker） |
| 脚本/curl/浏览器 | HTTP 网关（独立二进制，REST） |
