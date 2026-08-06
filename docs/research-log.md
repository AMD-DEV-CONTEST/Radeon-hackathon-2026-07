# BotverseX 研究日志（Research Log）

> 由 30 分钟自主进化循环（loop cron）每轮追加：上网检索 → 摘要 → 与 BotverseX 的关系。
> 只记录**对项目有实际启示**的内容，噪声不入库。
> 相关：`docs/strategy/2026-07-31-product-truth-and-next.md`（执行权威）· `docs/webserial-design.md`（WebSerial 设计）

---

## 2026-08-06 · WebSerial（navigator.serial）能力盘点

**来源**：
- [Web Serial API: Browser Support, Features, Limits](https://www.testmuai.com/learning-hub/web-serial-api-browser-support/)
- [WebHID & WebSerial: Building Custom Hardware Interfaces in 2026](https://blog.weskill.org/2026/04/webhid-webserial-building-custom.html)
- [开源的在线串口调试助手（浏览器 webSerial）](https://blog.csdn.net/fengydongdong/article/details/156419813)

**要点**：
- 浏览器直连串口设备（USB/RS-232/BT），**零安装**：浏览器即驱动，无需原生 App / 驱动 / Python。
- 支持：Chrome 89+ / Edge 89+ / Opera 76+（Win/macOS/Linux/ChromeOS）；Chrome 148 beta 开始支持 Android（2026-04）；全球约 72%。
- **不支持**：Safari 全系、Firefox stable（Nightly 151 实验性 flag）。手机浏览器基本无。
- 约束：HTTPS（localhost 免）；`requestPort()` 必须用户手势触发；同一端口同时只被一个 tab 持有。
- API：`requestPort()` / `getPorts()` / `port.open({baudRate})` / `readable`·`writable`（Web Streams，实测可达 ~4 MB/s）/ `connect`·`disconnect` 事件。
- 同类先例：2026 年浏览器 IDE（CodeSpace 类）用 WebSerial 直接给 ESP32/Arduino 烧录——「零安装硬件控制」已是成熟范式。

**对 BotverseX 的启示**：
- 执行定义「不装 2.9GB Agent 让人第一次让机械臂动起来」的技术答案是**现成的**：WebSerial 就是那条路，72% 桌面浏览器覆盖对早期验证足够。
- 降级路径明确：Safari/Firefox 用户提示改用 Chrome/Edge，不做浏览器全支持承诺。
- 单 tab 持有端口 → 产品上就是「一台电脑一个浏览器控制一条臂」，正好匹配单机 demo 场景。

---

## 2026-08-06 · LeRobot + Feetech STS3215 生态：控制协议与已知坑

**来源**：
- [LeRobot — Bring Your Own Hardware](https://huggingface.co/docs/lerobot/v0.5.0/en/integrate_hardware)
- [lerobot/docs/source/integrate_hardware.mdx](https://github.com/huggingface/lerobot/blob/main/docs/source/integrate_hardware.mdx)
- [so101.mdx](https://raw.githubusercontent.com/huggingface/lerobot/49755a3d9e7d43ae93092de8324e75348955afab/docs/source/so101.mdx)
- [Feetech sts3215 serial servos read failure · huggingface/lerobot#526](https://github.com/huggingface/lerobot/issues/526)
- [lerobot-kinematics: Real Hardware Control](https://deepwiki.com/box2ai-robotics/lerobot-kinematics/5.2-real-hardware-control)

**要点**：
- LeRobot 内置 `FeetechMotorsBus` 支持 STS3215（SO-100/SO-101 即 6× STS3215：shoulder_pan/lift、elbow_flex、wrist_flex/roll、gripper）。
- 串口配置标准：`lerobot-find-port` → `lerobot-setup-motors` 分配唯一 ID（1–6/8）→ **波特率 1,000,000** → `lerobot-calibrate`。
- 已知坑：STS3215 读失败（Incorrect status packet / checksum error）根因常是**电机 ID 未唯一化**（issue #526）。
- 社区 fork（lerobot-kinematics）有 `connect_arm()/action(qpos_rad)/feedback()` 封装，弧度→度→协议转换 + 关节方向翻转。
- **WebSerial/JS 侧没有官方实现**——LeRobot 生态全是 Python 串口路径。

**对 BotverseX 的启示**：
- 好消息：仓库 `apps/realtime/dora-bambot/_next/static/chunks/881-47c588f365fe1541.js` 里已有**完整浏览器 Feetech 实现**（baud 1e6、0x02 读/0x03 写/0x82 同步读、广播 ID 254 保护、校验和 ~Σ&0xFF、txRx 超时与 txTimePerByte 时序）——直接移植成类型化 TS 模块即可，不用从零发明协议。
- 协议与 LeRobot Python 侧一致 → WebSerial 录的数据天然可对接现有 Record/Dataset 管线。
- 坑提前写进设计：WebSerial 直连前必须先检测/提示电机 ID 唯一（沿用 `ping 1..N` 逐 ID 检测的既有纪律）。
- **适用边界（不吹跨机型）**：WebSerial 直连仅覆盖 Feetech 总线（SO-101 主线）；Reachy（Dynamixel/U2D2）与 B601（Robstride CAN）不属于本路径。

---

## 2026-08-06 · 对标：LeLab（HF 官方 LeRobot 浏览器 GUI）

**来源**：[huggingface/leLab](https://github.com/huggingface/leLab) · [LeLab — LeRobot Guide](https://huggingface.co/docs/lerobot/main/en/lelab) · [Hackster 报道](https://www.hackster.io/news/lelab-is-hugging-face-s-new-browser-based-gui-for-the-lerobot-ecosystem-d73ff19088f6)

**要点**：
- HF 官方为 LeRobot 生态做的网页 GUI，把 calibrate/teleoperate/record/train/replay/upload 收敛进一个浏览器界面，目标「开箱到训出第一个策略只要几分钟」。
- 安装方式：`uv tool install git+.../leLab.git && lelab`（**仍需终端 + uv，不是真·零安装**）；当前仅兼容 SO-101。
- UX 亮点：引导式标定（无键盘命令）、遥操实时 3D、录制（任务描述/集数/时间）、本地+HF 云训练（透明计价）、一键推理部署、一键盘点上传 HF。

**对 BotverseX 的启示**：最强对标。UX 流程是行业门槛，必须追平（引导式、3D、一键闭环）；但 LeLab 不是浏览器直连——我们 WebSerial 的「真零安装」仍是差异化线。竞争策略 = UX 向它看齐 + 技术差异保持。

---

## 2026-08-06 · 对标：PrismaX（a16z）与 zero2robot 等浏览器优先平台

**来源**：[PrismaX 报道](https://founderland.ai/articles/prismax-launches-robot-teleoperation-platform-with-a16z-back-mp0yyvyv) · [zero2robot](https://github.com/kaushikb11/zero2robot) · [Mirai](https://github.com/Mizunandayo/mirai) · [Artifex](https://devpost.com/software/artiflex)

**要点**：
- PrismaX（a16z，2025-08 发布）：打开网址→口令→排队→浏览器操作真机（8 种机型），Q1 2026 持续改排队/流初始化/控制中心 UX——「入口极简」的验证。
- zero2robot：43 章无机器人课程，每章一个可跑文件 + MuJoCo-WASM 浏览器 demo——「没有机器人也能开始」。
- Mirai/Artifex：浏览器仿真 + 自然语言指令，想法→机械臂动→导出——虚拟路径可作第一动作的低成本替代入口。

**对 BotverseX 的启示**：全行业 2026 年共同动作 = 把「连接与配置」从用户任务里拿掉（hermes 判断的行业验证）；虚拟路径（我们已有 Reachy virtual）是零硬件用户的正确入口；详见 `docs/strategy/2026-08-06-first-move-experience.md`。

---

## 格式模板（后续每轮追加）

```
## YYYY-MM-DD · 主题
**来源**：URL
**要点**：3–6 条
**对 BotverseX 的启示**：1–3 条（没有启示就不写这条，说明为什么）
```

---

## 2026-08-06 · LeRobotDataset 磁盘格式（episodes.jsonl / parquet 列 / v2 vs v3）

**来源**：[Dataset Format and Structure | huggingface/lerobot (DeepWiki)](https://deepwiki.com/huggingface/lerobot/2.1-dataset-format-and-structure) · [LeRobot compatible data schema (GR00T)](https://raw.githubusercontent.com/mschweig/isaac-gr00t/refs/heads/main/getting_started/LeRobot_compatible_data_schema.md)

**要点**：
- 磁盘布局：`meta/info.json` + `meta/episodes.jsonl` + `data/chunk-000/episode_*.parquet`（v2）；v3 改为多集 shard + `meta/episodes/` 边界文件。
- parquet 核心列：`observation.state`（1D 拼接数组，由 features/modality.json 切片映射命名）、`action`、`timestamp`（episode 内秒）、`episode_index`、`frame_index`、`index`、可选 `next.done`。
- `timestamp ≈ frame_index / fps`；`action` 记录的是导致下一帧观察的动作。
- 相机图像不进 parquet，走 `videos/chunk-*/observation.images.*/*.mp4` + 路径+时间戳引用。

**对 BotverseX 的启示**：U3 首录端点直接采用 LeRobot 风格列（index/episode_index/frame_index/timestamp/observation.state/action），S5 完整对齐（相机/任务/多集）时无需重写数据模型；`_summarize` 与 botclaw.json 是 BotverseX 自有索引层，与 LeRobot v3 布局（`meta/info.json` + data/**/*.parquet）两轨并行，扫描逻辑已兼容。

---

## 2026-08-06 · 对标复查：LeLab 无新版本（差异化主张仍成立）

**来源**：[Hackster 报道](https://www.hackster.io/news/lelab-is-hugging-face-s-new-browser-based-gui-for-the-lerobot-ecosystem-d73ff19088f6)（首发报道，检索无 2026 新 changelog）

**要点**：LeLab 自首发后无公开新版本/Changelog；仍是「uv 本地起服务」形态，无 WebSerial 浏览器直连。功能面（引导式标定/3D/一键录制训练部署）与我们此前记录一致。

**对 BotverseX 的启示**：我们的「真·零安装浏览器直连」差异线在 2026-08 仍无人追平。但窗口不会永远开着——访谈门禁（M40）越早跑，差异线的验证越早落地。

---

## 2026-08-06 · 市场验证：恺望数据（Kaiwang Data）逾亿元战略融资

**来源**：[TechNode 报道](https://technode.com/2026/08/05/embodied-ai-data-infrastructure-startup-kaiwang-data-raises-more-than-rmb100-million/) · [上海证券报](https://www.cnstock.com/commonDetail/755252) · [证券时报](https://www.chnfund.com/article/AReead0499-25fb-c6f6-d4b7-3a22df276095)

**要点**：
- 2026-08-04：具身智能全链数据基础设施公司恺望数据完成**逾 1 亿元**战略融资（亦庄产业基金/华方资本/天际资本联合领投）；鹿明、松延、自变量、智元系觅蜂等具身公司作为股东入场。
- 业务：数据定义/场景采集/标注加工/数据交易一体化；月产可用数据约 10 万小时（行业此前门槛 1 万小时）；已签多家批量采购。
- 市场叙事：数据成为具身智能落地瓶颈；从结构化道路场景进入开放真实环境，高质量交互数据需求暴增。

**对 BotverseX 的启示**：这是**最高纲领核心判断的市场级验证**——「未来机器人智能的瓶颈是高质量真实世界数据」正在被资本用真金白银确认。定位差异：恺望做企业级规模化数据服务（数据工厂），BotverseX 做「让普通人从真实场景产生数据」的入口（第一站）。两者不冲突，反而互补：投资人叙事里可以说「数据是瓶颈（已有人做工厂），我们做把场景变成数据的第一站」。可用于 M31 之后的融资材料更新。

---

## 2026-08-06 · 竞品：Hephasbot + 浏览器跑真策略（SO-101 浏览器控制赛道升温）

**来源**：[Hephasbot — Product Hunt](https://www.producthunt.com/p/hephasbot) · [three.js 论坛：真实策略 100% 浏览器内运行 SO-101](https://discourse.threejs.org/t/a-real-robot-policy-neural-net-physics-running-100-in-the-browser-so-101-arm-three-js-r3f/92415)

**要点**：
- **Hephasbot（2026-03 上线 Product Hunt）**：网页控制 SO-101——手动关节/键盘/鼠标/手柄/主从，宣称「免下载」；可存标定配置跨设备复用。机制未公开为 WebSerial（大概率本地辅助服务/WebSocket），但「浏览器免下载控 SO-101」的定位与我们正面重叠。
- three.js 论坛 2026-06-26 展示：ACT 策略（LeRobot 训练，~16M 参数）**100% 在浏览器内运行**（onnxruntime-web + MuJoCo-WASM），驱动虚拟 SO-101——「大脑和身体都在你的标签页里」。
- LeLab 仍无新版本（本日复查）。

**对 BotverseX 的启示**：
- 差异线不能只靠「浏览器直连」的技术事实：Hephasbot 已经把「免下载控 SO-101」做成产品话术。我们真正的护城河候选是**数据闭环入口**（首录→训练→部署回真机）而非单点直连——U3 首录 + 后续训练闭环比「遥控器」更接近纲领。
- 浏览器内跑策略（onnxruntime-web）是未来方向：WebSerial 直连 + 浏览器推理 = 「零安装全闭环」的终局形态，写入 roadmap 观察项（不提前做）。
- 访谈门禁的紧迫性 +1：赛道在升温，差异化验证要快。

---

## 2026-08-06 · 开源社区调研（全 runtime：文档/社区/新手高频问题）

**来源**：[lerobot so101 文档](https://huggingface.co/docs/lerobot/so101) · [SO-101 issue #1244](https://github.com/huggingface/lerobot/issues/1244) · [issue #1010](https://github.com/huggingface/lerobot/issues/1010) · [reachy_mini 仓库](https://github.com/pollen-robotics/reachy_mini) · [Seeed B601 wiki](https://wiki.seeedstudio.com/cn/rebot_arm_b601_rs_lerobot/) · [SIGRobotics-UIUC/LeKiwi](https://github.com/SIGRobotics-UIUC/LeKiwi) · [Unitree G1 开发者文档](https://support.unitree.com/home/en/G1_developer) · [LeKiwi+PincOpen 博客](https://huggingface.co/blog/zuoxingdong/mobile-manipulation-lekiwi-pincopen)

**要点**（每机型 → 平台页面已落地为 CommunityResources 区块）：
- SO-101：LeRobot Discord（discord.gg/q8Dzzpym3f 为当前链接，仓库历史有 3 个版本需验证）；HF Hub 58,000+ lerobot 数据集大多录自 SO 系；高频坑 = ID 唯一化 / 12V 过压（额定 7.4V）/ 固件 3.9 vs 3.10 / chmod 666。
- Reachy Mini：官方 Discord + forum.pollen-robotics.com；高频坑 = daemon 卡死（Lite）、Zenoh 7447 端口转发、电机红灯（插错槽）、麦克风 FPC 排线反。
- B601-RS：Seeed wiki/论坛/discord.seeed.cc；**RS 变体 LeRobot 支持未完整**（robstride CAN 未接入，走 socketcan）；预装套件禁重写电机 ID；CAN bitrate 1M 配置顺序；ID 映射表；禁热插拔 XT30。
- LeKiwi：社区依托 LeRobot Discord mobile-so100-arm 频道；ZMQ 无鉴权（#890）、Feetech 瞬态读错误（PR #4207）、校准前配 ID（#1042）。
- Unitree G1：官方社区入口少（GitHub Issues 为主，无公开 Discord——如实标注）；SDK 需 EDU 版；固定 IP 网段 192.168.123.x；价格 $16k+。

**对 BotverseX 的启示**：① CommunityResources 组件（文档/社区/FAQ 三块，details 折叠）已在 SO-101/B601/LeKiwi 三页落地，Reachy 与 G1/AmazingHand 待补；② FAQ 答案带 issue 编号（#1244 等）是社区信任的来源标注；③ G1 无社区入口就如实写，不编 Discord 链接；④ 链接会过期（Discord 邀请）——上线前需验证，维护成本计入 roadmap。

---

## 2026-08-06 · STS3215 舵机层社区高频故障（SO-101/B601 同款总线舵机）

**来源**：[lerobot issue #1010 — Incorrect status packet](https://github.com/huggingface/lerobot/issues/1010) · [beam-bots bb_so101 标定指南](https://github.com/beam-bots/bb_so101/blob/main/documentation/how-to/calibrate-servos.md) · [hackster.io STS3215 设置指南](https://www.hackster.io/ian-hong/feetech-serial-bus-servo-sts3215-setup-guide-fd16aa) · [DeltaEngine/FeetechStsServos](https://github.com/DeltaEngine/FeetechStsServos)

**要点**（「Incorrect status packet」的已知成因 = 我们 SerialDiagnostics 的诊断树）：
- **过压报警**：7.4V 电机接到 12V → 每个电机小红灯闪、通信报错。额定 6–7.4V。
- **固件版本不一致**：同总线混装 3.9/3.10 → status packet 错误甚至反转；官方 FT SCServo Debug（Win）/ Kotakku 的 Qt 移植（Linux/macOS）刷固件。
- **ID 重复**：出厂全部 ID=1，菊花链必须逐个接线分配 ID，否则只有一个舵机响应。
- **Linux 端口权限**：`chmod 666 /dev/ttyACM0` 是最常见新手坑。
- **标定**（离线扭矩校准法）：全舵机关扭矩 → 手掰每个关节走满机械行程 → 工具算 midpoint → `offset = 2048 − midpoint` 写 EEPROM（有符号格式 bit15=sign），断电不丢。范围太小 = 没掰够；模型错位看 URDF 拓扑而非 offset。
- **抖动/抽搐**：多为供电不足（换台式电源），或 GND 未共地/波特率错/固件混装。

**对 BotverseX 的启示**：
- SerialDiagnostics 的诊断树可加两条：① 12V 过压提示（电压读数 >7.4V 报警）；② 固件版本一致性检查（读 firmware version 寄存器对比）。
- 标定是 WebSerial 主线「零安装」的下一个自然闭环：浏览器里关扭矩 + 读 min/max + 写 EEPROM offset —— 现协议层已具备（setTorque/readPosition/writeRegister），可做成「浏览器标定向导」候选（等访谈信号，不提前做）。
- FAQ 区块可补充：ID 重复、chmod 666、供电抖动三条 —— SO-101/B601 页面共享。
