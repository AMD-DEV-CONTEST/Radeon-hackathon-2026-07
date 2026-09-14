# 1. 代码规范

1. 注释要求：生成代码文件（Rust 源码、构建脚本、部署文件等）顶部都要有总体功能介绍说明的注释。Rust 文件用 `//!` 模块级文档注释说明本模块职责与依赖方向；每个 `pub` 的 struct/enum/trait/fn/字段/常量都要有 `///` 文档注释；业务逻辑要对核心流程有 `//` 行内注释说明。注释用中文。
2. 后端代码严格按照 DDD 分层管理（crate 即层），前端代码严格按照 FSD 方式组织。
3. 具体的实现方法要有详尽清晰的注释；错误处理按层分包：各层用自己的 `thiserror::Error` 枚举定义错误（如 `PortError`/`ProtocolError`/`ClientError`/`TransportError`），infra 层把硬件/IO 错误包裹成 infra 错误后再上抛；`bin`/`main`/`bootstrap` 装配代码用 `anyhow::Result` 聚合。
4. 模块根文件（`lib.rs`/`mod.rs`）只做模块声明（`pub mod`）与便捷重导出（`pub use`），不允许包含业务逻辑。需要导出的符号由模块根统一 `pub use` 暴露，下游直接从 crate 根导入（如 `use shared::StateSnapshot`）。
5. 测试三层分明：单元测试写在被测源码文件内的 `#[cfg(test)] mod tests` 中；集成测试放在 `crates/<crate>/tests/` 下，命名格式为 `*_integration_tests.rs`；E2E 测试放在 `crates/testkit/tests/` 下，命名格式为 `*_e2e_tests.rs`。需要假 infra 时注入 `testkit::common` 的 Fake 实现。

## 1.1 DDD 分层（crate 即层）

`crates/` 顶层目录直接对应 DDD 层，依赖方向单向向下、无环：

| crate | DDD 层 | 职责 |
|------|------|------|
| `shared` | shared | `protocol`（JSON-RPC 信封 + StateSnapshot）+ `ports`（Collector/SysfsReader/ProcReader/HrutGateway/ShellRunner trait）。无 IO，无 tokio。 |
| `infra` | infra | `transport` 子模块（TCP/Unix/Serial/Stub + NDJSON 帧）+ sysfs/proc/hrut/statvfs/shell 真实实现。 |
| `domain` | domain | `collectors`（6 个采集器）+ StateService/AlertService/TelemetryService/CommandPolicy（纯策略）。零 IO，经 ports 注入读取。 |
| `application` | application | RpcDispatcher/CollectionOrchestrator/SessionService/AuditLog 用例编排。 |
| `client` | api 共享 | `Client` + `ClientBuilder`（id 匹配 + 超时 + 重连），CLI/HTTP/WS 复用。 |
| `daemon` | bootstrap | `build_production_app`/`build_test_app` DI 装配 + 监听 + 优雅退出。 |
| `api-cli` | api | `sophonctl` bin（本地 Unix + 远程 TCP `--host`）。 |
| `api-http` | api | `probe-http-gateway` bin（REST 网关）。 |
| `api-ws` | api | `probe-ws-outbound` bin（WebSocket 出站）。 |
| `testkit` | test | `common`（FakeReader/fixtures）+ E2E 测试。 |

依赖方向：`shared → infra → domain → application → daemon`；`client` 基于 `shared`+`infra`；`api-*` 基于 `client`。禁止反向依赖与环依赖。

# 2. 其他

1. 生成 markdown 文件的标题要有序号，例如 1、2.1、3.3.1。
2. 构建与测试：`cargo build --release`（产物在 `target/release/`）；`cargo test --workspace` 跑全部测试；`cargo clippy --workspace --all-targets -- -D warnings` 保持零警告。
3. **全量自动化测试**：执行 `./scripts/full_test.sh`。该脚本一次性跑：`cargo check --workspace --all-targets` → `cargo clippy --workspace --all-targets -- -D warnings` → `cargo test --workspace --all-targets --no-fail-fast` → `cargo build --release --bins`，任一阶段失败即以非零退出码退出。脚本用 `--no-fail-fast`（单个失败也跑完所有测试，确保都跑一遍，不跳过）、`--all-targets`（含测试目标/bench/bin，无遗漏）、并行（crate 间并行、单 crate 内多线程并行；有 `cargo-nextest` 时自动切到 nextest 获得更细并行）。
4. **所有任务完成后必须跑全量测试**：每完成一个功能/重构/修复任务，都要执行 `./scripts/full_test.sh`，必须全量测试全绿（退出码 0）才算任务完成；不允许跳过任何测试、不允许只跑部分 crate、不允许 `#[ignore]` 跳过（本项目不得引入 `#[ignore]`，除非有平台门控 `#[cfg(target_os=...)]` 并在脚本注释里说明）。
5. **编译与部署**：脚本在 `deploy/scripts/`，文档在 `deploy/docs/`（`build.md` 编译、`deploy.md` 部署、`README.md` 总览）。
   - **编译**（开发机交叉编译到 aarch64，推荐路径）：`./deploy/scripts/build-release.sh`。脚本流程：`rustup target add aarch64-unknown-linux-gnu` → 跑 `./scripts/full_test.sh` 确保全绿 → `cargo zigbuild --release --target aarch64-unknown-linux-gnu --bin ...`（Mac 用 zigbuild 免配交叉链接器，需 `cargo install cargo-zigbuild` + `brew install zig`；无则回退 `cargo build`）→ 产物在 `target/aarch64-unknown-linux-gnu/release/{probe-daemon,sophonctl,probe-http-gateway,probe-ws-outbound}`。板上直编见 `deploy/docs/build.md`「板上直接编译」（用 tuna 镜像加速 rustup/crates）。
   - **部署**（开发机→板子一键）：`./deploy/scripts/deploy-to-board.sh <board-host>`（如 `x5-root`）。脚本流程：scp 二进制+`config/config.toml`+`systemd/probe-daemon.service`+`install-on-board.sh` 到板子 `/tmp/rdk-sophon-deploy/` → 远程 `sudo bash install-on-board.sh`（装二进制到 `/usr/local/bin/`、配置到 `/etc/probe-daemon/config.toml`、unit 到 `/etc/systemd/system/`、建 `probe` 用户、备 `/var/log/probe-daemon` 与 `/run/probe-daemon`）→ `systemctl daemon-reload` + `enable --now probe-daemon` → 验证 `ss -lnt | grep 7777`。Mac 验证：`sophonctl --host <board-ip>:7777 state`。
   - **systemd 服务**：unit 源 `systemd/probe-daemon.service`，`Type=simple`+`Restart=on-failure`+`User=probe`+`RuntimeDirectory=probe-daemon`+硬化（`ProtectSystem=strict`/`NoNewPrivileges`/无 capability）。控制：`systemctl start/stop/restart/enable/disable/status probe-daemon`，日志 `journalctl -u probe-daemon -f`，审计 `journalctl -u probe-daemon | grep audit`。
   - **升级**：重跑 `build-release.sh` + `deploy-to-board.sh`（覆盖二进制+配置+unit，`daemon-reload`+`restart`）。**回滚**：板子 `cp /usr/local/bin/probe-daemon.prev`（升级前备份），见 `deploy/docs/deploy.md`。
   - **安全**：生产 `[shell] enabled = false`（默认即 false，启用等于远端 root）；TCP 7777 当前明文，生产绑内网或前置 SSH 隧道/mTLS（待补）；Unix socket 权限 0600 由 systemd RuntimeDirectory 控制。
6. 依赖管理用 cargo：workspace 级依赖声明在根 `Cargo.toml` 的 `[workspace.dependencies]`，各 crate 在自己的 `Cargo.toml` 用 `workspace = true` 引用；新增依赖用 `cargo add <pkg>`，不要手动编辑锁文件。edition 统一 2021。
7. **文档与契约（高优先级）**：
   - **设计文档**放 `docs/design/`，按 crate 分文件（`shared.md`/`infra.md`/`domain.md`/`application.md`/`client.md`/`daemon.md`/`api-and-testkit.md`），入口 `docs/README.md` + `overview.md`。设计文档讲内部实现、模块、关键决策、约束。
   - **对外契约文档**放 `docs/contracts/`，按**协议**分目录（`jsonrpc/`/`http/`/`cli/`/`transport/`），每协议内按**关注点**分多文件（如 `jsonrpc/` 下 `envelope.md`/`methods.md`/`notifications.md`/`errors.md`/`data-model.md`/`examples.md`），不要把太多东西堆一个文件。入口 `docs/contracts/README.md`。
   - **契约必须真实可用、好理解、全面**：契约文档是外部调用方与我们交互的**唯一依据**，外部依赖它选型、构造请求、解析响应、处理错误。失真或不可用的契约等于让外部集成失败，是高优先级 bug。
   - **写文档必须基于代码事实**：所有结论附 `源码: file:line` 引用（如 `crates/application/src/rpc_dispatcher.rs:60`），不得凭记忆编造；字段名/类型/错误码/路由等必须与代码一致，包含 serde rename（camelCase）、`skip_serializing_if` 省略规则、默认值、触发条件。
   - **改代码必须同步改契约**：任何对外接口（RPC 方法/参数/返回结构、StateSnapshot 字段、错误码、HTTP 路由、CLI 子命令、config 字段、传输帧格式）变更，必须同时更新对应契约文档与设计文档。契约与代码不一致时以代码为准，但视为缺陷须立即修正。
   - **写文档后必须跑全量测试**：`./scripts/full_test.sh` 全绿才算完成，确保文档描述的接口与代码实际行为一致。
   - 契约文档要包含可复现的**示例**（请求/响应、curl、时序），外部可直接照抄验证。

# 3. Git 提交规范

格式：`<type>(<scope>): <描述>`

**type 类型：**
- `feat` — 新功能
- `fix` — 修复 bug
- `refactor` — 重构（不改变功能）
- `style` — 代码格式/风格调整
- `perf` — 性能优化
- `docs` — 文档变更
- `test` — 测试相关
- `chore` — 构建/部署/工具变更

**scope 范围：**
- `shared` — 共享底座（protocol + ports）
- `infra` — 基础设施层（transport + 硬件读取 + shell）
- `domain` — 领域层（collectors + 领域服务 + 策略）
- `application` — 应用层（分发/编排/会话/审计）
- `client` — 共享 RPC 客户端
- `daemon` — bootstrap DI 装配 + main
- `api-cli` — sophonctl CLI
- `api-http` — HTTP/REST 网关
- `api-ws` — WebSocket 出站
- `testkit` — 测试公共工具 + E2E
- `protocol` — JSON-RPC 协议/快照类型（shared 子模块）
- `transport` — 传输适配器（infra 子模块）
- `collectors` — 硬件采集器（domain 子模块）
- `repo` — workspace 级变更（根 Cargo.toml/锁文件/release profile）
- `deploy` — 编译与部署（deploy/scripts 编译部署脚本、deploy/docs 文档、systemd unit、config）
- `docs` — 设计文档（docs/）
- `contracts` — 对外契约文档（docs/contracts/）

**示例：**
```
feat(domain/collectors): 新增 BPU 采集器
fix(infra/transport): 修复 TCP 适配器读帧超时未重试
refactor(application): 重构 RPC 分发器用例编排
test(daemon): 补充 exec_shell 集成测试
chore(repo): 配置 workspace 依赖与 release profile
docs(domain): 更新 domain crate 设计文档
contracts(jsonrpc): 新增 get_power 方法契约并补示例
chore(deploy): 增加交叉编译与一键部署脚本
```

# 4. 要点

1. 工作完总结时，分几个点，每个点要有 1. 2. 3. 这样的数字序号前缀，方便用户读取。
2. 每个任务完成后必须执行 `./scripts/full_test.sh` 并确认全量测试全绿（退出码 0）才算完成；并行跑、不跳过、所有 crate 的单元/集成/E2E 都要过。若全量测试失败，不得视为任务完成，必须修复到全绿。
3. 任何对外接口（RPC 方法/字段/错误码/HTTP 路由/CLI/config/传输帧）变更，**必须同步更新 `docs/contracts/` 对应契约文档与 `docs/design/` 设计文档**，并附可复现示例。契约文档是外部与我们交互的唯一依据，必须真实可用、好理解、全面——失真或缺失等于让外部集成失败。
4. 部署脚本（`deploy/scripts/`）或 systemd unit（`systemd/`）或配置默认值变更，**必须同步更新 `deploy/docs/` 对应文档**（`build.md`/`deploy.md`），并跑 `./scripts/full_test.sh`；改了二进制名/产物路径/安装路径要同步改 `build-release.sh`/`deploy-to-board.sh`/`install-on-board.sh` 三者与 `deploy/docs/deploy.md`。
