# 1. 设计文档总览

> 本目录面向**维护者**，描述各 crate 的内部设计与依赖关系。
> - **外部读者（人或 AI）想快速了解项目**：从 [`intro/`](intro/) 开始（功能模块 + 进程模块两个视角）。
> - **想对外集成（接口字段/错误码/示例）**：见 [`contracts/`](contracts/)。
> - **想了解内部实现（各 crate 设计）**：见下面的 [`design/`](design/)。

## 1.1 文档组织

按 crate 分文件，每 crate 一篇设计文档：

```
docs/
├── intro/                     # 项目介绍（外部快速了解入口）
│   ├── README.md             # 入口
│   ├── functional.md         # 功能模块视角：8 个功能模块
│   └── processes.md          # 进程模块视角：4 个二进制的关系
└── design/                    # 各 crate 内部设计（维护者）
    ├── overview.md           # 总览 + 依赖图 + 关键决策
    ├── shared.md             # shared crate（protocol + ports）
    ├── infra.md              # infra crate（transport + 真实读取）
    ├── domain.md            # domain crate（采集器 + 领域服务）
    ├── application.md        # application crate（用例编排）
    ├── client.md             # client crate（共享 RPC 客户端）
    ├── daemon.md             # daemon crate（bootstrap 装配）
    └── api-and-testkit.md    # api-cli/api-http/api-ws + testkit
```

## 1.2 阅读顺序

- **外部快速了解**：`intro/README.md` → `intro/functional.md`（功能）或 `intro/processes.md`（进程）。
- **维护者深入**：`design/overview.md` → 按 `shared → infra → domain → application → daemon` 顺序读各 crate。
- **想加功能**：见对应 crate 文档的"新增 XXX"节。

## 1.3 与契约文档的分工

- **项目介绍**（`intro/`）：讲"这个系统是什么"，功能模块 + 进程模块两个视角。
- **设计文档**（`design/`）：讲"怎么实现"，含内部模块、关键决策、约束。
- **契约文档**（`contracts/`）：讲"对外怎么用"，含方法签名、字段、错误码、示例。
- 改对外接口时，**契约与设计两处都要改**：设计文档讲实现，契约文档讲对外。
