---
name: magicbox-command-authoring
description: 为 MagicBox 舵机控制实现符合现有代码规范、可交付且可移除的新指令。
---

# MagicBox 指令开发

目标项目默认是 rdk-agent 从内置版本化模板初始化的托管工作区，不要求用户下载 rdk-sophon 源码；仓库贡献者也可以显式提供外部工作区。舵机插件统一位于工作区的 `examples/plugins/servo/`。先阅读现有 `servo_ctrl.py`、相邻测试和板端 `/userdata/magicbox` 中能从代码证明的原子能力，只复用已有硬件接口。

内置动作只能修订现有入口。新增 rdk-agent 交付动作必须使用独立动作包：

- 先用 `tools/servo_action.py new <kebab-case 动作名>` 创建 `examples/plugins/servo/servo_actions/<动作名>/`；不要手工创建目录或脚手架文件。
- 每个动作包拥有自己的 `registry.json`，契约为 `schema: rdk-servo-action/v1`、同名 `id`、`entrypoint: action.py:run` 和 `start` 策略（`left`、`right`、`both` 或 `none`）。
- 实现只写在同目录 `action.py`，且只导出 `run(context, params)`；通过 `context` 调用硬件桥接能力，禁止导入任何模块。
- `rdk-servo-action/v1` 只支持无参数动作，`arguments` 必须为 `[]`。实现必须是同步、顺序的无参数桥接调用；允许的方法只有 `init_position`、`lift_left`、`lift_right`、`hold_visible_position`、`lower_left`、`lower_right`、`wave_hands`、`stand`、`relax`、`shake_ears` 和 `flash`。参数化用户指令必须先升级契约，不得静默忽略。
- `servo_ctrl.py` 自动扫描一级动作包目录；不要修改静态 `ACTIONS`，也不要维护全局动作注册表。
- 用户可用 `sophonctl servo remove <动作名>` 原子下线整个动作包；活动目录会移入 `.rdk-agent-backups/` 以便恢复。
- 验证返工时复用已存在的动作包，只修改测试或 `action.py` 所属阶段拥有的文件；不得再次调用脚手架覆盖或重复创建目录。

新增用户能力时必须创建独立、可兼容的公开动作，不能改变已有动作的语义。Python 方法使用 snake_case，CLI 动作使用对应的 kebab-case；测试必须调用这个公开入口，不能直接调用底层 lift/lower 后声称已覆盖新功能。

单侧动作除了动作顺序，还必须证明不会启动另一侧 PWM。任何自动测试都要在导入脚本前同时向 `sys.modules` 注入 `Hobot` 与 `Hobot.GPIO`。

开发沙箱是离线 Python 3.12 标准库环境，不提供 pytest。测试使用 `unittest`，从动作包目录运行 `python3 -m unittest discover -s tests -v`；不安装依赖。动作包的脚手架、契约校验和 release 构建由 `tools/servo_action.py` 固化执行，不能靠 LLM 复制目录结构。
