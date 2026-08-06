# RDK Agent - AMD AI DevMaster 赛道 2 提交材料

RDK Agent 能够将自然语言描述的机器人需求转化为适用于 RDK X5 设备、经过测试与验证、可部署且可复用的能力。系统由开发主机上的私有多智能体开发运行时，以及开发板上的 Rust 设备访问平台组成。

![RDK Agent 概念封面](assets/rdk-agent-hero.png)

## 为什么叫“智子”（Sophon）？

设备侧子系统 `rdk-sophon` 的名称借鉴了《三体》中的“智子”（sophon）概念。小说描绘了一个被派往地球、承担观察与通信任务的先进信使。RDK Sophon 将这一构想转化为由设备所有者控制的工程模式：在开发板上部署一个轻量探针，持续观察设备状态，并将其作为 `rdk-agent` 与硬件之间受治理的通信桥梁。

![原创智子命名概念图](assets/sophon-three-body-concept.png)

上图是由本项目使用 AI 生成的概念插图，未使用小说或其改编作品的任何官方美术素材或资产。“智子”这一名称仅作为文学典故，用于解释内部代码名称；本独立项目未获得该作品作者、出版方、权利方或影视改编方的认可，也与其不存在隶属或合作关系。

## 提交材料索引

| 要求 | 材料 | 状态 |
| --- | --- | --- |
| 项目说明书 | [Markdown 源文件](PROJECT_SPECIFICATION.md)和 [PDF](deliverables/RDK_Agent_Project_Specification.pdf) | 已完成 |
| 完整源代码与 README | [仓库根目录](../../README.md)和[复现指南](REPRODUCIBILITY.md) | 已完成 |
| 3–5 分钟演示视频 | [B 站主地址](https://www.bilibili.com/video/BV1t3up6iEhy/)、[百度云备用地址](https://dagent-platform.bj.bcebos.com/amd-hackathon/amd-hackathon-2026-07.mp4?authorization=bce-auth-v1/ALTAKYR0nFJFHMGlFjuontyVVP/2026-08-06T12%3A43%3A01Z/-1/host/1a12970cc4c9439caa28199256b028f90e82ba41ac92c68fb921b271be0b0acd)与[交付说明](VIDEO.md) | 已完成；两个公开地址均已验证 |
| 补充 PPT 或海报 | [PowerPoint 演示文稿](deliverables/RDK_Agent_Track2_Pitch_Deck.pptx) | 已完成 |
| AMD Radeon/ROCm 方案 | [私有部署与优化指南](AMD_RADEON_ROCM.md) | 已完成；服务器侧证据见下文说明 |
| 在 Radeon 上训练、部署并优化的模型 | [模型侧索引](MODEL_TRACK.md)与 [`model/`](../../model/README.md) | 已完成；gfx1100 实测，可离线重算 |
| 验证证据 | [证据日志](evidence/verification-2026-08-05.md) | 已采集；最终冻结源码后需刷新 |
| PR 文案 | [PR 描述](PR_DESCRIPTION.md) | 已完成；待补充身份信息 |
| 最终复核 | [提交检查清单](SUBMISSION_CHECKLIST.md) | 团队字段及尚未闭环的技术证据项仍待完成 |
| 交付完整性 | [已验证的清单与 SHA-256 校验和](MANIFEST.md) | 已完成 |

## 项目概述

RDK Agent 提供两种运行模式：

- **机器人开发模式（Robot Development Mode）**：将支持范围内的需求依次送入意图门控和多智能体 TDD 循环，随后构建发布包、部署至 RDK X5、安装生成的 Skill，并执行受控验收检查。
- **机器人应用模式（Robot Application Mode）**：针对只读查询或用户明确要求执行的一次机器人动作，选择已安装的 Skill。

开发流程包含以下五个有序节点：

1. 动作包 TDD：测试智能体（Test Agent）-> 编码智能体（Coding Agent）-> 验证智能体（Verification Agent）。
2. 开发板发布部署。
3. 开发主机 Skill 安装。
4. CLI 硬件验收。
5. 自然语言 Skill 验收。

## 已验证证据的边界

已于 2026-08-05 验证：

- TypeScript 类型检查通过。
- `rdk-agent`：134/134 项自动化测试通过。
- `rdk-sophon`：62/62 项自动化测试通过。
- Rust Clippy 在拒绝所有警告的配置下通过。
- Rust workspace release 构建通过。
- 一台已配置的 RDK X5 成功响应 `ping` 和 `state`；已发现 `servo` 插件。
- 私有 Pi 运行时通过 OpenAI-compatible 端点选择了提供方 `amd` 和模型 `Qwen3-Next-80B-A3B-Instruct`。

`Qwen3-Next-80B-A3B-Instruct` 与经过 SFT 的 `Qwen3-32B-Agentic-SFT-r1-v3` 均已实际跑通。80B 模型有已封存的单张 Radeon `llama.cpp` 服务与兼容性记录；32B SFT 模型还完成了有记录的五节点 `rdk-agent` 实机工作流。

本仓库快照尚未独立证明：

- 服务器侧 Radeon GPU 型号、ROCm 版本、vLLM 启动命令，以及模型精度/量化配置。
- 客户端 TTFT 和输出 token 吞吐量。随附的基准测试脚本已经就绪，但本次提交不包含 API key 或私有端点。

私有 vLLM 端点仍只是一项客户端路由层声明。公开的 80B 性能数字来自另行封存的 `llama.cpp` 运行，本提交不会补写未采集的指标。

## Pull Request 标题

```text
Track 2, d-robotics agent, RDK Agent
```

本目录提供面向中文读者的完整译文；正式英文参赛材料位于 [`submission/en`](../en/README.md)。源代码树中的内部中文工程文档不作为面向比赛的项目说明。
