---
name: servo-control
description: 通过 sophonctl 安全地测试和控制 MagicBox 舵机动作。
---

# MagicBox 舵机控制

## 适用场景

当用户要求测试或控制 MagicBox 舵机时使用本 Skill。当前支持：

- `init`
- `lift-left`
- `lift-right`
- `lower-left`
- `lower-right`
- `stand`
- `relax`
- `shake-ears`
- `flash`
- `servo <index> <duty>`
- `remove <动作名>`（管理 rdk-agent 已交付的动作，不驱动舵机）

## 安全规则

1. 在机器人应用模式中，动作式自然语言就是对映射动作的一次执行授权；无需再次询问。仅询问能力、命令或状态时不得驱动舵机。
2. 如果用户明确报告机器人不稳、运动路径有障碍物或其他危险，则停止动作并报告原因。
3. 先只读执行 `sophonctl plugins list`，确认存在 `id: servo`。
4. 不把 `--hold inf` 用作默认值；只有用户明确要求持续保持并知道可用 Ctrl-C 中止时才能使用。
5. `servo <index> <duty>` 缺少 index 或 duty 时必须请求人类输入，不能猜测。
6. 一次只执行一个动作，不并行发送舵机命令；失败后不重复原动作。
7. `remove <动作名>` 是破坏性维护操作：仅在用户明确指定要删除的动作名时执行；它只接受 rdk-agent 托管动作，内置动作和不存在的动作会被拒绝。成功后必须回传备份路径。

## 前置检查

```bash
sophonctl plugins list
sophonctl servo --help
```

指定板子时，把全局参数放在插件名前：

```bash
sophonctl --board x5 plugins list
sophonctl --board x5 servo --help
```

插件不存在、板子不可达或帮助输出不包含目标动作时停止，并报告真实错误。

## 应用模式执行流程

动作式请求且前置检查通过后，直接执行唯一映射命令一次，不得停在列表或帮助检查。例如“摇一下耳朵”：

```bash
sophonctl servo shake-ears
```

指定 X5 时执行：

```bash
sophonctl --board x5 servo shake-ears
```

每一步等待命令结束并检查响应：`exit` 必须为 `0`，`stderr` 应为空，非空 `stdout` 应回传给用户。命令失败时停止并报告真实输出。

## 自然语言到命令映射

| 用户意图 | 命令 |
|---|---|
| 初始化舵机 | `sophonctl servo init` |
| 左腿抬起 | `sophonctl servo lift-left` |
| 右腿抬起 | `sophonctl servo lift-right` |
| 左腿放下 | `sophonctl servo lower-left` |
| 右腿放下 | `sophonctl servo lower-right` |
| 站立 | `sophonctl servo stand` |
| 放松/卸力 | `sophonctl servo relax` |
| 摇耳朵 | `sophonctl servo shake-ears` |
| 灯光动作 | `sophonctl servo flash` |
| 灯光动作但不操作灯带 | `sophonctl servo flash --no-lamp` |
| 删除已交付的二级动作 `<name>` | `sophonctl servo remove <name>` |

动作完成后的默认保持时间由插件决定。需要有限保持时使用 `--hold <秒数>`；镜像机器人只有在人类确认需交换引脚时才使用 `--exchange`。

## 单舵机操作

只有用户同时提供 index 和 duty 时才执行：

```bash
sophonctl servo servo <index> <duty>
```

不得自行推断插件未声明的安全范围。

## 结果报告

报告实际板子、执行命令以及每步的 exit/stdout/stderr。命令输出无法证明物理位移时，必须写“命令执行成功，物理效果待人类确认”，不能自行声称舵机动作正确。
