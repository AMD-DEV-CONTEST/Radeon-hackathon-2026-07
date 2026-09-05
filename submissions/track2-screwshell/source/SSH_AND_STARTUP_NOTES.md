# SSH 连接恢复 & 服务拉起复盘（u-14441-f4391bc7 @ 36.150.116.206）

> 沉淀自 2026-08-03 一次实例重启后的排障。面向后续 agent / 本人，照做即可。
> 本机副本：与实例 `/workspace/persistent/screwshell_run/SSH_AND_STARTUP_NOTES.md` 保持同步。

## 0. 一句话结论
实例重启后：SSH 服务端要等 sshd 自己起来（或由平台拉起）；
- [x] **venv 重启后丢 4 个 Python 包**：`gradio` + relay 依赖 `fastapi`/`uvicorn`/`sse-starlette`（torch/transformers 还在）。llama-server 是编译二进制不依赖 venv，所以重启后它常能起、relay+UI 却因 ModuleNotFoundError 静默死（端口全 000）。**已修复（2026-08-05 实测 rc=0）** 一键补回全部依赖：

## 1. SSH 连接
- 平台用 CloudFlare/网关把 `36.150.116.206:31010`(或 31033) 映射到实例内 `22`。
- 实例内 sshd 二进制在 `/usr/sbin/sshd`（openssh-server，已装；"只有 client 没 server" 的旧认知是错的）。
- 重启后 sshd 可能由平台/某 agent 自动拉起（PID 约 924，监听 0.0.0.0:22）。
  若连不上先确认：`ps aux | grep sshd`，没有就 `mkdir -p /run/sshd && /usr/sbin/sshd`。
- 公钥注入在 env `ONECLICK_SSH_PUBLIC_KEY`，需写 `/root/.ssh/authorized_keys` 才能 key 登录。
- 控制端 known_hosts 指纹会变，连不上且报 HOST IDENTIFICATION CHANGED 时：
  `ssh-keygen -R "[36.150.116.206]:31010"` 再重连。

## 2. 远程控制通道（当 SSH 不通时）
SSH 不通时，唯一能操作实例的是平台网页端 **JupyterLab**（PID 1 起的 jupyter，base_url `/instances/u-14441-f4391bc7/`）。
Jupyter 里 `New -> Terminal` 就是 shell，可替代 SSH 跑命令。
实例内**没有** sshd 时无法从外部连；但本例 sshd 实际存在，重启后等它起即可。

## 3. 服务拉起（重要：用自带脚本，别自己拼）
仓库根目录已有验证过的脚本：
仓库根目录已有验证过的**生产规范脚本**（旧 `_run_roomy_server.sh`/`_run_ui.sh` 已降级为回滚参考 `run_roomy_server.sh.bak2`，部分还是空文件/报错存根）：
- `run_gateway.sh`     -> 一键 llama-server(:8080) + MoL relay(:18090)（走 `screwshell.gateway.cli`，预检 :8080/:18090 占用，占用则拒绝启动）
- `run_ui_relay.sh`    -> Gradio UI(:7860) 走 relay（MOL_RELAY_MODE=1，X-Expert 头交 relay 做全局 LoRA 热切）
  llama-server 关键参数同下（--jinja / --ctx-size 131072 / --reasoning-budget 4096 / --alias screwshell-base），脚本已固化，别自己拼
**llama-server 启动关键参数（2026-08-03 踩坑结论，缺一不可）：**
- `--jinja`：**必须**。否则 `/v1` 拒 `tools` 参数、opencode/pi 拿不到工具能力。
- `--ctx-size 131072`（128K）：8K/32K 对 opencode agentic 都太小，会上下文不足。
- `--reasoning-budget 4096`：**必须**。Qwen3.6 默认 thinking=1 且 budget 无限，不限制则一个
  "hi" 都卡 130s+ 疯狂 prefill。彻底关思考用 `--reasoning off`。
- 路径用 `/opt/llama.cpp`（**不是** `/opt/llama.cpp.new`，那个目录不存在）。

正确后台启动姿势（**必须用 setsid 脱离 SSH 会话**，否则会话结束 server 被平台静默回收）：
> 2026-08-05 实测：不要 `ssh ... "cmd & disown"` 或 `ssh ... "setsid cmd &"` 里直接后台——本平台 SSH 包裹层会吞掉 stdout、进程被平台回收（日志空、端口 000）。
> 正确姿势：先把启动脚本用 base64 写到实例，再 `setsid bash 脚本 </dev/null >/dev/null 2>&1 &`：
> ```
> # 本机 PowerShell：避开 heredoc/引号在 SSH 包裹层炸开
> $b64 = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($script))
> ssh -p 31010 root@36.150.116.206 "echo $b64 | base64 -d > /tmp/start.sh && chmod +x /tmp/start.sh"
> ssh -p 31010 root@36.150.116.206 'setsid bash /tmp/start.sh </dev/null >/dev/null 2>&1 &'
> ```
> 引号坑：经 SSH 传命令时 `()` 和未引号的 `==文字==` 会在包裹层触发 bash 语法错误；命令含这些就走上面的 base64 脚本法，别手拼。
```
# 杀旧 server（先确认端口释放，否则新进程 couldnt bind 8080 直接退出）
pkill -9 -f "llama-server.*8080"; sleep 4
(ss -ltn 2>/dev/null || netstat -ltn 2>/dev/null) | grep -q 8080 && echo BUSY || echo FREE
# 起新（setsid 脱离，nohup 防 SIGHUP）
setsid bash -c "nohup /opt/llama.cpp/build/bin/llama-server \
  --model /workspace/persistent/screwshell_run/models/Qwen3.6-27B-Q4_K_M.gguf \
  --host 127.0.0.1 --port 8080 --jinja --ctx-size 131072 --n-gpu-layers 999 \
  --threads 24 --reasoning-budget 4096 > llama_server.log 2>&1 &"
```
UI 同理（setsid 脱离）：
```
pkill -9 -f "screwshell.ui.app"; sleep 2
setsid bash -c "nohup bash /workspace/persistent/screwshell_run/_run_ui.sh > ui.log 2>&1 &"
```

### 3.1 部分重启（llama :8080 仍健康时）
不要跑 `run_gateway.sh`——它的 prelaunch 端口检测会在 :8080 已占时拒绝启动（non-zero exit，不静默继续）。
直接拉 relay + UI，复用 `screwshell/gateway/cli.py` `_launch_relay` 的 env 契约：
```
export OBSERV_DIR=/workspace/persistent/screwshell_run/observ
# relay (fastapi/uvicorn)
export RELAY_BIND_ADDR=127.0.0.1 RELAY_PORT=18090
export RELAY_TRUST_TOKEN=screwshell-relay-devtoken
export RELAY_LLAMA_URL=http://127.0.0.1:8080
setsid /opt/venv/bin/python -m screwshell.gateway.relay </dev/null >/tmp/relay_direct.log 2>&1 &
# UI 走 relay
export MOL_BACKEND=llamacpp MOL_LLAMACPP_URL=http://127.0.0.1:18090 MOL_RELAY_MODE=1
unset MOL_LLAMACPP_API_KEY MOL_LLAMACPP_MODEL
setsid /opt/venv/bin/python -m screwshell.ui.app \
  --workspace /workspace/persistent/screwshell_run/demo_workspace \
  --base /workspace/persistent/screwshell_run/models/Qwen3.6-27B-Q4_K_M.gguf \
  --port 7860 --no-rag </dev/null >/tmp/ui_direct.log 2>&1 &
```

## 4. 本机访问 UI
ssh -p 31010 -L 7860:localhost:7860 root@36.150.116.206，保持窗口开，浏览器开 http://localhost:7860

## 5. 已知坑（踩过的）
- llama.cpp 真实路径是 `/opt/llama.cpp/build/bin`（**不是** `/opt/llama.cpp.new` —— 那个目录不存在，是之前记错的）。
- llama-server 已运行在 `:8080`，且 `--host 127.0.0.1`；UI（`_run_ui.sh`）连的就是 `http://127.0.0.1:8080`，不要再自己改端口。
- llama-server 端口参数是 `--port`，不是 `-p`。
- **llama-server 后台启动必须用 `setsid` 脱离 SSH 会话**：裸 `nohup ... &` 在 SSH 断开时会被
  平台整条回收，server 静默退出（日志见 `cleaning up before exit`）。旧笔记说"setsid 会被
  回收、用 nohup 才稳"是**错的**，已证伪。正确姿势见 §3。
- 重启前务必 `pkill -9` + 确认 8080 释放（sleep 4 + `ss -ltn|grep 8080`），否则新进程
  `couldnt bind HTTP server socket, port: 8080` 直接退出、旧进程还在跑旧配置。
- `--jinja` 漏了 → tools 调不动；`--reasoning-budget` 漏了（默认 -1 无限）→ "hi" 都卡死。
  详见 §3 启动关键参数。
- 子 shell 里 `export PATH=/opt/venv/bin` 不够，要 `source /opt/venv/bin/activate` 才能 import gradio。（relay 依赖 fastapi+uvicorn+sse-starlette，UI 依赖 gradio，缺哪个哪个静默死）

## 6. 待解决（2026-08-03 状态）
- [x] **venv 重启后丢 4 个 Python 包**：`gradio` + relay 依赖 `fastapi`/`uvicorn`/`sse-starlette`（torch/transformers 还在）。llama-server 是编译二进制不依赖 venv，所以重启后它常能起、relay+UI 却因 ModuleNotFoundError 静默死（端口全 000）。**已修复（2026-08-05 实测 rc=0）** 一键补回全部依赖：
  `/opt/venv/bin/pip install --no-cache-dir -i https://pypi.tuna.tsinghua.edu.cn/simple --trusted-host pypi.tuna.tsinghua.edu.cn fastapi uvicorn sse-starlette gradio`
- [ ] 三个 LoRA 在 llama-server 启动时通过 --lora 常驻预载（非运行时热切换），确认 _run_roomy_server.sh 的 lora 路径都还在。
