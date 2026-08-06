# 1. NDJSON 帧格式契约

> 协议：换行分隔的 JSON（Newline-Delimited JSON），一行一条 JSON-RPC 消息。
> TCP、Unix socket、Serial 传输通道共用此帧格式。
> 实现源码：`crates/infra/src/transport/framed.rs`

## 1.1 帧规则

- **一行一条消息**：写端序列化 `JsonRpcMessage` 为 JSON 字节，追加 `\n`，`write_all` + `flush`。
- **换行分隔**：读端遇 `\n` 视为一行完成。
- **CRLF 兼容**：读端 `trim_eol` 先剥尾部 `\n`，再剥可选 `\r`。CRLF 行可正常解析。
- **空行跳过**：trim 后为空行不报错，跳过继续读。
- **EOF 无换行**：连接关闭时若缓冲有未以 `\n` 结尾的尾巴，当作最后一条完整行解析；缓冲空则干净 EOF。

## 1.2 消息大小限制

单行 JSON 最大 **4 MiB**（`MAX_MESSAGE_BYTES = 4 * 1024 * 1024`，`shared/src/protocol/mod.rs:19`）。
超限的行：
- 读端返回 `FrameError::TooLong(len, MAX_MESSAGE_BYTES)`。
- 守护进程会断开该连接。
- 调用方应避免发送超大消息（`exec_shell` 的 `cmd`、`get_state` 的响应通常远小于此）。

## 1.3 字符编码

UTF-8。`serde_json` 默认 UTF-8，不处理 BOM。

## 1.4 最小交互

```sh
# 用 nc 连守护进程，每行发一条请求
echo '{"jsonrpc":"2.0","id":1,"method":"ping"}' | nc board 7777
# → {"jsonrpc":"2.0","id":1,"result":{"pong":true,"ts":"..."}}
```

## 1.5 多消息

一行一条，可连续发：
```sh
printf '{"jsonrpc":"2.0","id":1,"method":"ping"}\n{"jsonrpc":"2.0","id":2,"method":"get_thermal"}\n' | nc board 7777
```
守护进程逐行返回两条响应。

## 1.6 错误处理

- JSON 解析失败（非合法 JSON-RPC）：`FrameError::Serde`，守护进程记 warn 并可能断开。
- IO 错误：`FrameError::Io`。
- 行超长：`FrameError::TooLong`。

调用方收到非预期断开时，应重连并重发未完成的请求。

## 1.7 与 WebSocket 出站的关系

WebSocket 传输**不用** NDJSON——WS 帧自带边界，一帧一条 JSON-RPC 文本，无需 `\n` 分隔。
见 [`ws-outbound.md`](ws-outbound.md)。
