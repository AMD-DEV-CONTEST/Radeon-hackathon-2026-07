# 4. JSON-RPC 错误码契约

> 守护进程在 Response 的 `error.code` 中返回的标准 JSON-RPC 错误码 + 应用扩展码。
> 外部调用方据此判错与重试。
> 实现源码：`crates/shared/src/protocol/message.rs:90-105` 的 `ErrorCode`（`#[repr(i32)]`）

## 4.1 错误对象结构

```json
{
  "jsonrpc": "2.0",
  "id": <同请求>,
  "error": {
    "code": <int>,
    "message": "<string>",
    "data": <可选>
  }
}
```
- `code`：整数，见下表。
- `message`：人类可读描述。
- `data`：可选附加数据（当前路径不填充，省略不序列化）。

## 4.2 错误码表

### JSON-RPC 2.0 标准码（协议层）

| code | 常量 | 含义 | 当前触发情况 |
|------|------|------|------------|
| -32700 | `ParseError` | JSON 解析失败 | 协议层兜底（dispatcher 未显式触发） |
| -32600 | `InvalidRequest` | 请求非法 | 协议层兜底 |
| -32601 | `MethodNotFound` | 未知方法名 | `rpc_dispatcher.rs:87`（`call` 的 `other` 分支） |
| -32602 | `InvalidParams` | 参数缺失/类型错 | `rpc_dispatcher.rs:102,104`（`exec_shell` 缺 `cmd`） |
| -32603 | `InternalError` | 内部错误 | 协议层兜底 |

### 应用扩展码（-32000 ~ -32099）

| code | 常量 | 含义 | 触发点 | HTTP 网关映射 |
|------|------|------|--------|--------------|
| -32000 | `ExecError` | shell 执行失败（非超时） | `rpc_dispatcher.rs:135` | 500 |
| -32001 | `ShellDisabled` | shell 未在配置启用 | `command_policy.rs:52-55` | 403 |
| -32002 | `ShellDenied` | 命令命中 deny 列表 | `command_policy.rs:57-62` | 403 |
| -32003 | `Timeout` | 命令执行超时 | `rpc_dispatcher.rs:134` | 504 |
| -32004 | `RateLimited` | 限流 | 已定义，**当前未触发** | 429 |

## 4.3 各方法的可能错误

| 方法 | 可能错误码 |
|------|-----------|
| `ping` | （无错，恒成功） |
| `get_state`/`get_thermal`/.../`get_bpu` | `MethodNotFound`(-32601) 仅当方法名拼错；正常无错 |
| `refresh_state` | `MethodNotFound` 仅当拼错 |
| `exec_shell` | `InvalidParams`(-32602) 缺 `cmd`；`ShellDisabled`(-32001) 未启用；`ShellDenied`(-32002) 命中 deny；`Timeout`(-32003) 超时；`ExecError`(-32000) 其它执行失败 |
| `plugin.invoke` | `InvalidParams`(-32602) 参数错误或插件不存在；`Timeout`(-32003) manifest 超时；`ExecError`(-32000) manifest/启动/等待失败 |
| 未知方法 | `MethodNotFound`(-32601) |

## 4.4 调用方重试建议

| 错误码 | 是否重试 | 建议 |
|--------|---------|------|
| -32700/-32600/-32602 | 否 | 请求本身有问题，修正后重发 |
| -32601 | 否 | 方法名错，检查拼写 |
| -32001 | 否 | 服务端配置问题，联系板端运维启用 shell |
| -32002 | 否 | 命令被拒，改用允许的命令 |
| -32003 | 视情况 | 超时，可缩短命令或提高 timeout 后重试 |
| -32000 | 视情况 | 执行失败，看 stderr 诊断 |
| -32603 | 有限重试 | 偶发内部错误可重试一次 |

## 4.5 deny 列表（影响 ShellDenied）

内置 deny 子串（**不可被配置削弱**，`crates/domain/src/command_policy.rs:10-17`）：
- `"rm -rf /"`
- `"mkfs"`
- `"dd if=/dev/zero of=/dev/"`
- `":(){ :|:&"`（fork 炸弹）

配置 `shell.deny_patterns` 可**追加**模式（只能收紧）。命令若 `contains` 任一模式即 `ShellDenied`。
