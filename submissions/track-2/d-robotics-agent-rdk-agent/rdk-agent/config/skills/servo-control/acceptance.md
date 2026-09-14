# Servo-Control Skill 验收场景

## 自然语言触发映射

- “摇一下耳朵”唯一映射为 `sophonctl servo shake-ears`。
- 指定 X5 时映射为 `sophonctl --board x5 servo shake-ears`。
- 动作式输入不需要二次确认；能力、命令或状态查询不得驱动舵机。

## 参数边界

- 入口源码为所有动作提供 `--hold`、`--exchange` 和 `--no-lamp` 通用选项；默认不使用 `--hold inf`。
- `servo <index> <duty>` 缺少 index 或 duty 时必须请求人类输入，不能猜测。

## 静态合同与测试证据

- `test_cli_contract.py` 中的 `test_plugin_manifest_valid` 验证 manifest 的 api_version、id 和 entrypoint。
- `test_cli_contract.py` 中的 `test_start_left_does_not_touch_right_pwm` 验证左侧启动不会触碰右侧 PWM。
- `test_cli_contract.py` 中的 `test_lower_left_starts_only_left_pwm` 验证 `lower-left` 仅启动左侧 PWM。

## 失败与安全场景

- 前置的 `sophonctl --board x5 plugins list` 未发现 `id=servo` 时停止，不执行动作。
- CLI 返回非零 exit 或 stderr 时停止并回传真实结果，不自动重试物理动作。
- Skill 必须保留已有动作、一次只执行一个动作，并且不得绕过 sophonctl 直接访问硬件。

## 真机边界

- mock 测试只能证明 CLI 分发和左右通道隔离，不能证明真实舵机的角度、力度或实际位移。
- 实际物理效果仍需最终真机阶段由人类目视确认；CLI 的 exit=0 只证明命令链路成功。
