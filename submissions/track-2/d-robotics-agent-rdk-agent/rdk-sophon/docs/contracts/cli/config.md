# 2. config.toml 配置契约

> 守护进程 `probe-daemon` 的 TOML 配置文件契约。
> 实现源码：`crates/daemon/src/config.rs`，示例 `config/config.toml`

## 2.1 加载

- 默认路径 `/etc/probe-daemon/config.toml`，可 `--config <path>` 覆盖。
- **配置缺失不阻塞启动**：`Config::load` 失败回退 `Config::default()`（bind 0.0.0.0:7777 + unix socket，shell 默认禁用）并告警。
- 所有 section `#[serde(default)]`，缺失字段各自走默认。

## 2.2 `[log]`

| 字段 | 类型 | 默认 | 说明 |
|------|------|------|------|
| `level` | string | `"info"` | 日志级别，可被 `RUST_LOG` 环境变量覆盖 |
| `dir` | string | `""` | 审计/滚动日志目录；空=仅 stderr |

```toml
[log]
level = "info"
dir = ""
```

## 2.3 `[tcp]`

| 字段 | 类型 | 默认 | 说明 |
|------|------|------|------|
| `enabled` | bool | `true` | 是否启用 TCP 监听 |
| `bind` | string | `"0.0.0.0:7777"` | 绑定地址；可被 `--tcp-bind` 覆盖 |

```toml
[tcp]
enabled = true
bind = "0.0.0.0:7777"
```

## 2.4 `[unix]`

| 字段 | 类型 | 默认 | 说明 |
|------|------|------|------|
| `enabled` | bool | `true` | 是否启用 Unix socket |
| `path` | string | `"/run/probe-daemon/probe.sock"` | socket 路径；可被 `--unix-path` 覆盖 |

```toml
[unix]
enabled = true
path = "/run/probe-daemon/probe.sock"
```

绑定前清理旧 socket，绑定后 `set_permissions(0o600)`。授权由文件系统权限控制。

## 2.5 `[serial]`（可选）

整体 `Option`，省略则不启用串口。

| 字段 | 类型 | 默认 | 说明 |
|------|------|------|------|
| `path` | string | 无（必填） | 串口设备路径，如 `/dev/ttyS1` |
| `baud` | u32 | 无（必填） | 波特率，如 `115200` |

```toml
[serial]
path = "/dev/ttyS1"
baud = 115200
```

默认 8N1，读超时 250ms。单连接模式（不走 accept 循环，直接 spawn `run_session`）。

## 2.6 `[telemetry]`

| 字段 | 类型 | 默认 | 说明 |
|------|------|------|------|
| `interval_secs` | u64 | `5` | 周期推送间隔秒；`0` 关闭推送（仅拉取） |

```toml
[telemetry]
interval_secs = 5
```

## 2.7 `[shell]`

| 字段 | 类型 | 默认 | 说明 |
|------|------|------|------|
| `enabled` | bool | `false` | **危险**：启用 raw shell |
| `timeout_secs` | u64 | `30` | 命令超时秒 |
| `deny_patterns` | [string] | `[]` | 额外 deny 子串，叠加内置列表，不可削弱 |

```toml
[shell]
enabled = false
timeout_secs = 30
deny_patterns = []
```

**内置 deny 列表（不可削弱）**：`"rm -rf /"`、`"mkfs"`、`"dd if=/dev/zero of=/dev/"`、`":(){ :|:&"`。`deny_patterns` 只能追加。

## 2.8 `[plugins]`

| 字段 | 类型 | 默认 | 说明 |
|------|------|------|------|
| `enabled` | bool | `false` | 是否允许 `plugin.list` / `plugin.invoke`；默认关闭 |
| `dir` | string | `"/opt/sophon/plugins"` | 仅扫描此目录下的 `<id>/plugin.toml` |

```toml
[plugins]
enabled = true
dir = "/opt/sophon/plugins"
```

目录不存在时 `plugin.list` 返回空列表，调用任意插件返回不存在。生产目录、清单和入口程序必须由 root 管理，普通用户不可写；详细包格式见 [`plugins.md`](plugins.md)。

源码: `crates/daemon/src/config.rs:17-18, 137-159`、`crates/infra/src/plugin.rs:49-109`。

## 2.9 `[alerts]`

| 字段 | 类型 | 默认 | 说明 |
|------|------|------|------|
| `temp_c` | f64 | `75.0` | 温度告警阈值 °C |
| `disk_usage_pct` | f64 | `90.0` | 磁盘使用率告警阈值 % |

```toml
[alerts]
temp_c = 75.0
disk_usage_pct = 90.0
```

## 2.10 完整示例

见 [`config/config.toml`](../../../config/config.toml)。

## 2.11 CLI 覆盖

`probe-daemon` 接受：
- `--config <path>`：配置文件路径（默认 `/etc/probe-daemon/config.toml`）。
- `--tcp-bind <addr>`：覆盖 `tcp.bind`。
- `--unix-path <path>`：覆盖 `unix.path`。
- `--shell-enabled`：**临时启用 raw shell**（覆盖 `[shell].enabled=true`）。危险：允许远程执行任意命令，仅调试用；重启不带本参数即恢复关闭。生产建议改 config 而非用此参数，且务必在可信内网。
- `--shell-timeout <secs>`：覆盖 `shell.timeout_secs`（配合 `--shell-enabled` 用）。
- `--dry-run`：不起监听，仅打日志（开发机调试）。

> 用法示例（临时开 shell 跑命令）：
> ```sh
> # 临时开 shell（systemd 服务需改 ExecStart 或临时 systemctl 用参数；或直接前台跑）
> probe-daemon --config /etc/probe-daemon/config.toml --shell-enabled --shell-timeout 60
> # 之后从开发机
> sophonctl --host <板子IP>:7777 exec uname -a
> ```
> 用完**重启服务不带 `--shell-enabled`** 即恢复关闭（`sudo systemctl restart probe-daemon`，前提是 systemd unit 的 ExecStart 不含该参数）。
