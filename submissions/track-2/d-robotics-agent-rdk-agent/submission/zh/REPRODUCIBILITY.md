# RDK Agent 复现指南

本指南将开发主机验证、RDK X5 只读检查、完整部署、私有 AMD 推理和物理动作验收分别说明。评审人员可以执行前两部分，而不会让机器人产生动作。

## 1. 仓库结构

```text
rdk-sophon/
├── rdk-agent/       TypeScript 多智能体 TUI 与交付工具
├── rdk-sophon/      Rust 设备平台与 sophonctl
└── submission/zh/   赛道 2 中文材料与证据
```

## 2. 开发主机前置条件

- Node.js 22.19 或更高版本
- npm
- 包含 Cargo 的 Rust 工具链
- Podman，以及为机器人开发模式预先拉取的 `docker.io/library/python:3.12-slim` 镜像
- 用于本地开发的 macOS 或 Linux

安装依赖：

```sh
git clone https://github.com/cowhorseming/rdk-sophon.git
cd rdk-sophon/rdk-agent
npm ci
```

Rust workspace 使用 `Cargo.lock`；Cargo 会在首次构建时解析已锁定的依赖关系图。

## 3. 安全的本地验证

### 3.1 TypeScript

```sh
cd rdk-agent
npm run check
npm test
```

提交快照的预期证据：TypeScript 检查成功，134 项测试全部通过。

### 3.2 Rust

```sh
cd ../rdk-sophon
cargo test --workspace
cargo clippy --workspace -- -D warnings
cargo build --release --workspace
```

提交快照的预期证据：62 项测试全部通过，Clippy 在拒绝警告的配置下成功，release workspace 构建成功。

本次快照未将仓库中的 `scripts/full_test.sh` 流水线记录为一次完整运行。其组成阶段——检查、Clippy、测试和 release 构建——已分别运行并通过。另行执行的 `cargo fmt --all -- --check` 报告了已有的格式差异；格式检查不属于 `full_test.sh`。

部分 Rust 端到端测试会绑定本地 TCP 或 Unix 套接字。请在允许绑定回环套接字的环境中运行这些测试。

## 4. 在不移动硬件的情况下检查 TUI

```sh
cd ../rdk-agent
npm start -- --workspace "$PWD/config/templates/magicbox-servo"
```

仅使用以下检查命令：

```text
/modes
/mode robot-development
/skills
/workspace
```

进行安全的 UI 检查时，不要提交命令式机器人请求。机器人应用模式会将命令式请求视为执行一个已映射动作的授权。

## 5. 配置 RDK X5 客户端

在开发主机上创建 `~/.rdk-sophon/config.toml`：

```toml
[default]
host = "192.0.2.10:7777" # 仅用于文档的地址；请替换为开发板地址。
timeout = 30

[boards.x5]
host = "192.0.2.10:7777" # 仅用于文档的地址；请替换为开发板地址。
timeout = 30
```

根据开发板实际地址进行调整。随后仅运行只读检查：

```sh
sophonctl --board x5 ping
sophonctl --board x5 state
sophonctl --board x5 plugins list
```

提交证据记录了 2026-08-05 的 `pong: true`、实时状态快照以及 `servo` 插件。

## 6. 部署完整技术栈

RDK X5 前置条件：

- 运行 Ubuntu 的 aarch64 设备，并使用 `systemd`
- 安装所需的 root 权限
- SSH 主机别名 `x5-root`，或传给脚本的替代主机
- MagicBox 运行时所需的 Python 3 和设备权限

从仓库根目录运行：

```sh
export RDK_BOARD_IP=192.0.2.10 # 仅用于文档的示例；请替换为开发板 IP。
./rdk-agent/deploy/install-rdk-agent-stack.sh \
  --ssh-host x5-root \
  --board-address "$RDK_BOARD_IP:7777"
```

该脚本会部署开发板二进制文件及配置、舵机插件/运行时、开发主机上的 `sophonctl`，以及 RDK Agent 应用和配置。安装完成后，它会执行只读集成检查。

## 7. 配置私有 AMD Radeon 推理

使用参赛者控制、配备兼容 ROCm 技术栈的 Radeon Cloud 实例，并运行专用的 OpenAI-compatible vLLM 服务。使用比赛专用 Model API 路由时，该服务必须监听 `0.0.0.0:8000`。

服务启动示例：

```sh
export MODEL_PATH_OR_ID=/path/to/model-or-hub-id
vllm serve "$MODEL_PATH_OR_ID" \
  --served-model-name Qwen3-Next-80B-A3B-Instruct \
  --host 0.0.0.0 \
  --port 8000
```

复制已脱敏的客户端配置：

```sh
mkdir -p ~/.pi/agent
cp submission/zh/config/pi-models.amd-rocm.example.json ~/.pi/agent/models.json
```

在复制后的文件中设置真实的私有基础 URL。不要将 API key 写入仓库：

```sh
read -r -s RDK_AMD_MODEL_API_KEY
export RDK_AMD_MODEL_API_KEY
```

在 `~/.pi/agent/settings.json` 中选择模型：

```json
{
  "defaultProvider": "amd",
  "defaultModel": "Qwen3-Next-80B-A3B-Instruct"
}
```

不要公开真实端点或密钥。截图和日志中应遮盖密钥及用户专属的隧道名称。

## 8. 采集 AMD 服务器侧证据

在参赛者控制的 Radeon 实例内执行等效命令，并保存脱敏后的输出：

```sh
rocminfo
rocm-smi --showproductname --showdriverversion --showmeminfo vram
python3 -c 'import torch; print(torch.__version__); print(torch.version.hip); print(torch.cuda.get_device_name(0))'
python3 -c 'import vllm; print(vllm.__version__)'
curl http://127.0.0.1:8000/v1/models
```

同时记录确切的 vLLM 启动命令、模型 revision、精度或量化设置、容器 digest（如使用容器），以及预热策略。

## 9. 运行客户端基准测试

基准脚本会读取 Pi 模型配置，但绝不会输出 API key：

```sh
node submission/zh/scripts/benchmark-openai-compatible.mjs \
  --provider amd \
  --runs 10 \
  --output submission/zh/evidence/amd-endpoint-benchmark.json
```

对基线配置和优化配置运行同一组提示词。报告 p50 和 p95，而不是只报告最快请求。该客户端结果包含网络/隧道开销，必须结合服务器侧 profiler 和利用率证据进行解读。

## 10. 运行机器人开发模式

启动 TUI：

```sh
rdk-agent
```

然后执行：

```text
/mode robot-development
/develop Create a new action that waves the left side once.
```

观察五个交付节点。最后两个验收阶段可能会移动真实硬件。请确保机器人周围没有人员或障碍物，并做好随时中止的准备。

## 11. 运行机器人应用模式

安装 Skill 后：

```text
/mode robot-application
Wave the left side once.
```

命令式请求会授权执行一个已映射动作。命令链路成功本身并不能证明物理动作正确；请另行记录人工观察结果。

## 12. 预期输出

- TypeScript 与 Rust workspace 的测试报告。
- TUI 阶段进度，以及工具/Skill 事件。
- 带有确定性元数据和哈希的动作包 release。
- 开发板部署回执和已安装的 Skill。
- `sophonctl` 状态与插件输出。
- 一次 CLI 验收调用和一次自然语言验收调用。
- 经脱敏的 Radeon/ROCm/vLLM 环境证据与基准测试 JSON。

## 13. 故障排查边界

- 如果 Rust E2E 测试在绑定 `127.0.0.1` 时因 `Operation not permitted` 失败，请在受限沙箱之外运行。
- 如果使用 HTTP 或 WebSocket adapter，请显式传入 `/run/probe-daemon/probe.sock`，直至其源码默认值与 daemon 配置对齐。
- 如果真实舵机动作失败，请检查非特权 `probe` 服务用户的 GPIO 权限。
- 如果模型不可用，请检查 provider/model 选择、私有端点和 API key 环境变量，但不要输出密钥。
