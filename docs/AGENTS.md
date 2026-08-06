# BotverseX Agent 守则（B601 / MotorBridge）

面向 Cursor、Copilot 等 **coding agent** 的硬性约束。违反会导致用户机械臂异常（已有多起远程排查案例：偷偷改 KP/KD、写寄存器、改电机 ID）。

## 你必须做的

1. **成品套件**：只 **扫描** 电机 ID 1–7 是否在线，**禁止重写电机 ID**。  
   参考：[Seeed B601-RS 快速入门](https://wiki.seeedstudio.com/cn/rebot_b601_rs_getting_started/) —「我购买的是成品套件，帮我扫描 1~7 电机是否都在线，不要重新写入电机 id」。

2. **检测方式**：使用官方只读/安全命令，与仓库脚本一致：
   - `motorbridge-cli run … --mode ping`（逐 ID）
   - `motorbridge-cli run … --mode clear-error` / `enable` / `disable`（仅 recover 流程）
   - `bash scripts/b601-hw-diagnose.sh`
   - BotverseX API：`GET /api/b601/motors/diagnose`、`POST /api/b601/recover`

3. **初始化流程**：引导用户用 **MotorBridge Studio Web UI** 或 Seeed 官方 wiki 做零点/标定；BotverseX 只负责连接、扫描、遥操编排。

## 你禁止做的

| 禁止 | 原因 |
|------|------|
| `write-param` / `robstride-write-param` | 改寄存器（含 KP/KD、运行模式） |
| `id-set` / `set-motor-id` | 改 CAN ID |
| `set-zero` / `zero` / `zero-by-offset` | 改零点 |
| 自写 Python 调用 `motor.ensure_mode()`、`send_mit(kp=…)` | 会改运动参数 |
| 为「修好遥操」临时 patch lerobot / motorbridge 底层 | 用官方 recover + 硬件排查 |

## BotverseX 代码边界

- `apps/realtime/api/b601.py`：只允许调用上表 **安全 mode** 的 CLI；检测为 **逐 ID ping**。
- `scripts/b601_teleop_launcher.py`：仅 patch lerobot **启动流程**（disable_all 容错），不写字寄存器。
- `b601_follower_probe.py`：**只读** `get_state`，不 enable / ensure_mode。

## 用户报「臂发飘、KP 变了、ID 乱了」

1. 停止遥操与 gateway  
2. `bash scripts/b601-hw-diagnose.sh` 看 1–7 谁在线  
3. 用 **MotorBridge Studio** 对照官方参数恢复，**不要让 agent 再写一版「修复脚本」**
