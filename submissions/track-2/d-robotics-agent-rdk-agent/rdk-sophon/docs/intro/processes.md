# 2. 进程模块视角：起几个进程、关系如何

> 本文面向**想快速了解 rdk-sophon 部署形态**的外部读者（人或 AI）。
> 不讲功能上分几块（那是 [`functional.md`](functional.md) 的事），只讲**这个系统跑起来是几个进程、各自什么角色、怎么协作**。
> 所有结论附源码引用。

## 2.1 是几个进程？

**4 个独立二进制，但不一定要 4 个进程。** 最小部署 1 个进程，全功能最多 3 个常驻进程。

| 二进制 | 是否常驻进程 | 角色定位 | 必须起吗 |
|--------|------------|---------|---------|
| `probe-daemon` | **是，核心长驻** | 唯一服务端，持有状态/采集/命令执行 | **必须** |
| `sophonctl` | **否，临时命令** | 客户端工具，敲一次连一次，用完即退 | 按需（工具） |
| `probe-http-gateway` | 看需要 | 协议适配器：REST ↔ JSON-RPC | 可选 |
| `probe-ws-outbound` | 看需要 | 协议适配器：板子主动外连云端 WS | 可选 |

- 最小部署：只 `probe-daemon` 一个进程（外部用 `nc`/`sophonctl` 直连它的 TCP）。
- 全功能：`probe-daemon` + `probe-http-gateway` + `probe-ws-outbound` 共 3 个常驻进程。
- `sophonctl` 不算进程——它是 fork 一次执行完就退的工具（像 `kubectl` 之于 kubelet）。

## 2.2 四者关系图

```
                  开发机 / 外部
                       │
       ┌───────────────┼──────────────────┐
       │ nc / sophonctl  │ curl / 浏览器     │ 云端 broker
       │ (TCP 7777)    │ (HTTP 8080)       │ (WebSocket)
       ▼                ▼                   ▲
  ┌─────────┐    ┌──────────────┐    ┌──────────────┐
  │ probe-  │    │ probe-http-  │    │ probe-ws-   │
  │ daemon  │◄───┤ gateway      │    │ outbound ───┘
  │ (核心)  │unix│ (REST 翻译)  │    │ (主动外连云)
  └─────────┘    └──────────────┘    └──────────────┘
  TCP/Unix/        它是 daemon         它是 daemon
  Serial 监听      的 Unix 客户端       的 Unix 客户端
```

核心：**`probe-daemon` 是唯一的服务端，其它三个要么是它的客户端，要么是工具。**

## 2.3 各进程详解

### 2.3.1 probe-daemon（守护进程，核心，必须）

**唯一真正"服务端"。** 职责：
- 监听 TCP `0.0.0.0:7777`、Unix socket `/run/probe-daemon/probe.sock`、可选 Serial（`crates/daemon/src/main.rs:49-86`）。
- 持有共享的 `StateSnapshot`，跑采集循环周期刷新（`crates/daemon/src/bootstrap.rs:spawn_collect_loop`）。
- 处理所有 RPC：拉状态、`exec_shell`、推送 telemetry/alert。
- systemd 常驻，崩溃自动重启（`Restart=on-failure`）。

它是**数据源和命令执行者**——HTTP 网关和 WS 出站自己不存状态、不采集，只翻译转发给它。

### 2.3.2 sophonctl（CLI，工具，按需）

**客户端工具，不是服务。** 每次敲命令 fork 一次：
- 本地：`ClientBuilder::unix(socket)` 走 Unix socket 连 daemon。
- 远程：`--host ip:port` 走 TCP 连 daemon（`crates/api-cli/src/main.rs:54-58`）。

拿完结果就退出，无常驻进程。相当于 `kubectl`/`docker` 之于 kubelet/dockerd。和 daemon 走**同一套 JSON-RPC 协议**，子命令映射到 RPC method（`state`→`get_state`、`exec`→`exec_shell` 等）。

### 2.3.3 probe-http-gateway（REST 网关，可选）

**协议适配器进程。** 只做一件事：把 HTTP 请求翻译成 JSON-RPC 转发给 daemon，响应翻译成 HTTP JSON。
- 它是 **daemon 的 Unix 客户端**（`ClientBuilder::unix(daemon_sock)`）+ **对外的 HTTP 服务端**（监听 `0.0.0.0:8080`）。
- **不推送** notification（HTTP 是同步请求/响应，无法主动推）——要推送走 JSON-RPC 直连或 WS 出站。
- 源码：`crates/api-http/src/routes.rs`，路由如 `GET /state`→`get_state`、`POST /exec`→`exec_shell`。

只有"想要 curl/浏览器/REST 脚本能访问"时才起它。

### 2.3.4 probe-ws-outbound（WS 出站，可选）

**协议适配器进程，板子主动外连云端。** NAT 后或云端统一管多板时用：
- 作为 **daemon 的 Unix 客户端**连进去（`UnixStream::connect`），订阅 daemon 的 broadcast，收 telemetry/alert notification。
- 转成 WebSocket 文本帧，主动外连云端 broker（`tokio_tungstenite::connect_async`）。
- 断线指数退避重连（`crates/api-ws/src/reconnect.rs`）。
- **不用 `client::Client`**（要收 notification 而非 request/response），直接 `UnixTransport::recv`。

只有"云端管多板"场景才起它。

## 2.4 进程间通信方式

三个常驻进程之间**不走网络互调**，而是都通过**本地 Unix socket**连 daemon：

| 进程 | 连 daemon 的方式 | 协议 |
|------|----------------|------|
| sophonctl | Unix socket（本地）/ TCP（远程） | JSON-RPC over NDJSON |
| probe-http-gateway | Unix socket（本地） | JSON-RPC over NDJSON |
| probe-ws-outbound | Unix socket（本地） | JSON-RPC over NDJSON（收 notification） |

daemon 是**唯一的服务端**，其它都是它的 Unix 客户端。授权由 socket 文件权限 0600 控制（`crates/daemon/src/main.rs:65-68`）。

## 2.5 典型部署形态对照

| 场景 | 起哪些进程 | 说明 |
|------|-----------|------|
| 最小：开发机直连调试 | `probe-daemon` | sophonctl 在开发机当工具，连 daemon TCP |
| 生产：内网监控 | `probe-daemon`（+ `probe-http-gateway` 若要 REST） | systemd 起 daemon；要 curl/Grafana 抓取就加网关 |
| 云端管多板 | `probe-daemon` + `probe-ws-outbound` | 板子主动外连云端 broker 推 telemetry |
| 全功能 | `probe-daemon` + `probe-http-gateway` + `probe-ws-outbound` | 3 个常驻进程，sophonctl 按需用 |

## 2.6 为什么这样设计（不把 HTTP/WS 塞进 daemon）

1. **核心只一个**：daemon 是状态和逻辑的唯一来源，数据不分散，所有通道最终汇到它。
2. **HTTP/WS 是可选适配器**：不是所有场景都要 REST 或云端。拆成独立进程，需要哪个起哪个，不占资源、不增加攻击面。塞进 daemon 会让核心臃肿、强依赖 axum/tungstenite。
3. **CLI 是工具不是服务**：sophonctl 走同一套协议但是"用完即走"，不该常驻。
4. **故障隔离**：HTTP 网关挂了不影响 daemon 的 TCP/Unix 服务；WS 出站网络抖断不影响本地 CLI。各进程职责单一。

## 2.7 一句话总结

`probe-daemon` 是**唯一必起的常驻服务端**；`probe-http-gateway` 和 `probe-ws-outbound` 是**按需起的协议适配器进程**（REST 和云端场景分别用）；`sophonctl` 是**一次性的客户端工具**（不常驻）。四个二进制，默认只有 daemon 一个进程在跑。

## 2.8 生命周期与启停

- **daemon**：systemd 管理，`systemctl start/stop/restart/enable probe-daemon`，崩溃自动重启，日志 `journalctl -u probe-daemon`。详见 [`../../deploy/docs/deploy.md`](../../deploy/docs/deploy.md)。
- **http-gateway / ws-outbound**：当前手动起（未提供独立 systemd unit，按需加），命令见 [`../../deploy/docs/deploy.md`](../../deploy/docs/deploy.md)「部署 HTTP 网关 / WS 出站」。
- **sophonctl**：无生命周期，敲一次跑一次。

## 2.9 想深入了解

- **功能上分几块**（采集/分发/告警等）：[`functional.md`](functional.md)。
- **对外接口契约**（RPC 方法/字段/错误码）：[`../contracts/`](../contracts/)。
- **各 crate 内部设计**：[`../design/`](../design/)。
- **编译部署脚本**：[`../../deploy/`](../../deploy/)。
