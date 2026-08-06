# 1. 部署说明

> 板端部署 `probe-daemon` 为 systemd 服务，长驻运行、开机自启、崩溃自动重启。
> 本文基于 `deploy/scripts/`、`systemd/probe-daemon.service`、`config/config.toml` 真实内容。

## 1.1 一键部署（开发机→板子）

```sh
# 已编译好（target/aarch64-unknown-linux-gnu/release/*）
./deploy/scripts/deploy-to-board.sh x5-root
```

脚本流程（见 `deploy/scripts/deploy-to-board.sh`）：
1. 校验本地产物齐全。
2. scp 4 个二进制 + config.toml + probe-daemon.service + install-on-board.sh 到板子 `/tmp/rdk-sophon-deploy/`。
3. 远程 `sudo bash install-on-board.sh`：装二进制到 `/usr/local/bin`、配置到 `/etc/probe-daemon/`、unit 到 `/etc/systemd/system/`、建 `probe` 用户、备 `/var/log/probe-daemon` 与 `/run/probe-daemon`。
4. `systemctl daemon-reload` + `systemctl enable --now probe-daemon`。
5. 验证：`systemctl status` + `ss -lnt | grep 7777`。

完成后再从 Mac 验证：
```sh
sophonctl --host 192.168.128.10:7777 state
```

## 1.2 systemd 服务

unit 文件：`systemd/probe-daemon.service`，部署时复制到 `/etc/systemd/system/probe-daemon.service`。

关键配置：
- `Type=simple`，`ExecStart=/usr/local/bin/probe-daemon --config /etc/probe-daemon/config.toml`。
- `Restart=on-failure`，`RestartSec=2`：崩溃 2 秒后自动重启。
- `User=probe` / `Group=probe`：专用非特权用户（`install-on-board.sh` 自动建）。
- `RuntimeDirectory=probe-daemon`：服务自己的 `/run/probe-daemon`，由 systemd 管理权限，Unix socket 放这。
- 硬化：`NoNewPrivileges`、`ProtectSystem=strict`、`ProtectHome`、`PrivateTmp`、`CapabilityBoundingSet=`（无任何 capability）、`AmbientCapabilities=`。
- `ReadWritePaths=/var/log/probe-daemon /run/probe-daemon`：只这两处可写，其它只读。

> 注意：unit 默认 `User=probe`。若板子不便建专用用户，可改成 `root` 并删 `CapabilityBoundingSet=`，但**不推荐**——削弱了硬化。

## 1.3 配置

配置文件：`config/config.toml` → 板子 `/etc/probe-daemon/config.toml`。
完整字段契约见 [`docs/contracts/cli/config.md`](../../docs/contracts/cli/config.md)。

生产要点：
- `[shell] enabled = false`：**生产必须关闭** raw shell（默认就是 false）。启用等于给远端 root，仅限可信内网调试。
- `[tcp] bind = "0.0.0.0:7777"`：监听所有网卡。若只内网用，可绑具体 IP。
- `[telemetry] interval_secs`：推送周期；0 关推送（仅拉取）。
- `[alerts]`：温度/磁盘阈值。

改配置后重启生效：
```sh
ssh x5-root 'sudo systemctl restart probe-daemon'
```

## 1.4 运行/查看/控制

```sh
# 启动/停止/重启
sudo systemctl start probe-daemon
sudo systemctl stop probe-daemon
sudo systemctl restart probe-daemon

# 开机自启
sudo systemctl enable probe-daemon
sudo systemctl disable probe-daemon

# 状态
sudo systemctl status probe-daemon
sudo systemctl is-active probe-daemon

# 实时日志（journalctl）
sudo journalctl -u probe-daemon -f
# 最近 100 行
sudo journalctl -u probe-daemon -n 100 --no-pager
# 审计日志（exec_shell 的 source/method/args/outcome/duration_ms）
sudo journalctl -u probe-daemon | grep audit
```

## 1.5 升级（重新部署新版本）

升级就是重新部署一遍，systemd 会重启服务：

```sh
# 开发机：重新编译（出包前自动跑全量测试）
./deploy/scripts/build-release.sh

# 推送并重启服务（覆盖二进制 + 配置 + unit，daemon-reload + restart）
./deploy/scripts/deploy-to-board.sh x5-root
```

`deploy-to-board.sh` 每次都重装覆盖，systemd `Restart=on-failure` 保证滚动升级失败也自动拉起。

## 1.6 回滚

保留上一版本二进制即可回滚。推荐：

```sh
# 板子上：备份当前版本再升级
ssh x5-root 'sudo cp /usr/local/bin/probe-daemon /usr/local/bin/probe-daemon.prev'

# 出问题回滚
ssh x5-root 'sudo cp /usr/local/bin/probe-daemon.prev /usr/local/bin/probe-daemon && sudo systemctl restart probe-daemon'
```

配置回滚同理（`/etc/probe-daemon/config.toml` 备份）。

## 1.7 部署 HTTP 网关 / WS 出站（可选）

`probe-daemon` 是必须的。`probe-http-gateway` 和 `probe-ws-outbound` 是可选入口：

### HTTP 网关
装到板子后手动起（当前未提供独立 systemd unit，按需加）：
```sh
# 板上（连本地 daemon Unix socket，对外 8080）
probe-http-gateway --listen 0.0.0.0:8080 --daemon-sock /run/probe-daemon/probe.sock
```
开发机验证：
```sh
curl http://192.168.128.10:8080/state
```
REST 契约见 [`docs/contracts/http/`](../../docs/contracts/http/)。

### WS 出站
```sh
probe-ws-outbound --broker-url ws://broker.example.com/board-001 \
                  --daemon-sock /run/probe-daemon/probe.sock
```
出站契约见 [`docs/contracts/transport/ws-outbound.md`](../../docs/contracts/transport/ws-outbound.md)。

## 1.8 安全注意事项

1. **TCP 7777 当前是明文**：生产建议绑内网 IP，或前置 SSH 隧道/反代 + mTLS（mTLS 待补，见 README 进度）。
2. **shell 默认关闭**：生产绝不开启 `[shell] enabled = true`，除非可信内网且需调试。
3. **Unix socket 权限 0600**：由 systemd `RuntimeDirectory` + 文件权限控制，仅 probe 用户与 root 可访问。
4. **硬化 unit**：`ProtectSystem=strict` + 无 capability，限制被入侵后的影响面。

## 1.9 故障排查

| 现象 | 排查 |
|------|------|
| 服务起不来 | `journalctl -u probe-daemon -n 50`，常见：config 语法错（回退默认）/ 端口占用 / socket 路径无权限 |
| 7777 没监听 | `ss -lnt \| grep 7777`；`[tcp].enabled=false`？bind 被占？ |
| 板上 rustup 报 manifest 缺失 | 换 tuna 镜像重装（见 build.md「故障排查」） |
| 交叉编译链接失败 | Mac 用 zigbuild（见 build.md「方式一：开发机交叉编译」） |
| 采集器返回 null（非板子） | 正常：Mac 上无 `/proc`/`/sys`；板子上看 `/sys/class/thermal` 等是否存在 |
| exec_shell 被拒 | 确认 `[shell].enabled`；命令是否命中内置 deny（`mkfs`/`rm -rf /` 等） |
| 临时想跑 shell 命令 | `probe-daemon --shell-enabled [--shell-timeout 60]` 重启（不改 config，重启不带参数即关闭）；或改 config `[shell] enabled = true` + restart（持久，用完务必改回）。仅可信内网。 |
| 升级后行为异常 | `probe-daemon.prev` 回滚（见「回滚」节） |
