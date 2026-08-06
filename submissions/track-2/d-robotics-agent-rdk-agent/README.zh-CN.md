# RDK Agent — AMD AI DevMaster Track 2

[English](README.md) | [简体中文](README.zh-CN.md)

> 将自然语言需求转化为 RDK X5 上经过测试、可部署、可复用且受治理的机器人能力。

RDK Agent 是一个私有化部署的多智能体平台，用于在 RDK X5 上开发和运行机器人能力。设备状态与控制保留在本地，模型推理可以使用由参赛者控制的私有端点。开发者用自然语言描述机器人行为，多个专业智能体会把它转化为经过测试、验证、可部署且可复用的能力。

![RDK Agent 概念封面](submission/zh/assets/rdk-agent-hero.png)

> 封面是由本项目生成的概念插图，不是本次提交硬件实物的照片。

本文档是 AMD AI DevMaster Track 2 参赛说明的中文本地化版本，供团队审阅、中文讲解和演示准备使用。面向比赛评审与 Pull Request 的正式版本以仓库根目录的[英文 README](README.md)为准。

## 0. Track 2 提交状态速览

| 项目 | 内容 |
| --- | --- |
| 参赛赛道 | Track 2 — Development and Local Deployment of Private AI Agents（私有 AI 智能体的开发与本地部署） |
| 应用名称 | RDK Agent |
| 团队 / 参赛者 | `d-robotics agent` |
| 源码仓库 | <https://github.com/cowhorseming/rdk-sophon> |
| 演示视频 | [B 站主地址](https://www.bilibili.com/video/BV1t3up6iEhy/) · [百度云 MP4 备用地址](https://dagent-platform.bj.bcebos.com/amd-hackathon/amd-hackathon-2026-07.mp4?authorization=bce-auth-v1/ALTAKYR0nFJFHMGlFjuontyVVP/2026-08-06T12%3A43%3A01Z/-1/host/1a12970cc4c9439caa28199256b028f90e82ba41ac92c68fb921b271be0b0acd) |
| Pull Request 标题 | `Track 2, d-robotics agent, RDK Agent` |
| 正式截止时间 | 2026-08-06 23:59（UTC+8，北京/新加坡时间） |

当前交付状态：

| 比赛要求 | 当前状态 | 本文档或附件 |
| --- | --- | --- |
| 项目说明书 | 已完成 | 本文档与[中文 12 页项目说明书 PDF](submission/zh/deliverables/RDK_Agent_Project_Specification.pdf) |
| 完整源代码与 README | 已完成 | 本 monorepo；两个子系统的深层说明见 [`rdk-agent`](rdk-agent/README.md) 与 [`rdk-sophon`](rdk-sophon/README.md) 文档 |
| 3–5 分钟演示视频 | 已完成；3 分 07.2 秒、1080p、H.264/AAC；两个公开地址均已验证 | [B 站主地址](https://www.bilibili.com/video/BV1t3up6iEhy/) · [百度云备用地址](https://dagent-platform.bj.bcebos.com/amd-hackathon/amd-hackathon-2026-07.mp4?authorization=bce-auth-v1/ALTAKYR0nFJFHMGlFjuontyVVP/2026-08-06T12%3A43%3A01Z/-1/host/1a12970cc4c9439caa28199256b028f90e82ba41ac92c68fb921b271be0b0acd) |
| 补充 PPT / 海报 | 已完成 | [中文 12 张幻灯片路演 PPTX](submission/zh/deliverables/RDK_Agent_Track2_Pitch_Deck.pptx) |
| AMD Radeon/ROCm 部署与优化方案 | 已完成 | 客户端配置、受控实验、指标与基准方法见本文第 8–9 节 |
| AMD 服务器与性能证明 | 两条 Qwen3 实测路径均已完成 | 自训练 32B SFT 路径记录了 gfx1100、ROCm 7.2.1、adapter 身份及基线/优化 A/B；80B 路径记录了单张 Radeon 上成功运行的 `llama.cpp` 部署、API 兼容性 canary 与基线/优化服务指标。见[模型侧索引](submission/zh/MODEL_TRACK.md)。 |
| 实际跑通的模型 | `Qwen3-Next-80B-A3B-Instruct` 与自训练的 `Qwen3-32B-Agentic-SFT-r1-v3` | 80B 模型完成了已保存的单卡服务与兼容性运行；32B SFT 模型还完成了有记录的五节点 `rdk-agent` 实机工作流。 |
| 自训练 32B 模型运行真实 `rdk-agent` | 已完成一个有记录的任务：4 分 04 秒跑完 5/5 节点与两道真机验收闸门 | [两臂运行记录](model/AGENT_E2E.md)与[对比截图](model/assets/agent-e2e-sft-vs-base.png)；物理动作仍需人类目视确认 |
| 验证证据 | 已于 2026-08-05 采集 | 本文第 11 节与[原始脱敏日志](submission/zh/evidence/verification-2026-08-05.md) |

正式提交前，团队需要复核最终 worktree，并在提交与发布前明确确认这些变更。

## 1. 执行摘要

RDK Agent 是一个面向 RDK 机器人的私有多智能体开发与运行平台。开发者用自然语言描述行为，多个专业智能体随后设计测试、只实现有边界的动作入口、验证可执行证据、构建确定性 release、部署到开发板、安装为可复用 Skill，并执行受控的 CLI 与自然语言验收检查。本次提交的动作包路径当前面向 MagicBox 舵机运行时中不带参数的 `rdk-servo-action/v1` 动作。

项目解决一个具体的机器人开发问题：即使很小的行为，也会跨越自然语言意图、Python 硬件逻辑、测试、命令行集成、远程部署、Skill 元数据和实体验收。人工交接难以复现，而通用编码智能体在接触真实硬件前需要更严格的控制。

RDK Agent 将模型驱动的推理与确定性交付、设备执行分离。智能体在工具、Skill、文件系统、超时和沙箱边界内工作。确定性脚本控制脚手架、验证、release 结构、哈希和原子部署。RDK X5 通过 `sophonctl` 与 `probe-daemon` 提供稳定的控制和遥测契约。

仓库包含两个可独立构建和部署的系统：

| 目录 | 技术栈 | 职责 |
| --- | --- | --- |
| `rdk-agent/` | TypeScript、Pi SDK | TUI/headless 应用、意图路由、多智能体 TDD、受限工具、Skill 选择与安装、确定性交付适配器、部署和 Human-in-the-Loop 恢复。 |
| `rdk-sophon/` | Rust | RDK X5 `probe-daemon`、`sophonctl`、硬件状态采集、JSON-RPC、遥测、告警、命令策略与审计、传输和动态插件。 |

两个子项目不共享 Cargo 或 npm workspace，也没有内部代码依赖。它们的集成契约是 `sophonctl` CLI 与板端 JSON-RPC 协议，因此任一目录未来都可以迁移到独立仓库，而无需改变另一系统的架构。

## 2. 为什么叫“智子”（Sophon）？

开发板侧子系统 `rdk-sophon` 的名称借鉴了《三体》中的“智子”（sophon）概念。小说描绘了一个被派往地球、承担观察和通信任务的先进信使。

本项目将这一科幻意象重新解释为透明、由设备所有者控制的工程模式：把轻量的 `probe-daemon` 部署到 RDK X5 上，观察设备状态，并通过 `sophonctl` 充当 `rdk-agent` 与硬件能力之间受治理的通信桥梁。

| 文学隐喻 | `rdk-sophon` 中的工程实现 |
| --- | --- |
| 信使被派往遥远世界 | 将 `probe-daemon` 部署到 RDK X5 开发板。 |
| 它观察当地环境 | 采集温度、CPU、内存、磁盘、网络和 BPU 状态。 |
| 它通过长距离链路报告 | 遥测和 JSON-RPC 将开发板状态传递给开发主机。 |
| 它为远端系统协调通信 | `sophonctl` 将 `rdk-agent` 连接到开发板插件和能力。 |
| 它可以远程影响事件 | 受治理的命令可以调用已经批准的机器人能力。 |

与虚构作品中的隐蔽监视不同，`rdk-sophon` 由设备所有者主动安装和控制，提供明确接口，保留审计记录，执行命令策略，并限制智能体权限。

![原创智子命名概念图](submission/zh/assets/sophon-three-body-concept.png)

> 本图是由本项目使用 AI 生成的原创概念插图，未使用小说或其改编作品的任何官方美术素材或资产。“智子”这一名称仅作为文学典故，用于解释内部代码名称；本独立项目未获得该作品作者、出版方、权利方或影视改编方的认可，也与其不存在隶属或合作关系。

## 3. 目标用户与应用场景

### 3.1 机器人应用开发者

开发者可以提出一个新的、自包含的机器人动作需求，无需手动协调测试文件、控制代码、插件注册、Skill 文档、部署和验收。

示例：

```text
开发了一个挥动左手的功能。
```

系统会在整个工作流中保留原始需求。如果生成的元数据、路径或硬件调用颠倒了所要求的方向，确定性守卫会在写入前拒绝该变更。

### 3.2 机器人教育工作者与原型团队

可见的“测试 → 编码 → 验证”循环使智能体机器人开发过程可以检查。离线测试使用 fake 和 mock，模型开发能力时不需要直接访问 GPIO。

### 3.3 RDK X5 运维人员

同一平台支持只读查询温度、CPU、内存、磁盘、网络、BPU 和动态插件。系统明确区分“命令链路执行成功”与“由人确认实际动作效果”两类证据。

### 3.4 可复用的私有机器人能力

通过验证的能力会成为本地 Skill。机器人应用模式可以根据自然语言选择已安装的 Skill，并执行一个已经映射的动作，而不必重新进入开发工作流。

## 4. 系统架构与仓库边界

![端到端架构](submission/zh/assets/architecture.png)

```text
开发主机                                             RDK X5

用户 -> RDK Agent TUI / headless runner
          |-- 意图门控
          |-- 动作包 TDD：测试 -> 编码 -> 验证
          |-- 确定性构建与部署工具
          |-- 离线 Podman 测试沙箱
          `-- 生成的 Skills
                    |
                 sophonctl -------- TCP 7777 --------> probe-daemon
                                                        |-- 硬件采集器
                                                        |-- 遥测与告警
                                                        `-- 舵机插件 -> 动作包

RDK Agent -> 私有 OpenAI-compatible 端点 -> vLLM -> ROCm -> AMD Radeon GPU
```

| 组件 | 职责 |
| --- | --- |
| `rdk-agent` | TypeScript TUI/headless 应用、意图路由、多智能体编排、受限工具、Skill 选择、确定性交付适配器和 Human-in-the-Loop 处理。 |
| `sophonctl` | 开发主机上的稳定命令契约，用于访问开发板状态、插件和动作。 |
| `probe-daemon` | 运行在 RDK X5 上的 Rust 服务，负责 RPC 分发、状态采集、遥测、告警、命令策略、审计和动态插件。 |
| 舵机插件与动作包 | 开发板侧 Python 能力运行时，包含本地元数据和可独立移除的动作包。 |
| 私有模型服务器 | 参赛者控制的 AMD Radeon Cloud 实例上运行、通过 Pi 配置选择的 OpenAI-compatible ROCm 推理端点。 |

`rdk-agent` 不链接 Rust crate。它调用已安装的 `sophonctl` 客户端，后者通过 TCP 7777 与 `probe-daemon` 通信。模型推理只提出有边界的工作，确定性工具和开发板契约负责约束真正写入或执行的内容。模型选择被隔离在 Pi SDK Session adapter 后，因此私有 OpenAI-compatible 服务器可以替换其他提供方，而无需修改工作流或设备代码。

## 5. 两种运行模式与五节点工作流

![五节点开发工作流](submission/zh/assets/workflow.png)

### 5.1 机器人开发模式与意图门控

机器人开发模式将支持范围内的需求送入意图门控和多智能体 TDD 循环，然后构建发布包、部署到 RDK X5、安装生成的 Skill，并执行受控验收检查。

对于完全匹配的问候和确认语，系统会直接以确定性方式作答。其他开发输入由一个短时模型会话分类；该会话没有工具、Skill、项目上下文和文件系统写权限。只有处于受支持动作包范围内且置信度较高的请求才会启动开发流程。正常使用时直接输入自然语言需求即可；`/develop` 只是在确实需要跳过意图分类时使用的人工覆盖指令。

### 5.2 动作包 TDD

动作包 TDD 使用有界循环：

1. **动作测试设计智能体**创建或修订行为测试与动作元数据。
2. **动作编码智能体**只实现动作入口点。
3. **动作验证智能体**在没有写权限的情况下独立运行契约和行为检查。

验证失败会重新开始完整的“测试 → 编码 → 验证”循环。连续三轮未成功后，工作流会暂停并请求人工指导，而不会静默继续。

### 5.3 确定性五节点交付

验证完成后，会运行四个有序交付阶段：

1. **开发板 Release 部署智能体**调用确定性构建工具并以原子方式发布 release。
2. **Skill 安装智能体**在开发主机上安装生成的运行时 Skill。
3. **CLI 硬件验收智能体**通过 `sophonctl` 执行一次新能力。
4. **自然语言 Skill 验收智能体**使用原始需求选择已安装的 Skill，并再次执行同一能力。

因此，五个可见的开发节点是：

1. 动作包 TDD：测试智能体 → 编码智能体 → 验证智能体。
2. 开发板发布部署：确定性构建并以原子方式发布 release。
3. 开发主机 Skill 安装：安装生成的运行时 Skill。
4. CLI 硬件验收：通过 `sophonctl` 执行一次新能力。
5. 自然语言 Skill 验收：使用原始需求选择已安装的 Skill，并再次执行同一能力。

### 5.4 机器人应用模式

机器人应用模式采用独立的单智能体路径。对于能力问题，系统保持只读；对于用户明确提出的祈使式请求，系统会授权执行一次已映射动作。即使模型文本出现错误，工具层仍会强制执行查询与动作的边界。

## 6. 核心能力与 Track 2 契合度

### 6.1 工具调用

每个智能体只获得当前阶段所需的工具。自定义工具提供脚手架、验证、构建和部署等有边界的操作，而不是不受限制的脚本执行。

### 6.2 多步骤规划和任务执行

领域工作流强制执行有序交接，覆盖意图路由、TDD、发布、部署、Skill 安装和两条验收路径。只有前置阶段成功后，后续阶段才会启动。

### 6.3 权限和隐私控制

每个智能体都有工具 allowlist、Skill allowlist、写入路径 allowlist、超时和沙箱策略。开发测试在禁用网络的 Podman 容器中运行，使用只读 workspace 和资源限制；测试环境不会挂载凭据或主机 home 目录。确定性的左右方向一致性检查、可执行证据门控和原子部署在变更发生前提供进一步控制。

### 6.4 Human-in-the-Loop 恢复

遇到歧义、模型或工具错误、无效结构化结果或耗尽修订预算时，工作流会暂停并请求人工输入。`/abort` 可以终止被阻塞的运行。

### 6.5 本地设备遥测与动态执行

`probe-daemon` 为按需查询和遥测提供单次状态快照，覆盖温度、CPU、内存、磁盘、网络和 BPU 状态。动态插件命令使用精确的参数向量，而不是 `sh -c`。机器人动作包从本地注册表中发现，无需重新构建 Rust CLI 即可移除。

### 6.6 Track 2 能力矩阵

Track 2 规则列出五种智能体能力，并要求至少实现两种。本项目只声明仓库中已经实现的能力：

| 赛道能力 | 状态 | 证据边界 |
| --- | --- | --- |
| Local RAG | 未实现 | 不作声明。 |
| 工具调用 | 已实现 | 受限的 read/bash/write/edit，以及确定性的动作包和部署工具。 |
| 多步骤规划 | 已实现 | 有序领域工作流与有界 TDD 修订。 |
| 本地多轮记忆 | 部分实现 | 已有内存会话和人工跟进；没有跨运行持久化记忆，因此不计入已实现能力。 |
| 权限/隐私机制 | 已在智能体层与工具层实现 | Allowlists、离线沙箱、只读挂载、证据门控，以及动作/查询分离；传输认证和正常路径下的逐动作审批仍在路线图中。 |

## 7. 安全性与可靠性设计

### 7.1 Prompt 层以下的控制

Prompt 不是唯一控制措施。文件工具验证路径，Bash 工具拒绝文件修改和不安全的命令形式，动作包工具验证结构和语义，开发智能体也不能调用硬件动作。

### 7.2 方向一致性守卫

当原始需求明确指出左侧、右侧或双侧时，action ID、元数据、意图示例、目录和 Python bridge 调用必须一致。发生冲突时，系统会在写入前以稳定错误码 `ACTION-DIRECTION-001` 拒绝变更。

### 7.3 可执行证据门控

只有文本形式的 `passed` 结果并不足够。运行器会记录验证智能体是否真正执行 Bash，以及最终检查是否成功。证据缺失或检查失败都会把结果改为“需要修订”。

### 7.4 确定性契约验证

动作包格式拒绝 import、动态执行、访问私有 controller、运行时参数、异步入口点，以及与测试 spy 字段耦合。发布结构和元数据由脚本生成，而不是由模型自由输出。

### 7.5 原子部署

部署流程先上传到 staging 区，验证文件和哈希，创建备份，再替换目标；如果替换后的步骤失败，则恢复备份。

### 7.6 诚实的实体验收边界

自动化检查可以证明命令链路和软件契约，但不会声称实体动作的视觉效果正确。最终动作效果仍需人工观察验收。

## 8. 模型与私有化部署

Pi SDK 是唯一负责解析模型提供方的层，领域代码和应用代码不依赖特定模型。每个阶段都会创建隔离的内存会话，并在运行时报告所选 provider 和 model。

Track 2 的目标部署是在由参赛者控制的 AMD Radeon Cloud 实例上运行专用 vLLM 服务。模型进程计划通过 ROCm 在该 AMD Radeon GPU 实例上运行；共享公共模型 API 不得成为唯一的核心推理链路。

```text
RDK Agent -> OpenAI-compatible 私有端点 -> vLLM -> ROCm -> AMD Radeon GPU
     |
     `-> sophonctl -> RDK X5 -> probe-daemon -> 舵机能力
```

当前私有客户端配置：

| 字段 | 值 |
| --- | --- |
| Pi provider | `amd` |
| 模型 | `Qwen3-Next-80B-A3B-Instruct` |
| API 形式 | OpenAI-compatible Chat Completions |
| 声明的上下文窗口 | 131,072 tokens |
| 声明的最大输出 | 8,192 tokens |

真实端点和 API key 被有意排除。仓库仅提供[脱敏后的 Pi 模型配置示例](submission/zh/config/pi-models.amd-rocm.example.json)，并通过环境变量读取密钥。该客户端配置只能证明模型路由，不能证明 GPU 型号、ROCm 版本、服务后端或精度/量化方式。

## 9. AMD Radeon 与 ROCm 优化及证据

### 9.1 合规目标

Track 2 的核心推理链路目标，是在参赛者控制的 Radeon Cloud 上运行专用 vLLM 服务，模型进程在 AMD Radeon GPU 上通过 ROCm 执行，`rdk-agent` 通过 OpenAI-compatible 服务边界访问它。共享公共模型 API 不应成为唯一的核心推理链路。

### 9.2 已实现的软件层推理控制

应用已经减少了不必要的模型工作：

- 完全匹配的问候和确认消息绕过模型推理。
- 意图分类使用不含工具、Skill 和项目上下文的短时会话。
- 每个智能体只承担一个聚焦角色，避免单一会话无限增长。
- 只加载 allowlist 中的 Skill，并明确记录选择证据。
- 跨阶段文本交接限制在最后 6,000 个字符，文件继续作为事实来源。
- 确定性脚本负责脚手架、验证、打包、哈希和部署，不额外调用模型。
- 相互独立的内存会话避免无关历史在不同阶段累积。

这些控制可以减少 token 消耗、上下文增长和结果波动，但不能替代实际测量的 GPU 优化结果。

### 9.3 证据范围与私有 vLLM 边界

仓库目前封存了两条 Radeon 实测路径：

1. 自训练 32B SFT 路径记录了 `gfx1100` GPU、ROCm/HIP 版本、模型与 adapter 身份、精度/量化、`/v1/models`、每臂 88 次 A/B，以及五节点 Agent 实机截图。
2. 80B 路径记录了 `gfx1100` GPU、GGUF 身份与量化方式、单卡显存、十条基线/优化服务记录、可复现的聚合检查，以及三项 API 兼容性 canary。

某个客户端配置使用的独立私有 vLLM 端点目前仅在路由层得到验证；其服务器 GPU、ROCm/vLLM 版本、启动命令、模型 revision 与精度没有单独封存，且公开的 80B 性能数字不依赖该端点。

### 9.4 受控优化矩阵

基准实验应保持提示词、输出上限、软件 revision 和正确性标准不变，每次只改变一个变量。

| 实验 | 基线 | 候选配置 | 所需证据 |
| --- | --- | --- | --- |
| 精度/量化 | 服务器默认值 | 硬件支持的较低精度或量化模型 | 启动参数、VRAM、正确性、TTFT、tokens/s |
| 上下文上限 | 支持的最大值 | 限制为工作流实测所需大小 | 输入 token 数、截断检查、延迟、VRAM |
| 模型预热 | 冷进程 | 有记录预热流程的热进程 | 冷/热样本、p50/p95 |
| 内存利用率 | 服务器默认值 | 调优后的 vLLM 利用率 | 多次运行无 OOM、峰值 VRAM |
| 并发度 | 单请求 | 经测量的低并发 | 单请求延迟与吞吐量 |
| 提示词负载 | 完整通用上下文 | 限定智能体与已选 Skill | token 数、阶段正确性、端到端时间 |

需要报告的指标包括：

- 客户端 TTFT 的 p50 和 p95。
- 解码输出速度（tokens/s）。
- 请求总延迟。
- 端到端工作流耗时。
- 峰值 VRAM 与 GPU 利用率。
- 仅在目标环境有可靠计数器时记录功率或能耗。
- 使用相同提示词时的正确响应率与验收通过率。

随附的[OpenAI-compatible 基准测试脚本](submission/zh/scripts/benchmark-openai-compatible.mjs)会发起固定 prompt 的流式请求，报告 p50/p95 TTFT、总延迟、可获得 token usage 时的 decode throughput，以及响应正确性；脚本不会把 API key 写入报告。

```sh
node submission/zh/scripts/benchmark-openai-compatible.mjs \
  --provider amd \
  --runs 10 \
  --output submission/zh/evidence/amd-endpoint-benchmark.json
```

报告包含端点 host，但不包含 scheme、path 或 key。如果 host 也会暴露私有基础设施，应在公开前删除或哈希化。应使用相同的 prompt 集合测试基线和优化配置，报告 p50 与 p95，而不是只报告最快请求，并结合服务器利用率和 profiler 证据解释客户端结果。

### 9.5 当前证据状态

`d-robotics agent` 团队实际跑通了两条 Qwen3 推理路径，二者分别取证。**(A)** 是团队 SFT 训练的 32B 模型，并在真实 RDK X5 上完成了有记录的 `rdk-agent` 工作流；**(B)** 是在单张 Radeon 卡上成功部署并运行的现成 80B 模型。两者都在参赛者控制的 `gfx1100` 主机上实测。保存产物均可离线审计；复跑 (A) 需要兼容的 Radeon 主机，而 (B) 保存的聚合指标与 delta 可在无 GPU 环境中验证。

| 项目 | (A) 自训练 32B SFT 路径 | (B) Qwen3-Next 80B 单卡服务路径（`llama.cpp`） |
| --- | --- | --- |
| 客户端 provider/model 选择 | 已在本地验证；公开材料已脱敏 | 本地 loopback 端点 |
| AMD Radeon GPU 型号 | `gfx1100`，Card Model `0x744b`，显存 51,522,830,336 B | `gfx1100`，显存 51,522,830,336 B，系统内存 503 GiB |
| ROCm/HIP 版本 | ROCm 7.2.1，HIP `7.2.26015-fc0010cf6a`，torch `2.9.1+rocm7.2.0` | 未封存确切 ROCm/HIP 版本；`llama.cpp` HIP 二进制 SHA-256 `ba13e01f…` |
| 服务器版本与配置 | 服务端原件 `qwen3_agentic_openai_server.py`（SHA-256 `95d5c139…`），SDPA attention、fp32 RMSNorm、贪心解码 | `llama-server`，开启 Flash Attention，32 推理/批处理线程，1 个并行槽，262,144-token 上下文 |
| 模型 revision 与精度/量化 | `unsloth/Qwen3-32B-bnb-4bit@7f721e74…f9083`，bnb NF4 4-bit 双重量化，bf16 计算；adapter `checkpoint-000119` SHA-256 `4dcee691…f20bf` | `Qwen3-Next-80B-A3B-Instruct-Q4_K_M.gguf`，79,674,391,296 参数，48,410,988,384 B，SHA-256 `d103b273…` |
| API 身份与兼容性证据 | 已实测 `/v1/models`；返回的 `id` 与 `/health` 如实反映当前加载的是哪一臂，这也是 A/B 的身份对照手段 | 未封存 `/v1/models` 响应；OpenAI 兼容接口另由三个 canary 验证：结构化 `tool_calls`、`role=tool` 续写、42,028-token needle 检索 |
| 基线与优化后 TTFT | 用户可见 p50 17.41 s → **8.26 s**；p95 83.97 s → **12.89 s** | 中位 2,021.26 ms → **1,808.76 ms**（−10.5%） |
| 基线与优化后解码吞吐量 | 6.54 → **6.72** tok/s，88/88 输出逐字节一致 | 37.19 → **49.82** tok/s（+34.0%）；prefill 1,271.45 → 1,397.39 tok/s（+9.9%） |
| 峰值 VRAM 与利用率 | 加载后约 19.3 GB；基准峰值 27.99 → 28.06 GB；解码期间采样到 GPU 利用率 99% | 48,843,468,800 → 49,523,740,672 B —— **占 51.5 GB 单卡的 96.1%**，承载 80B 级模型 |
| 智能体工作流端到端延迟 | RDK X5 实机上的五节点 `rdk-agent` 工作流：SFT **4 分 04 秒**验收通过（5/5 节点）；Base 停在 3/5，14 分 25 秒后被终止 —— [`model/AGENT_E2E.md`](model/AGENT_E2E.md) | 模型完成了已保存的服务与 API 兼容性运行；本仓库没有为该路径单独封存五节点 Agent 轨迹。 |
| 测量方法 | 每臂 88 次试验，temperature 0，2 条预热记录 | 每臂 1 次预热 + 5 次正式运行，2,332-token prompt，temperature 0 |

#### 9.5.1 自训练 32B SFT 模型跑通真实 RDK Agent 工作流

本团队训练的 32B SFT 模型（`d-robotics-glm/Qwen3-32B-Agentic-SFT-r1-v3`，模型回退为“无”）已面对真实 RDK X5，完成一次有记录的端到端 `rdk-agent` 运行。它在 **4 分 04 秒**内跑完全部五个工作流节点，包括 CLI 与自然语言 Skill 两道真机验收。保持 agent、开发板、任务、工具和命令不变，仅切换模型时，Base 到达 3/5 节点，并因 CLI 验收无法解析其结构化结果，在 14 分 25 秒后被终止。

![RDK Agent 有记录的实机运行：Base 停在 3/5；自训练 32B SFT 完成 5/5](model/assets/agent-e2e-sft-vs-base.png)

左侧：Base 停在 CLI 真机验收节点。右侧：自训练 32B SFT 模型跑完五个节点与两道真机验收闸门。完整记录与复现边界见[端到端运行说明](model/AGENT_E2E.md)。

这是每臂一个任务、一次运行。它证明 SFT 这次运行完成了“模型 → Agent → 开发板”的命令链路；命令退出码 0 与截图本身不能独立证明物理动作的视觉效果正确。

本项目不会编造 AMD 性能数据。对于 (A)，`model/radeon-optimization/qwen3-32b-agentic-sft/benchmark.py` 只有在具备冻结模型、adapter、测试数据及兼容 Radeon GPU 的主机上，才能重新运行每臂 88 次试验并生成 `results.json`。对于 (B)，`model/radeon-optimization/qwen3-next-80b/verify_results.py` 无需 GPU，可从十条保存的测量记录重算墙钟时间、prefill、decode 聚合指标及所有公开 delta。TTFT 只封存了两臂各自的中位数，因此脚本依据保存的中位数检查 TTFT delta，不能重建其分布。

因此，两条 Qwen3 模型路径都完成了真实运行，但封存证据的覆盖范围不同：32B SFT 截图证明了五节点“模型 → Agent → 开发板”命令链路；80B 记录证明了单张 Radeon 上的服务运行、性能、长上下文检索、结构化工具调用与工具结果续写。某个 `rdk-agent` 客户端配置使用的私有 vLLM 端点目前仅在客户端路由层得到验证；上表 80B 性能数字来自已封存的 `llama.cpp` 运行，不依赖该私有 vLLM 端点的服务器信息。

## 10. 安装、部署与复现

以下流程区分开发主机验证、RDK X5 只读检查、完整部署、私有 AMD 推理和实体动作验收。评审者无需移动机器人即可运行本地检查和开发板只读检查。

### 10.1 仓库结构

```text
rdk-sophon/
├── rdk-agent/       TypeScript 多智能体 TUI 与交付工具
├── rdk-sophon/      Rust 设备平台与 sophonctl
└── submission/      比赛附件、证据、配置与脚本
```

### 10.2 前置条件

开发主机：

- macOS 或 Linux 开发主机。
- Node.js 22.19 或更高版本，以及 npm。
- 包含 Cargo 的 Rust 工具链。
- 机器人开发模式所需的 Podman；安装脚本会准备固定的 `docker.io/library/python:3.12-slim` 镜像。
- 用于部署的 RDK X5 SSH 访问权限。

RDK X5：

- 运行在 aarch64 上的 Ubuntu；部署流程已在 Ubuntu 22.04 上验证。
- 用于安装的 `systemd` 和 root 权限。
- SSH 主机别名 `x5-root`，或传给部署脚本的替代名称。
- MagicBox 运行时所需的 Python 3，以及 `Hobot.GPIO` 所需的设备权限。

私有 AMD 推理：

- 具备兼容 ROCm 技术栈的 AMD Radeon GPU 环境。
- 由参赛者控制的专用 OpenAI-compatible vLLM 服务。
- 上文链接的脱敏 Pi 模型配置。

### 10.3 一键安装

克隆仓库后，在仓库根目录运行集成安装脚本：

```sh
git clone https://github.com/cowhorseming/rdk-sophon.git
cd rdk-sophon

export RDK_BOARD_IP=192.0.2.10 # 文档示例地址，请替换为开发板实际 IP。
./rdk-agent/deploy/install-rdk-agent-stack.sh \
  --ssh-host x5-root \
  --board-address "$RDK_BOARD_IP:7777"
```

这一个入口会完成 RDK X5 服务与舵机运行时部署、开发主机 `sophonctl` 的构建安装、Podman 沙箱准备和 `rdk-agent` TUI 安装。脚本会在内部调用 npm 与 Cargo，评审者无需再手动执行依赖安装命令。脚本最后只执行只读联调检查，不会移动机器人。

### 10.4 可选的源码级验证

以下命令只供需要验证源码树的贡献者使用，不属于安装步骤；所有命令块均以仓库根目录为起点。

TypeScript：

```sh
cd rdk-agent
npm run check
npm test
```

本次提交快照的预期证据：TypeScript 检查成功，134 项测试通过。

Rust：

```sh
cd rdk-sophon
cargo test --workspace
cargo clippy --workspace -- -D warnings
cargo build --release --workspace
```

本次提交快照的预期证据：62 项测试通过，拒绝警告的 Clippy 检查成功，release workspace 构建成功。部分端到端测试会绑定本地 TCP 或 Unix 套接字，必须在允许绑定回环套接字的环境中运行。

日常开发也可以从 Rust 子项目运行聚合脚本：

```sh
cd rdk-sophon
./scripts/full_test.sh
```

本次快照没有把仓库的 `scripts/full_test.sh` 流水线记录为一次完整运行；其中的检查、Clippy、测试和 release 构建阶段分别运行并通过。单独执行的 `cargo fmt --all -- --check` 报告已有格式差异；格式检查不属于 `full_test.sh`。

### 10.5 在不移动硬件的情况下检查 TUI

一键安装完成后，启动已经安装的应用：

```sh
rdk-agent
```

TUI 默认进入机器人应用模式。同时按下 `Shift+Tab` 可在机器人应用模式和机器人开发模式之间循环切换，当前模式会显示在状态栏中。安全 UI 检查不要提交机器人动作，只使用只读查看命令：

```text
/modes
/skills
/workspace
```

不要在安全 UI 检查中提交命令式机器人请求；机器人应用模式会把命令式请求视为执行一次已映射动作的授权。

### 10.6 验证 RDK X5 客户端

一键安装脚本会把通过 `--board-address` 传入的 `x5` 开发板地址写入 `~/.rdk-sophon/config.toml`。使用以下只读命令验证已安装的客户端：

```sh
sophonctl --board x5 ping
sophonctl --board x5 state
sophonctl --board x5 plugins list
```

本次提交证据于 2026-08-05 采集到 `pong=true`、实机状态快照和 `servo` 插件。

### 10.7 高级部署选项

集成部署入口位于 `rdk-agent`，但会编排两个子项目的交付物：

- `rdk-sophon` 板端：`probe-daemon` 等 aarch64 二进制、配置与 systemd 服务。
- `rdk-agent` 板端：MagicBox 舵机应用脚本、带局部 registry 的独立动作包与插件 manifest。
- `rdk-sophon` 开发主机：本机架构的 `sophonctl` 客户端。
- `rdk-agent` 开发主机：TUI、Agent/Skill 配置与研发沙箱。

第 10.3 节的默认命令会安装完整技术栈。已有环境需要局部更新时，可使用同一个脚本只部署板端或只部署开发主机：

```sh
export RDK_BOARD_IP=192.0.2.10 # 文档示例地址，请替换为开发板实际 IP。

# 只部署板端：rdk-sophon 服务端 + rdk-agent 舵机运行文件
./rdk-agent/deploy/install-rdk-agent-stack.sh \
  --board-only \
  --ssh-host x5-root \
  --board-address "$RDK_BOARD_IP:7777"

# 只部署开发主机：sophonctl + rdk-agent TUI + Podman 研发沙箱
./rdk-agent/deploy/install-rdk-agent-stack.sh \
  --development-only \
  --board-address "$RDK_BOARD_IP:7777"
```

更深的安装路径与参数说明见 [`rdk-agent` 子系统文档](rdk-agent/README.md)和 [`rdk-sophon` 子系统文档](rdk-sophon/README.md)。

### 10.8 配置私有 AMD Radeon 推理

使用参赛者控制、配备兼容 ROCm 技术栈的 Radeon Cloud 实例，并运行专用 OpenAI-compatible vLLM 服务。比赛专用 Model API 路由要求服务监听 `0.0.0.0:8000`。服务启动示例：

```sh
export MODEL_PATH_OR_ID=/path/to/model-or-hub-id
vllm serve "$MODEL_PATH_OR_ID" \
  --served-model-name Qwen3-Next-80B-A3B-Instruct \
  --host 0.0.0.0 \
  --port 8000
```

复制脱敏客户端配置：

```sh
mkdir -p ~/.pi/agent
cp submission/zh/config/pi-models.amd-rocm.example.json ~/.pi/agent/models.json
```

在复制后的文件中设置真实私有基础 URL，并仅通过环境变量提供 API key：

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

不要公开真实端点或密钥。截图与日志必须遮盖密钥和用户专属隧道名称。

### 10.9 采集 AMD 服务器侧证据

在参赛者控制的 Radeon 实例中执行等效命令，并保存脱敏输出：

```sh
rocminfo
rocm-smi --showproductname --showdriverversion --showmeminfo vram
python3 -c 'import torch; print(torch.__version__); print(torch.version.hip); print(torch.cuda.get_device_name(0))'
python3 -c 'import vllm; print(vllm.__version__)'
curl http://127.0.0.1:8000/v1/models
```

还需记录确切的 vLLM 启动命令、模型 revision、精度或量化设置、容器 digest（如果使用容器）和预热策略。

### 10.10 运行机器人开发模式

启动已经安装的 TUI：

```sh
rdk-agent
```

同时按下 `Shift+Tab`，直到状态栏显示机器人开发模式，然后像正常对话一样直接输入研发需求：

```text
创建一个让左侧挥动一次的新动作。
```

意图门控会识别处于支持范围内且置信度较高的研发需求，并自动启动五节点工作流。`/develop <需求>` 只是在需要跳过意图分类时使用的人工覆盖入口，正常流程不需要它。最后两个验收阶段可能会移动真实硬件，必须确保机器人周围没有人员或障碍物，并做好随时中止的准备。

### 10.11 运行机器人应用模式

安装 Skill 后，同时按下 `Shift+Tab`，直到状态栏显示机器人应用模式，然后直接输入动作需求：

```text
让左侧挥动一次。
```

命令式请求会授权执行一个已经映射的动作。命令链路成功本身不能证明物理动作正确，应另行记录人工观察结果。

### 10.12 预期输出

- TypeScript 与 Rust workspace 测试报告。
- TUI 阶段进度和工具/Skill 事件。
- 带确定性元数据与哈希的动作包 release。
- 开发板部署回执和已安装 Skill。
- `sophonctl` 状态与插件输出。
- 一次 CLI 验收调用和一次自然语言验收调用。
- 脱敏后的 Radeon/ROCm/vLLM 环境证据与基准 JSON。

### 10.13 故障排查边界

- Rust E2E 测试若因绑定 `127.0.0.1` 出现 `Operation not permitted`，应在允许绑定回环套接字的环境中重跑。
- 使用 HTTP 或 WebSocket adapter 时，应显式传入 `/run/probe-daemon/probe.sock`，直到源码默认值与 daemon 配置对齐。
- 真实舵机动作失败时，检查非特权 `probe` 服务用户的 GPIO 权限。
- 模型不可用时，检查 provider/model、私有端点和 API key 环境变量，但不要输出密钥。

## 11. 已验证证据与边界

证据采集于 2026-08-05。[原始验证日志](submission/zh/evidence/verification-2026-08-05.md)包含经过脱敏的命令记录。

| 范围 | 结果 |
| --- | --- |
| TypeScript 静态检查 | 通过 |
| `rdk-agent` 自动化测试 | 134 项通过，0 项失败 |
| `rdk-sophon` 自动化测试 | 62 项通过，0 项失败 |
| Rust Clippy（`-D warnings`） | 通过 |
| Rust workspace release 构建 | 通过 |
| RDK X5 实机 ping | `pong=true` |
| RDK X5 实机状态 | 8 个 CPU usage 条目、核心频率 1500 MHz；内存总计 7,424,344,064 bytes、已用 3,550,343,168 bytes |
| RDK X5 温度 | DDR 55.113 °C；CPU 54.38 °C |
| 动态插件发现 | 已找到 `servo — MagicBox 舵机姿态控制` |
| 客户端模型路由 | provider `amd`，模型 `Qwen3-Next-80B-A3B-Instruct`，OpenAI-compatible Chat Completions |

![仓库验证快照](submission/zh/assets/test-evidence.png)

![经过脱敏的 RDK X5 实机证据](submission/zh/assets/board-evidence.png)

证据边界：

- `cargo fmt --all -- --check` 报告了已有格式差异，因此本提交没有把 Rust 格式检查描述为通过。
- 本次快照没有把完整 `scripts/full_test.sh` 流水线描述为一次完整运行；组成阶段是分别运行和验证的。
- 两个 Qwen3 模型均已实际跑通：80B 路径有已封存的单张 Radeon 服务与兼容性证据；自训练 32B SFT 路径还完成了有记录的五节点 `rdk-agent` 实机运行。
- 客户端模型配置本身只证明模型选择，不能证明私有 vLLM 端点服务器侧的 GPU、ROCm、vLLM 版本、模型 revision 或量化方式。这一证据边界不影响另行封存的 80B `llama.cpp` 运行记录。
- 但**本团队自训练的模型**（`Qwen3-32B-Agentic-SFT-r1-v3`）这些项均已佐证且可复现：GPU `gfx1100`、ROCm 7.2.1、torch 2.9.1+rocm7.2.0、adapter SHA-256 `4dcee691…f20bf`、NF4 4-bit 量化，以及在该主机实测的基线/优化 A/B（用户可见 TTFT p50 17.41 s → 8.26 s，峰值 VRAM 27.99 → 28.06 GB，88/88 输出逐字节一致）。见[模型侧索引](submission/zh/MODEL_TRACK.md)；`results.json` 由 benchmark 在 Radeon 实机生成，非手工誊写。
- 自动化结果只证明软件契约和命令链路，实体动作质量仍需人工观察。
- 公开证据省略了 MAC 地址、凭据和私有基础设施细节。
- 工作流状态与人工输入状态不会跨进程重启持久化。
- 模型运行时配置目前是全局配置，而不是按智能体 profile 选择。

本提交不会暴露凭据，不会把开发主机上的 Mach-O 二进制描述为 RDK X5 交付物，不会把命令成功等同于实体动作质量得到证明，也不会把估算的 AMD 性能数据当作实测数据报告。
