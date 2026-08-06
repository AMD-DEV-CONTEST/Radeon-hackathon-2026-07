# ComfyUI 远程访问操作说明书

适用于本机（AMD 服务器，ComfyUI 0.29.0，默认监听 `8188` 端口）的远程访问配置。

---

## 1. 前置条件

- 服务器上 ComfyUI 已启动，且监听端口为 `8188`（默认）。
- 你能通过 SSH 登录服务器（拿到 IP、端口、用户名、密码/密钥）。
- 本地电脑能访问外网（用于 SSH 隧道或云穿透）。

---

## 2. 服务器端：启动 ComfyUI

在服务器上启动 ComfyUI，并监听外部可访问的地址：

```bash
cd /workspace/ComfyUI
source /persistent/amd_ai_env/bin/activate
python3 main.py --listen --port 8188
```

参数说明：

| 参数                 | 说明                                    |
| ------------------ | ------------------------------------- |
| `--listen`         | 监听所有网卡（`0.0.0.0`），默认只监听本机 `127.0.0.1` |
| `--listen 0.0.0.0` | 同上，显式写法                               |
| `--port 8188`      | 指定端口，默认就是 8188                        |

> 本仓库已写好脚本，直接执行：
> 
> ```bash
> ./run_comfy.sh          # 前台启动
> ./start_comfy_public.sh # 后台启动 + 平台 rc-tunnel 外网穿透
> ```

启动成功后，服务器本地访问验证：

```bash
curl http://127.0.0.1:8188
# 或
curl http://<服务器IP>:8188
```

---

## 3. 远程访问的几种方式

### 方式 A：局域网内直接访问（最简单）

确认本机 IP，然后在同一局域网内的电脑浏览器打开：

```bash
hostname -I   # 查看服务器内网 IP，例如 192.168.1.100
```

浏览器访问：

```
http://192.168.1.100:8188
```

**适用**：你和服务器在同一局域网。若 ComfyUI 用的是默认 `127.0.0.1` 监听，此方式不可用。

---

### 方式 B：SSH 隧道（推荐，安全，无需开公网端口）

在你**本地电脑**的终端执行，把服务器的 8188 端口映射到本地：

**Windows（PowerShell / CMD）：**

```bash
ssh -N -L 8188:127.0.0.1:8188 user@服务器IP
```

**macOS / Linux：**

```bash
ssh -N -L 8188:127.0.0.1:8188 user@服务器IP
```

- `-N` 不执行远程命令，只做转发
- `-L 本地端口:目标地址:目标端口`，把本地 8188 转发到服务器的 8188

若 SSH 端口不是 22：

```bash
ssh -N -L 8188:127.0.0.1:8188 -p 端口号 user@服务器IP
```

然后本地浏览器打开：

```
http://127.0.0.1:8188
```

**优点**：全程加密、无需对外暴露 ComfyUI 端口、不受平台防火墙影响（只要 SSH 通就行）。

---

### 方式 C：Cloudflare Tunnel（免费公网 HTTPS 链接）

1. 安装 cloudflared：

```bash
# Linux (x86_64)
wget https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64
sudo mv cloudflared-linux-amd64 /usr/local/bin/cloudflared
sudo chmod +x /usr/local/bin/cloudflared
```

2. 服务器上启动一条临时隧道，把本机 8188 暴露出去：

```bash
cloudflared tunnel --url http://127.0.0.1:8188
```

3. 终端会打印一个 `https://xxxx.trycloudflare.com` 链接，复制到本地浏览器打开即可。

**注意**：trycloudflare 免费隧道链接是随机的、重启会变；适合临时共享，不适合固定使用。

---

### 方式 D：平台自带穿透 rc-tunnel（本环境已在用）

本服务器平台自带外网穿透工具 `rc-tunnel`，一条命令即可获得公网 HTTPS 链接：

```bash
# 停掉旧隧道（如有）
rc-tunnel stop
pkill -f frpc 2>/dev/null

# 开启 8188 端口的外网隧道
rc-tunnel expose --port 8188

# 查看隧道状态与链接
rc-tunnel status
```

直接执行仓库里的脚本一键完成：

```bash
./start_comfy_public.sh
```

脚本会：后台启动 ComfyUI → 开隧道 → 打印 HTTPS 链接，把链接复制到本地浏览器打开。

---

## 4. 访问方式对比

| 方式                | 安全性 | 需要公网端口  | 是否加密 | 适用场景        |
| ----------------- | --- | ------- | ---- | ----------- |
| 局域网直连             | 中   | 否       | 否    | 同一局域网       |
| SSH 隧道            | 高   | 否（用 22） | 是    | 长期、日常使用（推荐） |
| Cloudflare Tunnel | 高   | 否       | 是    | 临时外网分享      |
| rc-tunnel（平台）     | 中   | 否       | 是    | 本平台一键外网访问   |

---

## 5. 安全建议

- **默认无登录认证**：ComfyUI 直接暴露公网时任何人拿到链接都可操作。推荐优先用 SSH 隧道。
- **只监听本机**：若不需要公网访问，启动时去掉 `--listen`，保持默认 `127.0.0.1`。
- **防火墙**：若云平台/系统防火墙拦截，确认放行 8188（局域网直连时）或 22（SSH 时）：

```bash
sudo ufw allow 8188/tcp
sudo ufw allow 22/tcp
```

- **多用户隔离**：如需为多人提供访问，可加 `--multi-user` 参数启动，用户数据按账号隔离：

```bash
python3 main.py --listen --port 8188 --multi-user
```

---

## 6. 常见问题排查

| 现象         | 排查方法                                                                                      |
| ---------- | ----------------------------------------------------------------------------------------- |
| 浏览器打不开     | 确认 ComfyUI 正在运行、`--listen` 已开启；`curl http://127.0.0.1:8188` 是否返回页面                        |
| SSH 隧道连接超时 | 见 `check_ssh_server_info.sh` 自检：若 SSH 22 端口连不通，说明平台外层防火墙封了 SSH，改用 rc-tunnel / cloudflared |
| 公网链接访问慢    | 隧道受平台带宽限制，属正常；图片/模型较大时耐心等待                                                                |
| 端口被占用      | `--port 8189` 换端口，或 `pkill -f main.py` 停掉旧进程再启动                                           |

运行服务器自检脚本，可一键确认 SSH/网络/防火墙状态：

```bash
./check_ssh_server_info.sh
```
