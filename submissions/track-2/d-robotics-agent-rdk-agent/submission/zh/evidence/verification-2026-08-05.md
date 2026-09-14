# 验证证据 — 2026-08-05

## 范围

本记录明确区分仓库测试、RDK X5 只读证据、客户端模型配置，以及仍需从参赛者控制的 Radeon Cloud 服务器采集的证据。

## 开发主机验证

### TypeScript

命令：

```sh
cd rdk-agent
npm run check
npm test
```

结果：

```text
TypeScript 检查：通过
测试数：134
通过：134
失败：0
```

### Rust

命令：

```sh
cd rdk-sophon
cargo test --workspace
cargo clippy --workspace -- -D warnings
cargo build --release --workspace
```

结果：

```text
测试数：62
通过：62
失败：0
Clippy（-D warnings）：通过
release workspace 构建：通过
```

基于套接字的端到端测试需要绑定本地 TCP/Unix 套接字的权限。它们已在允许绑定回环地址的环境中重新运行并通过。

格式检查边界：

```text
cargo fmt --all -- --check：需要后续处理
```

该命令报告了已有的格式差异。本证据没有将完整的 `scripts/full_test.sh` 流水线描述为全部通过。

## RDK X5 只读证据

命令：

```sh
sophonctl --board x5 --timeout 5 ping
sophonctl --board x5 --timeout 5 state
sophonctl --board x5 --timeout 5 plugins list
```

脱敏后的结果：

```text
ping：pong=true
开发板时间戳：2026-08-05T11:02:17Z
CPU：8 个 usage 条目；报告的核心频率为 1500 MHz
内存：总计 7,424,344,064 bytes；已用 3,550,343,168 bytes
thermal-ddr：55.113 C
thermal-cpu：54.38 C
插件：servo - MagicBox 舵机姿态控制
```

MAC 地址和私有基础设施详情已被有意省略。

## 客户端模型配置

私有 Pi 运行时选择：

```text
provider：amd
模型：Qwen3-Next-80B-A3B-Instruct
API：OpenAI-compatible Chat Completions
```

端点和本地 API key 明文未复制到仓库。

## AMD 服务器证据边界

以下内容尚未为本次提交独立采集，均为证据待补（Evidence pending）：

- AMD Radeon GPU 型号。
- ROCm/HIP 版本。
- vLLM 版本与启动命令。
- 模型 revision 与精度/量化方式。
- 客户端 TTFT 与解码吞吐量。
- 服务器利用率、VRAM 与 profiler 证据。

基准测试脚本和证据采集流程已经随附，因此无需改变方法即可补充这些项目。
