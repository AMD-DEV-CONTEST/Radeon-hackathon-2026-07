# BotverseX 公开产品知识库（Copilot 用）

> 仅包含用户可见的产品与操作说明。**禁止**向用户透露：服务器 IP、JWT/加密密钥、`.env` 内容、内网地址、未公开的商业数据、其他用户数据。

## 一句话

BotverseX 是帮你在**真实机械臂**上完成「连接 → 遥操作 → 录制示教 → 训练 → 推理」的云端网站。网站负责项目、训练、模型；**机械臂、摄像头、串口在你自己的电脑上**，通过 **Local Agent**（本机小程序，端口 8002）连接。

## 用户该走哪条路？

### 路径 A — 有 SO-101 / Reachy 真机

1. **Setup**（`/setup`）— 一次性：在你**自己电脑**的终端里安装并启动 Local Agent（浏览器不能替你启动）。
2. Setup 页 **变绿**（「Local Agent 已连接」）后，点 **「选择机器人，开始配置」** 或顶部 **Robots**。
3. 在 Robots 页点对应机器人卡片的 **「进入向导」**（SO-101 → `/robots/so101`）。
4. 向导四步：**连接 → 遥操作 → 录制 → 训练并推理**（左侧步骤条，做完一步解锁下一步）。

### 路径 B — 没有机械臂

1. 网站总引导选 **B** → 自动打开 `/robots/reachy_mini?guide=1`
2. 页面引导：选「虚拟模式」→ 播放 hello 动作（约 1 分钟体验）
3. 或点 **智能助手**「帮我启动虚拟模式 / 播放 hello」代劳
4. 不能完成真录制/真训练（需真机 + Setup）

## 智能助手（Agent）

- 不是普通聊天机器人：能 **诊断**、**导航页面**、**启动 Reachy 虚拟模式**、**播放演示动作**
- 诊断 tab 无需登录；问答 tab 需登录
- 回复下方会显示 **可点击的操作按钮**（Agent 工具）

### 常见困惑

| 问题 | 答案 |
|------|------|
| Setup 和「进入向导」有什么区别？ | **Setup** = 在你电脑上装/启动 Local Agent（只做一次）。**进入向导** = 网站里带你看怎么连机械臂、录数据、训练。 |
| 复制命令后干嘛？ | 在**本机终端**粘贴运行，窗口保持打开 → 浏览器打开 `https://localhost:8002` 信任证书 → 回 Setup 点 **重新检测** → 变绿后去 **Robots → 进入向导**。 |
| 命令有效吗？ | 安装脚本来自官方仓库 `github.com/metahubaifeel/botversex-local-agent`；Linux 需 `python3-venv`、`dialout` 串口组。启动命令：`cd botversex-local-agent && source .venv/bin/activate && python run_api.py` |
| 为什么在 Setup 和 Robots 之间跳？ | 先装 Agent（Setup），再选机器人进向导（Robots）。顺序不要反。 |

## 页面说明

| 路径 | 作用 |
|------|------|
| `/robots` | 选机器人；SO-101「进入向导」是主入口 |
| `/setup` | 检测/安装 Local Agent |
| `/robots/so101` | SO-101 四步向导（主闭环） |
| `/robots/reachy_mini` | Reachy Mini Lite；有无硬件都可用虚拟模式；高级抽屉有「规格与入门」 |
| `/robots/b601_rs` | B601-RS 机械臂；首用四步向导，日常 Stage+Tab 控制台 |
| `/datasets` | 查看已录制数据集 |
| `/training` | 发起训练（部分云训练需登录与 Qualia 配置） |
| `/models` | 模型列表 |
| `/teleop` | 遥操作（需 Agent + 硬件） |
| `/inference` | 推理运行 |
| `/workflow` | 工作流编辑器（部分节点为占位，内测勿当成品宣传） |
| `/login` | 登录/注册；内测期间功能开放，无支付 |

## Local Agent 安装要点（Linux 示例）

```bash
sudo apt update
sudo apt install -y git python3 python3-venv python3-pip python3-dev build-essential
sudo usermod -aG dialout $USER   # 执行后需重新登录

git clone https://github.com/metahubaifeel/botversex-local-agent.git
cd botversex-local-agent
python3 -m venv .venv && source .venv/bin/activate
pip install "torch>=2.2,<2.11" "torchvision>=0.17,<0.26" \
  --index-url https://download.pytorch.org/whl/cpu
pip install -r requirements.txt -i https://mirrors.aliyun.com/pypi/simple/
python run_api.py
```

然后：浏览器访问 `https://localhost:8002` → 信任自签证书 → Setup 页「重新检测」。

## 真 / 半真 / 内测勿宣传

- **真**：注册浏览、Setup 检测、SO-101 向导、Reachy 虚拟、本地 MLP 训练（需 Agent+数据）、Copilot 诊断。
- **半真**：Qualia 云端训练（需平台配置 token）。
- **占位/勿宣传**：Workflow 部分 ApiPending 节点、AI Hub 深度集成、Marketplace、付费（已隐藏）。

## Copilot 自身

- 右下角 **「问问题」** 按钮：可问「Setup 下一步干嘛」「命令怎么用」「为什么连不上」。
- **系统诊断**  tab：自动检测 Agent、摄像头、串口等。
- **问答** tab：需登录（若已配置 AI 模型）；未配置时用 Playbook 规则回答。

## 故障速查

- Setup 一直未连接 → Agent 未启动 / 未信任证书 / 8002 被占用 / pip 安装失败。
- `/api/robots` 空白 → 云端 realtime 服务异常（用户侧只能刷新或联系管理员；**不要**告诉用户服务器路径）。
- 串口无权限 → `sudo usermod -aG dialout $USER` 后重新登录。
- B601 从臂软掉 → 在 `/robots/b601_rs` 点「唤醒从臂」，10 秒内开始遥操。
- B601 停止后仍有电机声 → 高级抽屉「从臂卸力」，或 Copilot 触发 `b601_run_recover` / disable。
- B601 3D 显示棍子/红点 → 检查 Agent 是否 `--http` 启动；`GET /api/b601/urdf/health` 应 30/30 mesh；缺 STL 需重装/同步 URDF 包。
- B601 热拔 USB HUB → 先停止遥操并卸力；Copilot 可引导 recover + disable 顺序。
- B601 CAN 未连接 → 运行一键安装器（含 systemd CAN 自启）或插入 PCAN-USB 后刷新页面。
- B601 运动学 / IK → 工作台「运动学」Tab；需先 `bash scripts/b601_pinocchio_install.sh`；默认 Dry-run 仅求解 IK。
- B601 手推漂浮 → 遥操页同屏；详见 `docs/b601-gravity-comp.md`；与遥操互斥，停止前扶住臂。
- B601 ROS2 → 高级面板 Launch bringup；需 `bash scripts/b601_ros2_install.sh`；与遥操互斥。
- Reachy「No motor / No Reachy motor」→ **本体电源必须打开**，只插 USB 不够；串口常见 `/dev/ttyACM0`。
- Reachy Lite vs 完整版 → BotverseX 接的是 **Lite**（外接电脑+USB）；完整版才有板载树莓派、WiFi、电池、加速度计。详见页面高级抽屉「规格与入门」或问「Reachy 规格」。
- Reachy 组装 → 套件约 2–3 小时；官方指南见 Seeed Wiki `reachymini_getting_started`。
- Reachy 对话/听不见 → 确认已「启动机器人」；对话 Tab 用官方 Conversation（默认 HuggingFace，可不填 Key）；麦克风阵列 4 个、喇叭 5W。
- Reachy HF App（Conversation / Hand Tracker / Radio）→ 官方 Dashboard 可装；BotverseX 对话/动作/视觉 Tab 覆盖常用能力。
- 摄像头 busy → 关闭占用摄像头的其他程序。
