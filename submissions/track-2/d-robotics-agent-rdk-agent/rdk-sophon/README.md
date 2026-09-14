# rdk-sophon

RDK 开发板的长驻硬件探针服务。它将板端硬件状态上报给开发机，并接受远端命令；
支持多种传输通道（网络 / USB 网络共享 / 串口 / SSH 隧道 / 云端），同时提供板端本地 CLI。

## 1. 设计概要

板端运行单个守护进程。它持有一份共享的 `StateSnapshot`，由采集器按周期刷新，
并在所有传输通道上暴露同一套 JSON-RPC 2.0 接口。三种上报模式共享同一份快照：
周期性遥测推送、按需拉取、阈值告警。命令默认为结构化 RPC（`get_thermal`、`exec_shell` 等）；
原始 shell 是显式启用、可审计、受黑名单约束的应急通道，默认关闭。

## 2. 工作区结构（DDD 分层，crate 即层）

`crates/` 顶层目录名直接对应 DDD 层，打开即见分层：

| crate 目录 | DDD 层 | 内含 | 职责 |
|------|------|------|------|
| `shared` | shared | `protocol` + `ports` 子模块 | JSON-RPC 信封 + 状态快照 + 端口 trait。无 IO，无 tokio。 |
| `infra` | infra | `transport` 子模块 + sysfs/proc/hrut/statvfs/shell | 传输适配器（TCP/Unix/Serial/Stub）+ 真实硬件读取 + shell 执行。 |
| `domain` | domain | `collectors` 子模块 + state/alert/telemetry/policy | 6 个采集器 + 领域服务 + `CommandPolicy`（纯策略）。 |
| `application` | application | rpc_dispatcher/orchestrator/session/audit | 用例编排：分发、采集编排、会话驱动、审计。 |
| `client` | api 共享 | Client + builder | `Client`（id 匹配 + 超时 + 重连），CLI/HTTP/WS 共用。 |
| `daemon` | bootstrap | lib（`build_*_app`）+ bin（main） | 依赖注入装配 + 监听 + 优雅退出。 |
| `api-cli` | api | sophonctl bin | CLI，本地 Unix + 远程 TCP（`--host`）。 |
| `api-http` | api | probe-http-gateway bin | REST 网关：`/state`、`/thermal`、`/exec` 等。 |
| `api-ws` | api | probe-ws-outbound bin | WebSocket 出站：板子主动外连云端 broker。 |
| `testkit` | test | `common` 子模块 + tests/ | FakeReader/fixtures + E2E 测试。 |

依赖方向单向向下，无环：`shared → infra → domain → application → daemon`；
`client` 基于 `shared`+`infra`；`api-*` 基于 `client`。

## 3. 构建

```sh
cargo build --release
# 产物位于 target/release/{probe-daemon,sophonctl,probe-http-gateway,probe-ws-outbound}
```

交叉编译到板端（aarch64），需先配置目标：

```sh
rustup target add aarch64-unknown-linux-gnu
cargo build --release --target aarch64-unknown-linux-gnu
```

## 4. 运行

```sh
# 守护进程（默认参数已足够；可用命令行参数或 /etc/probe-daemon/config.toml 覆盖）
sudo ./target/release/probe-daemon --config config/config.toml

# 本地 CLI
./target/release/sophonctl state
./target/release/sophonctl thermal
./target/release/sophonctl exec uname -a      # 需启用 [shell]

# 远程 CLI（开发机直连板子）
./target/release/sophonctl --host <board-ip>:7777 state
./target/release/sophonctl --host <board-ip>:7777 exec uname -a

# HTTP/REST 网关（板端起，开发机 curl）
./target/release/probe-http-gateway --listen 0.0.0.0:8080 --daemon-sock /run/probe-daemon/probe.sock
curl http://<board-ip>:8080/state
curl -X POST http://<board-ip>:8080/exec -H 'Content-Type: application/json' -d '{"cmd":"uname -a"}'

# WebSocket 出站（板子主动连云端 broker）
./target/release/probe-ws-outbound --broker-url ws://broker.example.com/board-1
```

## 5. 远程连接（开发机）经 TCP

板端默认监听 `0.0.0.0:7777`。在局域网内的笔记本、通过 USB 网络共享（RNDIS）、
或通过 SSH 隧道（`ssh -L 7777:localhost:7777 board`），发送换行分隔的 JSON-RPC：

```sh
echo '{"jsonrpc":"2.0","id":1,"method":"get_state"}' | nc <board-ip> 7777
```

连接期间，守护进程每隔 `telemetry.interval_secs` 推送一次 `telemetry` 通知，
并在阈值越界时发出 `alert` 通知。

## 6. 配置

见 [`config/config.toml`](config/config.toml)。关键配置项：

- `tcp.bind`、`unix.path`、`[serial]` — 要启用的传输通道。
- `telemetry.interval_secs` — 推送周期；`0` 表示仅拉取。
- `shell.enabled` — **默认关闭**。启用后允许执行任意 shell；内置黑名单（`mkfs`、`rm -rf /` 等）始终生效，且配置中的模式只会收紧黑名单。
- `alerts.temp_c`、`alerts.disk_usage_pct` — 阈值。

## 7. systemd

将 [`systemd/probe-daemon.service`](systemd/probe-daemon.service) 放入
`/etc/systemd/system/`，将二进制安装到 `/usr/local/bin/probe-daemon`，
将配置放到 `/etc/probe-daemon/config.toml`，然后：

```sh
sudo systemctl enable --now probe-daemon
```

## 8. RPC 方法参考

| method | params | returns |
|--------|--------|---------|
| `ping` | — | `{pong, ts}` |
| `get_state` | — | 完整 `StateSnapshot` |
| `get_thermal` / `get_cpu` / `get_memory` / `get_disk` / `get_net` / `get_bpu` | — | 对应片段 |
| `refresh_state` | — | 立即触发一次采集 |
| `exec_shell` | `{cmd: string}` | `{exit, stdout, stderr}`（受策略约束） |

通知（服务端 → 客户端，无需回复）：`telemetry`、`alert`。

## 9. 测试（三层）

```sh
cargo test --workspace                # 62 个测试全过
cargo clippy --workspace --all-targets -- -D warnings   # 零警告
```

- **单元测试**（各 crate 内 `#[cfg(test)]`）：protocol 帧编解码、transport NDJSON、
  domain CommandPolicy（deny/enabled）、AlertService 阈值判定、collectors 用 FakeReader 解析。
- **集成测试**（`crates/daemon/tests/`）：用 `daemon::build_test_app` + StubTransport，
  跑 client→dispatcher→domain→collector 全链路，不起真实端口。覆盖 ping/get_state/exec_shell（deny/disabled/正常）与 telemetry/alert 推送。
- **E2E 测试**（`crates/testkit/tests/`）：真实 TCP/Unix 端口 + 真实 transport。
  daemon 注入 FakeReader（Mac 上可跑）但走真实网络栈。覆盖 ping/get_state/exec deny/超时/telemetry 推送。

采集器通过 `ports::SysfsReader`/`ProcReader`/`HrutGateway` 注入，Mac 上用 `FakeReader` 测解析逻辑，
板子上用 `RealReader` 读真实 `/proc`/`/sys`，无需改动业务代码。

## 10. 进度（MVP）

- [x] DDD 分层：crate 即层，`crates/` 顶层 10 目录（shared/infra/domain/application/client/daemon/api-cli/api-http/api-ws/testkit）。
- [x] JSON-RPC 2.0 协议、NDJSON 帧封装。
- [x] TCP、Unix socket、串口传输通道。
- [x] 温度/CPU/内存/磁盘/网络/BPU 采集器（Linux sysfs/proc 路径，trait 注入可测）。
- [x] RPC 方法表 + 可审计、受黑名单约束的 shell 应急通道（策略与执行分离）。
- [x] 周期性遥测推送 + 阈值告警。
- [x] 四种 API 形式：`sophonctl`（本地+远程）、Rust `client` 库、HTTP/REST 网关、WebSocket 出站。
- [x] 三层测试（单元 + 集成 + E2E），62 个测试全过，clippy 零警告。
- [ ] TLS（mTLS）— trait 已就绪，待补适配器。
- [ ] MQTT 适配器（可选）。
- [ ] 客户端级鉴权 / 限流。
