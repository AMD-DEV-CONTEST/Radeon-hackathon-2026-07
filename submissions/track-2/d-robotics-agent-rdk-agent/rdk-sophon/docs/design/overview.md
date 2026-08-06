# 1. rdk-sophon 设计总览

> 本文档面向**维护者**，描述各 crate 的内部设计与依赖关系。
> 对外接口契约见 `../contracts/` 目录（面向外部调用方）。

## 1.1 项目定位

rdk-sophon 是跑在 RDK 开发板上的长驻硬件探针守护进程。板端运行单个 `probe-daemon`，
持有共享的 `StateSnapshot`，由采集器周期刷新，在所有传输通道上暴露同一套
JSON-RPC 2.0 接口。三种上报模式共享同一份快照：周期遥测推送、按需拉取、阈值告警。
命令默认为结构化 RPC；原始 shell 是显式启用、可审计、受黑名单约束的应急通道，默认关闭。

## 1.2 分层（crate 即层）

`crates/` 顶层目录名直接对应 DDD 层，依赖方向单向向下、无环：

```
shared（底座：protocol + ports）
   ▲
infra（传输 + 真实硬件读取 + shell 执行）
   ▲
domain（采集器 + 领域服务 + 策略，经 ports 注入读取）
   ▲
application（用例编排：分发 / 采集编排 / 会话 / 审计）
   ▲
daemon（bootstrap：DI 装配 + 监听 + 优雅退出）
```

`client` 基于 `shared`+`infra`，供 `api-cli`/`api-http`/`api-ws` 三种入口复用。
`testkit` 提供假 infra 与 E2E 测试。

## 1.3 crate 清单

| crate | DDD 层 | 职责 | 设计文档 |
|------|------|------|------|
| `shared` | shared | JSON-RPC 信封 + 状态快照 + 端口 trait。无 IO，无 tokio。 | [shared.md](shared.md) |
| `infra` | infra | 传输适配器 + 真实硬件读取 + shell 执行。 | [infra.md](infra.md) |
| `domain` | domain | 6 个采集器 + 领域服务 + `CommandPolicy`。 | [domain.md](domain.md) |
| `application` | application | `RpcDispatcher`/`CollectionOrchestrator`/`SessionService`。 | [application.md](application.md) |
| `client` | api 共享 | `Client` + `ClientBuilder`。 | [client.md](client.md) |
| `daemon` | bootstrap | `build_*_app` DI + 监听 + 优雅退出。 | [daemon.md](daemon.md) |
| `api-cli` | api | `sophonctl`（本地 + 远程 CLI）。 | [api.md](api.md) |
| `api-http` | api | `probe-http-gateway`（REST 网关）。 | [api.md](api.md) |
| `api-ws` | api | `probe-ws-outbound`（WebSocket 出站）。 | [api.md](api.md) |
| `testkit` | test | 假 infra + fixtures + E2E。 | [testkit.md](testkit.md) |

## 1.4 依赖图

```
                shared ◄── (0 内部依赖，纯底座)
                   ▲
            ┌──────┴──────┐
            │             │
          infra         domain ◄── (domain 仅用 infra::statvfs_of)
            ▲             ▲
            └──────┬──────┘
                   │
              application
                   ▲
            ┌──────┴──────────┐
            │                 │
          client            daemon(lib)
            ▲                 ▲
   ┌────────┴─────────┬──────┴──────┐
   ▼        ▼          ▼             ▼
api-cli  api-http   api-ws       daemon(bin)

testkit ──► daemon(lib), client, application, domain, infra, shared
```

禁止反向依赖与环依赖。

## 1.5 关键设计决策

1. **crate 即层**：目录名 = DDD 层名，打开 `crates/` 即见分层。子模块用 `mod` 组织（如 `domain/src/collectors/`、`infra/src/transport/`）。
2. **采集器可注入 trait**：`domain::collectors` 构造期注入 `SysfsReader`/`ProcReader`/`HrutGateway`，Mac 上用 `testkit` 的 Fake 测解析逻辑，板子上用 `infra` 的 Real 读真实硬件，业务代码不变。
3. **策略与执行分离**：`domain::CommandPolicy`（纯策略 deny/timeout，零 IO）与 `infra::RealShellRunner`（spawn sh）拆开，策略可单测不碰进程。
4. **daemon 拆 lib+bin**：`daemon` 的 `[lib]` 暴露 `build_test_app(fake_readers)`，让 E2E 注入假 infra 但走真实网络栈。
5. **传输中立**：`Transport` trait 是 dispatcher 与物理层唯一边界，所有传输适配器只解决"帧边界"，dispatcher 不知消息来自哪种传输。
6. **单一数据源**：拉取（`get_state`）与推送（`telemetry`）读同一份 `StateSnapshot`，避免数据漂移。

## 1.6 阅读顺序建议

- 想理解对外接口：直接看 `../contracts/`。
- 想理解内部架构：先读本文件，再按 `shared → infra → domain → application → daemon` 顺序读各 crate 设计文档。
- 想加一个新采集器：读 `docs/design/domain.md` 的"新增采集器"节。
- 想加一个新 RPC 方法：读 `docs/design/application.md` 的"新增方法"节 + `../contracts/jsonrpc/methods.md`。
