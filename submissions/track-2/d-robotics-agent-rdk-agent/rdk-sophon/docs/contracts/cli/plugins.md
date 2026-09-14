# 3. 动态控制插件契约

> 动态插件让板端安装新能力后直接使用 `sophonctl <插件名> <参数...>`，无需修改或重新编译 `sophonctl`。实现源码：`crates/api-cli/src/main.rs`、`crates/application/src/rpc_dispatcher.rs`、`crates/infra/src/plugin.rs`。

## 3.1 调用与 RPC 映射

```sh
sophonctl plugins list
sophonctl servo init
sophonctl servo stand --hold inf
sophonctl servo shake-ears
sophonctl servo relax
sophonctl servo servo 0 -2.0
```

`plugins list` 发出 `plugin.list`。未被内置子命令占用的第一个词会作为插件名，后续每个命令行参数保持为一个独立的字符串，发出：

```json
{"jsonrpc":"2.0","id":1,"method":"plugin.invoke","params":{"plugin":"servo","args":["stand","--hold","inf"]}}
```

成功响应：

```json
{"jsonrpc":"2.0","id":1,"result":{"exit":0,"stdout":"","stderr":""}}
```

`exit` 为进程退出码，信号终止时可为 `null`；stdout/stderr 均最多回传 256 KiB。插件找不到或参数类型不正确返回 `InvalidParams`（-32602）；超时返回 `Timeout`（-32003）；启动/读取 manifest 失败返回 `ExecError`（-32000）。

源码: `crates/api-cli/src/main.rs:49-76, 163-196`、`crates/application/src/rpc_dispatcher.rs:105-107, 176-255`、`crates/infra/src/plugin.rs:16-17, 113-183`。

## 3.2 插件包格式

daemon 只发现配置 `[plugins].dir` 下第一层目录的 `plugin.toml`，例如：

```text
/opt/sophon/plugins/servo/
├── plugin.toml
└── servo_plugin.py
```

`plugin.toml`：

```toml
api_version = 1
id = "servo"
description = "舵机姿态控制"
entrypoint = ["/usr/bin/python3", "/opt/sophon/plugins/servo/servo_plugin.py"]
timeout_secs = 0
```

仓库提供了可直接用于 MagicBox 脚本的示例清单：`examples/plugins/servo/plugin.toml`。

| 字段 | 类型 | 规则 |
|------|------|------|
| `api_version` | u32 | 当前必须为 `1` |
| `id` | string | 小写字母开头；其余只能是小写字母、数字、`-`；即 CLI 一级命令名 |
| `description` | string | 可选，默认空字符串；展示在插件列表 |
| `entrypoint` | string array | 必填且非空；第一个元素为可执行程序，余项为固定参数 |
| `timeout_secs` | u64 | 可选，默认 `0`；`0` 不设超时，正数为秒 |

daemon 以 `entrypoint + args` 的精确 argv 启动进程，不经 `sh -c`。上例中 Python 脚本收到的 `sys.argv[1:]` 依次是 `stand`、`--hold`、`inf`。这使 Python、Rust、Go、C/C++ 或任何可执行文件都能作为插件入口。

源码: `crates/infra/src/plugin.rs:19-37, 69-94, 133-156`。

## 3.3 安装、权限与中断

```sh
sudo install -d -o root -g root -m 0755 /opt/sophon/plugins/servo
sudo install -o root -g root -m 0644 plugin.toml /opt/sophon/plugins/servo/plugin.toml
sudo install -o root -g root -m 0755 servo_plugin.py /opt/sophon/plugins/servo/servo_plugin.py
sudoedit /etc/probe-daemon/config.toml  # 设置 [plugins] enabled = true
sudo systemctl restart probe-daemon
sophonctl plugins list
```

插件目录不需要 daemon 重启即可重新扫描；修改 `[plugins]` 配置本身则需要重启。一个连接在执行插件时收到 EOF（例如 `sophonctl servo stand --hold inf` 按 Ctrl-C）会 abort 当前请求；执行器启用 `kill_on_drop`，子进程被回收。

`probe-daemon` 默认以无特权 `probe` 用户和 `NoNewPrivileges=true` 运行。因此旧脚本中的 `sudo python3 ...` 不能直接作为插件入口。需要硬件特权时，应让插件调用专门的、按操作白名单实现的控制 Broker；不要把 daemon 改成 root 或开放泛化 sudo。

源码: `crates/application/src/session_service.rs:43-142`、`crates/infra/src/plugin.rs:148`、`systemd/probe-daemon.service:14-27`。
