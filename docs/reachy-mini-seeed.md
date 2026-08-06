# Reachy Mini — Seeed 官方要点（BotverseX 对照）

> 来源整理自 [Seeed Wiki · Reachy Mini 入门](https://wiki.seeedstudio.com/cn/reachymini_getting_started/)  
> 用途：产品内帮助、Copilot、客户上手。**不是**整篇 wiki 搬运。

## BotverseX 接的是哪一版？

默认对接 **Reachy Mini Lite**（外接电脑 + USB），不是带树莓派的「完整版」。

| | Lite（你们常用） | 完整版 |
|--|------------------|--------|
| 价格（官方标价） | ~$299 | ~$449 |
| 计算 | 外接 Mac/Linux（Windows 官方写「即将支持」；我们用 Allan SDK + Agent 硬接） | 板载 Raspberry Pi 4 |
| 连接 | **仅 USB 有线** | WiFi + 以太网 |
| 电源 | 有线 | 电池 + 有线（约 2–4h） |
| 加速度计 | 无 | 有 |
| 头 / 身体 / 天线 | 6-DOF 头 + 身体旋转 + 2 天线 | 同左 |
| 麦克风 / 喇叭 / 摄像头 | 4 麦 + 5W + 广角 | 同左 |
| 尺寸 / 重量 | 高约 28cm（睡眠约 23cm），宽约 16cm，约 1.5kg | 同左 |

## 官方硬件能力（和平台对照）

| 能力 | 官方 | BotverseX |
|------|------|-----------|
| `goto` / 动作播放 / 录制回放 | ✅ | ✅ |
| 虚拟模式（无真机） | 仿真需 `reachy-mini[simulation]` | ✅ 页面内虚拟模式 |
| 4 麦克风 + 5W 喇叭 | ✅ | ⚠️ 对话/音频链路已接一部分；Daemon 勿长期关音频 |
| 广角摄像头 | ✅ | ⚠️ 视觉 Tab / 手部跟踪进行中 |
| HF App（Conversation / Hand Tracker / Radio） | Dashboard 一键装 | ⚠️ Conversation 等已代理；完整 App 商店体验未齐 |
| 重力补偿 | SDK 支持（常需 Placo） | UI 有入口；部分固件/运动学后端不可用 |
| Web Dashboard | 官方自带 | 用 BotverseX `/robots/reachy_mini` |

## 官方 SDK 最快上手（对照用）

```bash
pip install reachy-mini
# 装 App 更快可装 uv；失败会回退 pip
```

```python
from reachy_mini import ReachyMini
from reachy_mini.utils import create_head_pose

with ReachyMini() as mini:
    mini.goto_target(
        head=create_head_pose(z=10, roll=15, degrees=True, mm=True),
        duration=1.0,
    )
```

仿真（无硬件）：

```bash
pip install reachy-mini[simulation]
```

BotverseX 日常路径**不必**手跑这些：页面点「启动机器人」即可拉起 daemon。

## 组装与上电（用户常踩坑）

- 套件组装约 **2–3 小时**；官方有[交互式组装指南](https://wiki.seeedstudio.com/cn/reachymini_getting_started/)。
- **只插 USB 不够**：本体电源必须打开，否则常见  
  `No Reachy motor on /dev/ttyACM0` / `No motor found`。
- Lite：典型供电约 **5V @ 2A**（USB 或墙插适配器）。
- 组装时可分段测：摄像头、麦克风、舵机。

## HF App 生态（值得接/值得演示）

| App | 做什么 |
|-----|--------|
| Conversation | 语音 + LLM + 动作（官方双工对话） |
| Hand Tracker | 视觉跟手 |
| Radio | 语音控电台 |

入口：Hugging Face Spaces，标签 `reachy-mini`。  
发布自家 App：建 Space → 加 `reachy-mini` 标签。

## 隐私（官方承诺，可对外说）

- 默认不收集、不上传个人数据到 Pollen / HF。
- 可全程本地处理；云服务需用户自己配置。

## 社区链接

- Seeed Wiki：https://wiki.seeedstudio.com/cn/reachymini_getting_started/
- 官网：https://www.pollen-robotics.com/reachy-mini/
- GitHub：`pollen-robotics/reachy_mini`
- Discord：Reachy Mini 官方 Discord

## BotverseX 页面入口

1. 启动 Local Agent（`:8002`）
2. 打开 http://127.0.0.1:5173/robots/reachy_mini
3. 有机：点「启动机器人」→ 动作 / 对话 / 视觉  
4. 无机：开「虚拟模式」体验动作
