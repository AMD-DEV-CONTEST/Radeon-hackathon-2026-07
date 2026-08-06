# rdk-agent

RDK 设备的多 Agent 编排应用。该项目作为独立 TypeScript 应用与 `rdk-sophon` 同仓开发，并只通过系统中已安装的 `sophonctl` 与设备探针交互。

## 1. 分层

```text
src/
├── shared/       # 跨层类型与端口接口
├── domain/       # 任务领域模型与业务不变量
├── application/  # 用例编排
├── infra/        # sophonctl 等外部系统适配器
└── api/          # 进程/HTTP/CLI 等入口
```

依赖方向为 `api → application → domain/shared`；`infra` 实现 `shared` 中定义的端口。领域和应用层不得直接调用 `child_process` 或依赖 `sophonctl` 的参数格式。

## 2. 当前实现：TUI 编排器

本目录提供一个基于 [Pi SDK](https://www.npmjs.com/package/@earendil-works/pi-coding-agent) 和 `@earendil-works/pi-tui` 的终端编排器，当前包含两种模式：

1. **机器人开发模式**：围绕一个自包含动作包执行测试设计、Coding、独立验证的 TDD 循环；通过后由确定性脚本构建 release，专用 Agent 依次部署板端动作包和开发机 Skill，最后执行 CLI 与自然语言 Skill 真机验收。
2. **机器人应用模式**：单 Agent 根据自然语言选择一个或多个已交付 Skill；动作式请求会在前置检查后直接执行一次对应的真实机器人动作，查询式请求保持只读。

任意 Agent 无法继续或自动返工达到上限时，工作流暂停并请求人类输入；输入 `/abort` 可以终止。当前不设置人工审批门，正常交付步骤自动继续。

研发模式的普通输入会先经过独立的入口意图分类器。精确问候和感谢由确定性规则直接响应；其他输入由无工具、无 Skill、无项目上下文且不落盘的短 Pi Session 分类为需要研发、普通对话、待澄清或当前研发流程不支持。只有高置信度、明确要求研发且匹配当前动作包能力边界的用户指令才进行 workspace 预检并启动 TDD；分类异常或低置信度默认请求确认。`/develop <用户指令>` 可作为明确的人工覆盖入口。

每个 Agent 有独立的系统提示词、工具白名单、写路径白名单、阶段超时、执行沙箱和严格 Skill 白名单；当前不限制工具调用次数。普通开发者直接运行 `rdk-agent`，程序会从 `config/templates/magicbox-servo` 初始化版本化托管工程，无需下载 rdk-sophon 源码。动作包测试默认在离线 Podman Python 3.12 容器中执行，托管工作区只读挂载，代码修改仍由受 `writePaths` 约束的 Pi 文件工具完成；脚手架、契约验证和 release 结构由固定脚本生成。部署和真机验收留在宿主机执行。Pi 不会向该 Agent 暴露白名单之外的全局或项目 Skill；Agent 根据 Skill 的名称和描述匹配用户指令，先读取一个或多个对应 `SKILL.md` 再执行。机器人应用模式会在工具层区分查询和动作：查询只允许 sophonctl 列表、帮助及版本检查，其他 Bash 命令在启动前拒绝；动作式请求才开放一次真实动作。验证 Agent 只有实际运行安全测试且 Bash 没有报错时才能通过；Skill 交付还会经过确定性合同校验，错误命令、虚假参数或测试结论会被强制改为返工。工作区来源、模式、TDD 循环、部署、最终验收和最大返工次数全部来自运行时读取的 [`config/agents.yaml`](config/agents.yaml)，Skill 位于 `config/skills/<name>/SKILL.md`。

当前动作包契约 `rdk-servo-action/v1` 明确只支持无参数动作。`action.py` 只能以同步、顺序方式调用公开的无参数硬件桥接白名单；导入模块、私有控制器方法、任意 duty 和运行时参数都会被构建前的确定性校验拒绝。参数化动作需要先升级契约。用户原始指令还会作为不可改写的执行上下文贯穿所有 Agent；当用户指令明确指定左、右或双侧时，动作 ID、`start`、描述、触发语句、写入路径和实际桥接调用必须同向，否则工具会在文件创建或覆盖前以 `ACTION-DIRECTION-001` 阻断。

## 3. 板端与开发机部署

rdk-agent 跨两端运行，不能只安装一个本地命令：

```text
开发机                                      RDK X5 板端
rdk-agent ──调用──> sophonctl ──TCP 7777──> probe-daemon
   │                                             │
   └─ Podman 离线开发沙箱                         └─ /opt/sophon/plugins + /userdata/magicbox/scripts
```

默认约定如下：

- 开发机通过 SSH 别名 `x5-root` 部署文件；
- `sophonctl` 中的板子别名固定为 `x5`，与 Agent 提示词和 Skill 保持一致；
- 板端 `probe-daemon` 监听 TCP `7777`；
- Node.js 版本必须不低于 22.19.0；机器人研发模式还需要 Podman 和 `python:3.12-slim` 镜像；
- 开发机安装 `sophonctl` 需要 Rust/Cargo；板端部署脚本会优先交叉编译，缺少交叉工具链时回退到板上编译。

### 3.1 交付物归属

`install-rdk-agent-stack.sh` 是 **rdk-agent 提供的集成部署入口**，它会编排两个项目各自的交付物；脚本放在 rdk-agent 目录下，不代表所有安装内容都属于 rdk-agent。

| 目标机器 | 归属 | 交付物 | 安装结果 |
| --- | --- | --- | --- |
| RDK X5 板端 | **rdk-sophon** | aarch64 服务端、CLI/网关二进制、配置和 systemd unit | `/usr/local/bin/{probe-daemon,sophonctl,probe-http-gateway,probe-ws-outbound}`、`/etc/probe-daemon/config.toml`、`probe-daemon.service` |
| RDK X5 板端 | **rdk-agent** | MagicBox 舵机应用入口、独立动作包和 Sophon 动态插件 manifest | `/userdata/magicbox/scripts/servo_ctrl.py`、`/userdata/magicbox/scripts/servo_actions/<动作 ID>/`、`/opt/sophon/plugins/servo/plugin.toml` |
| 开发机 | **rdk-sophon** | 为开发机本机架构编译的 `sophonctl` 客户端及板子别名 | `~/.local/bin/sophonctl`、`~/.rdk-sophon/config.toml` 中的 `x5` |
| 开发机 | **rdk-agent** | TUI 应用、生产依赖、Agent/Skill/模板配置 | `~/.local/share/rdk-agent/`、`~/.local/bin/rdk-agent`、`~/.config/rdk-agent/` |
| 开发机 | 第三方运行环境 | rdk-agent 研发模式使用的离线 Python 沙箱 | Podman machine 和 `docker.io/library/python:3.12-slim` 镜像 |

板端不会运行 Node.js 或 rdk-agent TUI；开发机上的 rdk-agent 通过本机 `sophonctl` 连接板端 `probe-daemon`。板端的 `sophonctl` 是 rdk-sophon 随板端包一起交付的本地诊断工具，开发机的 `sophonctl` 则必须针对开发机架构单独编译，二者不是同一个二进制文件。

### 3.2 一键部署到板端

先准备 SSH 配置。`rdk-agent/config/agents.yaml` 默认把部署目标写为 `x5-root`，所以该名称既用于登录，也用于开发模式的部署 Agent：

```sshconfig
Host x5-root
  HostName 192.168.128.10
  User root
  IdentityFile ~/.ssh/id_ed25519
```

```sh
ssh -o BatchMode=yes x5-root 'uname -m'
```

从仓库根目录执行：

```sh
./rdk-agent/deploy/install-rdk-agent-stack.sh \
  --board-only \
  --ssh-host x5-root \
  --board-address 192.168.128.10:7777
```

该命令只改板端，不安装开发机的 `sophonctl`、rdk-agent TUI 或 Podman。它依次：

1. 交付 **rdk-sophon 板端包**，启用动态插件并启动 `probe-daemon`；
2. 交付 **rdk-agent 板端运行文件**，初始化 MagicBox servo 插件入口，但不会执行任何舵机动作。

`--board-address` 只用于显示和校验，可以省略；脚本会从 `ssh -G x5-root` 推导主机地址。验证：

```sh
ssh x5-root 'sudo systemctl is-active probe-daemon'
ssh x5-root 'ss -lnt | grep 7777'
ssh x5-root 'test -x /userdata/magicbox/scripts/servo_ctrl.py'
ssh x5-root 'test -f /opt/sophon/plugins/servo/plugin.toml'
ssh x5-root 'sudo journalctl -u probe-daemon -n 50 --no-pager'
```

研发模式后续生成的新动作会继续通过 SSH 原子更新 rdk-agent 的这些板端交付物，无需在板上保存 rdk-agent 源码：

```text
/userdata/magicbox/scripts/servo_ctrl.py
/userdata/magicbox/scripts/servo_actions/
/opt/sophon/plugins/servo/plugin.toml
```

不需要初始化 servo 文件时可传入 `--skip-servo-bootstrap`。`probe-daemon` 的服务用户还必须具备板端 Hobot.GPIO 所需的设备访问权限。不要为了省事把整个 daemon 改成 root；权限不足时应配置设备组或专用硬件控制 Broker。

### 3.3 一键部署到开发机

板端已经部署并能通过 TCP `7777` 访问后，从仓库根目录执行：

```sh
./rdk-agent/deploy/install-rdk-agent-stack.sh \
  --development-only \
  --board-address 192.168.128.10:7777
```

该命令不通过 SSH 修改板端。它依次：

1. 交付 **rdk-sophon 开发机客户端**：编译并安装本机架构的 `sophonctl`，将地址登记成板子别名 `x5`；
2. 准备 **rdk-agent 的第三方沙箱依赖**：Podman 和固定 Python 3.12 镜像；
3. 交付 **rdk-agent 开发机应用**：TUI、生产依赖和可编辑配置；
4. 用 `state`、`plugins list` 和 `rdk-agent --help` 做只读联调检查。

只使用机器人应用模式、不准备研发沙箱时可传入 `--skip-podman`。安装完成后：

```sh
export PATH="$HOME/.local/bin:$PATH"
sophonctl --board x5 state
sophonctl --board x5 plugins list
rdk-agent --help
rdk-agent
```

安装位置和职责：

```text
~/.local/share/rdk-agent/                 应用与生产依赖
~/.local/bin/rdk-agent                    全局命令链接
~/.config/rdk-agent/                      可编辑的 Agent、Skill 和模板配置
~/.local/state/rdk-agent/workspaces/      版本化托管开发工作区
```

### 3.4 一键部署完整环境

新环境需要同时安装板端和开发机时，不传 `--board-only` 或 `--development-only`：

```sh
./rdk-agent/deploy/install-rdk-agent-stack.sh \
  --ssh-host x5-root \
  --board-address 192.168.128.10:7777
```

执行顺序是“板端 rdk-sophon → 板端 rdk-agent 运行文件 → 开发机 rdk-sophon → 开发机 rdk-agent”。只想检查基础命令、参数以及板端 SSH（所选目标包含板端时）可追加 `--preflight-only`，不会安装或覆盖任何文件。查看全部参数：

```sh
./rdk-agent/deploy/install-rdk-agent-stack.sh --help
```

### 3.5 只交付单个项目

不使用集成脚本时，底层脚本的归属和边界如下：

| 命令 | 交付边界 |
| --- | --- |
| `./rdk-sophon/deploy/scripts/deploy-to-board.sh x5-root --enable-plugins` | 只交付 **rdk-sophon 板端包**，不安装 servo 应用文件 |
| `./rdk-sophon/deploy/scripts/install-sophonctl.sh --release --board x5 192.168.128.10:7777 --default` | 只交付 **rdk-sophon 开发机客户端** |
| `./rdk-agent/deploy/install-rdk-agent.sh` | 只交付 **rdk-agent 开发机 TUI**，不安装 sophonctl、Podman 或任何板端文件 |

### 3.6 升级与重新部署

拉取新代码后可以直接重新运行一键脚本。板端部署会覆盖 `/etc/probe-daemon/config.toml`，因此手工修改过板端配置时应先备份或把修改同步回仓库配置；`--enable-plugins` 会继续确保插件功能打开。rdk-agent 安装器会原子替换应用目录：未修改的默认配置自动升级，检测到 `~/.config/rdk-agent` 有用户定制时保留原配置，并生成 `agents.yaml.v2.example` 供人工合并。确认要用当前版本的静态配置替换旧配置时，可执行 `npm run deploy -- --refresh-config`；安装器会先把整个配置目录备份到同级时间戳目录，并保留运行期 `skills/servo-control` 及其回滚目录。

## 4. 运行与配置

Pi SDK 本身没有内置安全沙箱；它提供可替换工具接口和容器/VM 示例。rdk-agent 通过该接口把开发阶段 Bash 路由到 Podman。

默认托管工程位于 `~/.local/state/rdk-agent/workspaces/magicbox-servo/v<workspace.version>`，由内置模板首次原子初始化，重复启动不会覆盖已开发代码。它是研发 Agent 在当前开发机上的可写交付工程，不是对 rdk-sophon 源码仓库的依赖；动作包在这里完成测试与构建后才部署到目标板。`/workspace` 可查看当前工程和来源。模板交付契约升级时必须提高 `workspace.version`，以创建新目录并保留旧工程，不能在同一版本下复用不完整模板。

托管工程的持久化不等于允许新增功能复用历史实现。明确的新增/创建/实现请求在第一轮必须由当前 Session 调用 scaffold；若同名动作已经存在，运行时会先将它可恢复地归档到 `.rdk-agent/action-history/<action-id>/vN`，再创建干净脚手架。实现 Agent 工作前必须运行目标 `unittest` 并得到有效行为红测；若新脚手架的测试提前变绿，运行时会拒绝该意外绿测。修改、修复和测试既有功能仍允许绿色回归。

开发阶段的动作行为与契约测试在离线 Podman 容器中执行。运行时只依赖 Python 3.12 标准库，测试统一使用 `unittest`；不使用 pytest，不会在任务中联网安装包。模板自带 FakeContext 和 GPIO mock 参考测试，供测试 Agent 按现有项目规范扩展。

只有参与 rdk-sophon 仓库开发时才需要显式指定外部源码：

```sh
rdk-agent --workspace /path/to/rdk-sophon
```

外部工程模式会检查 `workspace.requiredPaths`；传错目录时在创建 Agent 前中止并提示候选项目。

默认安装到 `~/.local/share/rdk-agent`，命令链接安装到 `~/.local/bin/rdk-agent`。部署脚本首次运行时还会初始化 `~/.config/rdk-agent`；未修改的默认配置会随程序升级，检测到用户自定义后则保留原配置并生成新版示例供手动合并。

直接编辑下面这些位置，下次启动 TUI 即可生效，不需要修改、编译或重新部署代码：

```text
~/.config/rdk-agent/
├── agents.yaml                 # 模式、循环、Agent 提示词、工具和 Skill
├── skills/<name>/SKILL.md      # Skill 正文
└── templates/magicbox-servo/   # 普通开发者的初始指令工程
```

也可以临时加载另一套配置：

```sh
rdk-agent --config-dir /path/to/config
```

界面语言默认为简体中文。可通过启动参数或环境变量切换为英文，启动参数优先：

```sh
rdk-agent --lang en
RDK_AGENT_LANG=en rdk-agent
```

支持 `zh` / `zh-CN` 与 `en` / `en-US` 等常用别名。语言选项会切换 TUI、无头模式、编排状态和 Agent 面向用户的回答；命令、路径、标识符以及底层工具和板端返回的原始输出保持不变。`agents.yaml` 中的 `nameEn`、`descriptionEn`、`deliverableEn` 和 `developmentScopeEn` 是可选英文展示字段，缺失时回退到原字段。

部署目录可通过 `npm run deploy -- --install-dir <dir> --bin-dir <dir> --config-dir <dir>` 覆盖；脚本会先在临时目录安装生产依赖，成功后再替换旧版本。需要显式刷新静态配置时追加 `--refresh-config`。

TUI 命令：

```text
Shift+Tab                    同时按下，循环切换模式
/develop <用户指令>         明确跳过意图识别并启动研发流程
/workspace                   查看托管/外部工作区及其来源
/skills                      查看当前 Agent 配置、实际加载和本次选择的 Skill
/modes                       查看模式
/mode robot-development      切换机器人开发模式
/mode robot-application      切换机器人应用模式
/clear                       清空日志
/abort                       在等待人类接入时终止工作流
/quit                        退出
```

TUI 默认进入机器人应用模式。模式只能在工作流空闲时切换。

页面和运行日志会实时输出 Skill 白名单、实际加载列表和本次选择，同时展示实际模型、推理级别、循环次数、Agent 状态、工具调用和人类接入请求。研发工作进展固定在输入框上方，并显示整体节点进度、当前节点和当前 Agent；流程结束后保留最终状态。研发模式的 Agent 开始、完成和失败分别使用青、绿、红色短标识，标识前后留有空白行。应用模式只有一个执行步骤，因此不显示工作进展面板、阶段列表和 Agent 生命周期标识，只保留执行日志、Skill 信息及最终结果。Pi 使用其已配置的模型和认证（通常来自 `~/.pi/agent`）。

```text
src/
├── shared/       # AgentRunner 端口、跨层事件
├── domain/       # Agent 配置模型与不可跳过的交付工作流状态机
├── application/  # 双模式编排、TDD 循环和 Human-in-the-loop
├── infra/        # Pi SDK 适配器（唯一知道 Pi session 的层）
└── api/tui/      # Pi TUI 的交互入口和可视化
```

`infra` 仍是未来唯一可调用 `sophonctl` 的层；当前 TUI 中的 Agent 通过 Pi 的受限工具集在目标工作目录中完成交付。`exec` 等受控命令最终仍须受板端 `probe-daemon` 的 shell 策略约束。
