# BotverseX — Windows 演示机部署（联想笔记本）

开发机在 Linux，演示机在 **Windows**。Reachy Mini USB 接在演示机上。

## 1. 演示机先装这些（一次性）

1. [Node.js 20+](https://nodejs.org/)
2. [Python 3.12+](https://www.python.org/)（安装时勾选 *Add to PATH*）
3. **OpenSSH Server**（设置 → 应用 → 可选功能 → OpenSSH 服务器）
4. Git（可选，用于拉 SDK）

PowerShell（当前用户）：

```powershell
Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
```

## 2. 从 Linux 开发机同步项目

在开发机上（需知道 Windows 的局域网 IP，例如 `192.168.57.x`）：

```bash
# 建议写入 ~/.ssh/config：
# Host reachy-demo
#   HostName 192.168.57.XXX
#   User amd
#   IdentityFile ~/.ssh/reachy_lenovo

DEMO_SSH_HOST=amd@192.168.57.XXX bash scripts/sync-to-demo.sh

# 同时同步豆包 API keys + Seeed 对话目录（含你的 config/audio 补丁）：
SYNC_KEYS=1 DEMO_SSH_HOST=amd@192.168.57.XXX bash scripts/sync-to-demo.sh
```

同步位置：`C:\Users\Public\dev\botversex`（不含 venv / node_modules，体积小）。

## 3. 演示机安装依赖

```powershell
cd C:\Users\Public\dev\botversex
.\scripts\windows\setup-first.ps1
```

## 4. Reachy SDK（演示机）

Allan 版 SDK 需单独克隆（体积大，不走 git 同步）：

```powershell
cd C:\Users\Public\sdk
git clone <your-reachy_mini_Allan-repo> reachy_mini_Allan
cd reachy_mini_Allan
python -m venv .venv
.\.venv\Scripts\pip.exe install -e .
```

若路径不是默认，改环境变量或编辑：

`apps\realtime\config\robots.windows-demo.json` → `service.sdk_path`

## 5. 启动演示

```powershell
cd C:\Users\Public\dev\botversex
.\scripts\windows\dev-all.ps1 up
```

浏览器打开：<http://127.0.0.1:5173/robots/reachy_mini>

局域网观众访问：`http://<演示机IP>:5173/robots/reachy_mini`

## 6. 环境变量（可选）

| 变量 | 说明 |
|------|------|
| `BOTVERSEX_ROBOTS_CONFIG` | Windows 机器人清单，默认 `robots.windows-demo.json` |
| `REACHY_MINI_SDK_PATH` | SDK 目录 |
| `REACHY_MINI_SERIAL_PORT` | 固定 COM 口，如 `COM5` |
| `BOTVERSEX_SEEED_CONVERSATION_DIR` | Seeed 对话目录 |
| `BOTVERSEX_SEEED_KEYS_FILE` | 豆包 keys JSON |

## 7. Linux vs Windows 差异（已适配）

- 串口：`/dev/ttyACM*` → `COM*`，自动扫描
- Python venv：`.venv/bin/python` → `.venv\Scripts\python.exe`
- 日志：`/tmp/*` → `%TEMP%` 或 `C:\Users\Public\botversex\logs`
- 音量：Linux 用 `amixer`；Windows 走 daemon `/api/volume/set`
- SO-101 / B601 / CAN：演示机可只保留 Reachy，用 `robots.windows-demo.json`

## 8. 日常更新（开发机改完 → 演示机）

```bash
# Linux 开发机
DEMO_SSH_HOST=reachy-demo bash scripts/sync-to-demo.sh
```

```powershell
# Windows 演示机（依赖未变时只需重启）
.\scripts\windows\dev-all.ps1 down
.\scripts\windows\dev-all.ps1 up
```

## 9. 排障

| 现象 | 检查 |
|------|------|
| SSH 连不上 | Windows IP、防火墙 22 端口、OpenSSH 服务是否运行 |
| 串口找不到 | 设备管理器里 COM 号，设 `REACHY_MINI_SERIAL_PORT=COMx` |
| daemon 起不来 | SDK venv、`REACHY_MINI_SDK_PATH`、日志 `%TEMP%\botversex_reachy_mini_daemon.log` |
| 本体对话无声 | keys 是否同步；Windows 默认音量；Seeed 进程日志 `%TEMP%\botversex_seeed_conversation.log` |

## 10. 回退

演示机保留 git 时可：

```powershell
git checkout main
git pull   # 或重新 sync-to-demo.sh
```
