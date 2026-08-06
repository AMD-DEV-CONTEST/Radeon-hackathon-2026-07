# MagicBox 舵机原子能力与验收边界

## 已从板端源码确认的事实

- PWM 频率为 50Hz，一个周期约 20ms。
- `lift_left`、`lift_right`、`lower_left`、`lower_right` 在更新占空比后只等待 50ms，约等于 2.5 个 PWM 周期。这段等待用于原子状态切换，不是复合动作的可见姿态保持时间。
- 板端参考实现 `/userdata/magicbox/basic_function_demo/servo.py` 会让目标占空比保持约 2 秒；长生命周期的 C++ 控制进程也不能直接等同于一次执行完即清理 PWM 的 CLI 进程。
- 当前 MagicBox gesture 配置启用 `need_exchange=True`。应用脚本按当前装配约定使用左侧 BOARD 33、右侧 BOARD 32；如果设备配置改变，必须以实际板端配置为准，不能仅凭变量名重新交换。

## 复合动作契约

- “抬起再放下”“挥动”必须包含 `lift → visible hold → lower`，默认 `WAVE_POSITION_HOLD_SECONDS = 0.8`。
- 静态入口在 lift/lower 之间直接使用共享常量等待；托管动作包必须调用控制器的 `hold_visible_position()`，不要在动作模块中复制魔法数字。
- CLI 的通用 `--hold` 发生在完整动作执行之后。它只能保持最终姿态，不能代替 lift 与 lower 中间的可见停留。
- 单侧动作必须只启动目标侧 PWM。静态动作由 `LEFT_ONLY_ACTIONS`/`RIGHT_ONLY_ACTIONS` 表达；托管动作由 `servo_actions/<动作 ID>/registry.json` 的 `start` 表达。

## 自动验收能证明什么

- mock/TDD 可证明动作映射、调用顺序、可见停留调用和左右侧隔离。
- 部署回执可证明目标路径、哈希和备份。
- `sophonctl` 返回 exit=0 只证明命令经过插件和板端脚本完成，不能证明舵机轴真实移动到目标位置。
- PTK 7465 MG-D 的内部位置闭环属于舵机本体控制，不等于主控获得编码器读数。本链路没有位置遥测时，不得声称已经测量物理位移，也不得因缺少该反馈阻塞自动研发流程。
