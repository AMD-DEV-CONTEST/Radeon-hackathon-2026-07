# BotverseX 客户快速开始

> 面向使用 BotverseX 网站连接实体机器人的用户。不是开发者文档，也不涉及源码仓库结构。

## 先选一条路：你今天想做什么？

**A. 只是想看看 / 演示给朋友看（零安装，没真机也能玩）**  
→ 打开 [botversex.feispace.me/play](https://botversex.feispace.me/play)（或本地 `http://127.0.0.1:5173/play`）。自动进虚拟 Reachy、播一段动作；继续点页面上的动作就能玩。不用装任何东西。

**B. 手头有 SO-101，只想先让关节动一下（零安装）**  
→ Chrome / Edge 打开 [SO-101 浏览器直连](https://botversex.feispace.me/robots/so101?mode=browser)，插 USB → 授权串口 → 扫舵机 → 拖滑条。**不装 Local Agent。**

**C. 要主从遥操、长时间录制、训练，或接 B601 / Reachy 真机**  
→ 才走下面的「四步连接」装 Local Agent。

> 先 A 或 B，再决定要不要装 Agent。Agent 是进阶路径，不是第一步。

## 你需要知道的三件事

1. **网站**负责项目管理、训练、模型和工作流。
2. **Local Agent** 在你自己的电脑上运行，负责 USB 摄像头、串口和机械臂。
3. 只浏览网站、不做硬件操作时，**不需要**启动 Local Agent。虚拟 demo 也不需要。

## 什么时候必须启动 Local Agent？

- 连接 SO-101 / Reachy Mini / **reBot B601-RS** 真机
- 遥操作、录制示教数据
- 使用本机摄像头或串口

> 浏览器虚拟 demo、看 3D 模型、浏览 AI Hub 模型库、配置云端训练任务——这些都**不需要** Local Agent。

### Reachy Mini 速记

- BotverseX 接的是 **Lite**（USB + 外接电脑）；完整版才有 WiFi / 电池 / 板载树莓派。
- **本体电源必须打开**，只插 USB 不够。
- 页面：`/robots/reachy_mini` → 高级抽屉「规格与入门」；完整对照见 `docs/reachy-mini-seeed.md`。

## 四步连接（仅真机用户）

> 这四步只针对选了上面 B 路径的用户。A 路径（虚拟 demo）请直接点上面的链接，跳过这里。

1. **安装** — 在本机安装 Local Agent（见 Setup 页复制命令）
2. **启动** — 终端运行 `python run_api.py`，窗口保持打开
3. **信任证书** — 浏览器打开 `https://localhost:8002` 并选择继续访问（每个浏览器只需一次）。**这一步很容易忘**：装完 Agent 不信任证书，浏览器会一直报"无法连接"，但 Agent 其实是好的。建议装完 Agent 第一时间先做这一步。
4. **重新检测** — 回到 Setup 页，确认显示「已连接」

## 卡住了怎么办？

打开网站右下角的 **BotverseX Copilot**，它会根据当前页面自动诊断并给出修复步骤。常见问题：

- `python3-venv` 未安装
- pip 下载太慢
- 8002 端口被占用
- 摄像头被其他程序占用
- 串口没有 dialout 权限

## 数据隐私

录制和数据集默认保存在你的电脑，除非你主动上传到云端。

## B601-RS 机械臂（M27）

1. 在 **Robots** 页选择 **reBot B601-RS** → **新手上手** 或 **工作台**
2. 插上 PCAN-USB、48V 从臂、Star Arm 102 主臂 USB；运行一键安装器（含 CAN + 官方遥操插件）
3. **新手上手**：连接 → 试遥操 → 录数据 → 去训练（可选，不必每步都走完）
4. **工作台**：Stage 3D + 遥操 / 数据 / 部署 / 视觉 Tab

### 两阶段上电（听感正常）

1. **唤醒从臂**（recover）：7 关节 clear-error + enable，短促电机声
2. **开始遥操**：官方 configure() 再逐关节上电（约十秒，噪声更大）→ 从臂跟主臂

### 停止 = 卸力

点「停止遥操」后会显示 **卸力中…**（约 3–5 秒）。从臂应可手推。若仍有电机声，高级抽屉 → **从臂卸力**。

### 拔 USB / 热拔 HUB

先 **停止遥操** → **从臂卸力**，再拔线。静止状态下偶发拔 HUB 通常无大碍，但养成顺序可避免 fault。

### 开发注意

Local Agent 开发请用：`cd apps/realtime && python run_api.py --http`（Vite 代理 HTTP，否则 URDF 502）。

验收脚本：`bash scripts/b601-smoke.sh`

常见问题由 Copilot 一键修复：CAN 未连接、主臂 USB、从臂软掉、URDF 零件 404。
