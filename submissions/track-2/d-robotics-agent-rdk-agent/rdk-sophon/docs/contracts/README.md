# 1. 对外契约文档总览

> **这是外部调用方与 rdk-sophon 守护进程交互的唯一依据。**
> 契约文档必须真实、可用、好理解、全面——外部依赖这些文档接入选型、构造请求、解析响应、处理错误。

## 1.1 文档组织

按**协议**分目录，每协议内按**关注点**分文件（不把太多东西堆一个文件）：

```
docs/contracts/
├── README.md              # 本文件：总览 + 如何用 + 版本约定
├── jsonrpc/               # JSON-RPC 2.0 契约（最核心）
│   ├── envelope.md        # 信封结构（Request/Response/Notification）
│   ├── methods.md         # 所有 RPC 方法（params + result）
│   ├── notifications.md   # telemetry / alert 推送
│   ├── errors.md          # 错误码表 + 重试建议
│   ├── data-model.md      # StateSnapshot 数据模型（JSON 字段定义）
│   └── examples.md        # 实战请求/响应示例
├── http/                  # HTTP/REST 契约
│   ├── routes.md          # 路由表
│   ├── errors.md          # HTTP 状态码 + 错误映射
│   └── examples.md        # curl 示例
├── cli/                   # 命令行契约
│   ├── sophonctl.md        # sophonctl 子命令 + 参数
│   ├── config.md          # config.toml 配置契约
│   └── plugins.md         # 动态控制插件包与调用契约
└── transport/             # 传输通道契约
    ├── ndjson.md          # NDJSON 帧格式
    ├── channels.md        # TCP/Unix/Serial 通道
    └── ws-outbound.md     # WebSocket 出站
```

## 1.2 协议间关系

- **JSON-RPC over NDJSON** 是底层协议（TCP/Unix/Serial 共用）。
- **HTTP/REST** 网关在 JSON-RPC 之上包了一层同步请求/响应（不推送 notification）。
- **CLI**（sophonctl）是 JSON-RPC 的命令行封装（本地或远程）。
- **WebSocket 出站** 把 JSON-RPC notification 转成 WS 帧发云端。

外部调用方按场景选协议：
| 场景 | 用哪个契约 |
|------|-----------|
| 笔记本/脚本直连板子 | `jsonrpc/` + `transport/channels.md` |
| curl/浏览器/REST 集成 | `http/` |
| 命令行操作 | `cli/` |
| 云端管多板 | `transport/ws-outbound.md` |

## 1.3 版本与兼容性约定

- 契约版本与守护进程版本一致（`probe-daemon --version`）。
- **向后兼容**：新增字段/方法不视为破坏性变更；调用方应容忍字段缺失（见 `jsonrpc/data-model.md` §兼容性）。
- **破坏性变更**：删除方法、改字段名/类型、改错误码语义——会升大版本并在 `CHANGELOG` 标注。
- **预留字段**：`data-model.md` 标注的"协议预留、当前不产"字段，调用方不应依赖。

## 1.4 契约真实性保证

- 契约文档**必须基于代码事实**，所有结论附 `源码: file:line` 引用。
- **改代码必须同步改契约**：任何对外接口（方法/字段/错误码/路由/配置）变更，必须同时更新对应契约文档。
- 契约与代码不一致时，**以代码为准**，但视为缺陷，应尽快修正文档或回退代码。

## 1.5 如何贡献/反馈

发现契约文档错误或不可用，是**高优先级 bug**（外部依赖它），请立即修复并跑 `./scripts/full_test.sh` 确认。
