# XAI 文档索引（单一入口）

> 本文件是仓库 21 份 `.md` 的**导航索引**，不替代原文。找东西先来这里，再进对应文档。
> 维护原则：新增文档请在对应分组下补一行；不要另起一份重叠文档。

## 一、先读这几份（新人 / 回归必看）
| 文档 | 内容 |
|---|---|
| `README.md` | 项目定位：本地私有超级 Agent（参考实现 + Rust 集成骨架） |
| `GETTING_STARTED.md` | 上手指南：怎么跑起来 |
| `USER_GUIDE.md` | 用户视角使用说明 |

## 二、架构与设计（改代码前必看）
| 文档 | 内容 |
|---|---|
| `API_CONTRACT.md` | **前后端 API 契约（单一事实源）**——接口改动的权威依据 |
| `ARCHITECTURE_GUARDRAILS.md` | 架构防「缝合怪」纪律：新增模块的边界红线 |
| `FRONTEND_CAPABILITY_BLUEPRINT.md` | 前端重构能力蓝图（对标 Coze / WorkBuddy / OllamaFlow） |
| `xai-ux-collab-blueprint.md` | 交互与协同蓝图（v2 增补） |

## 三、审计 / 清理 / 诊断（排查历史问题）
| 文档 | 内容 |
|---|---|
| `AUDIT_REPORT.md` | 项目健康度审计报告 |
| `audit-report.md` | 实现审计报告（首轮开发后） |
| `FRONTEND_BACKEND_AUDIT.md` | 前端 → 后端依赖审计 |
| `CLEANUP_LOG.md` | 废代码清理记录（删除清单 + 恢复方式） |
| `verification_20260722.md` | 「红灯图标 + 模型未配置」诊断与修复报告 |

## 四、报告 / 对标（决策参考）
| 文档 | 内容 |
|---|---|
| `COMPARISON_REPORT.md` | 融合版 v4 完整对比报告 |
| `DELIVERY_REPORT.md` | 统一操作台最终交付报告 |
| `XAI_VENDOR_BENCHMARK_REPORT.md` | 真实开源项目调研与差距改进报告 |
| `调研报告_架构对标.md` | 开源对标与差距分析 |

## 五、流程 / 移交 / 质量
| 文档 | 内容 |
|---|---|
| `DEVELOPMENT_WORKFLOW.md` | 软件开发流程 |
| `HANDOFF.md` | 项目移交说明书 |
| `PROJECT_OVERVIEW.md` | 项目综合文档（最全，但体积大） |
| `QUALITY_BACKLOG.md` | 质量待办清单 |
| `CHANGELOG.md` | 变更日志 |

## 六、运维脚本（本目录）
| 文件 | 作用 |
|---|---|
| `xai-snapshot.sh` | 改代码前一行命令打安全快照（git tag + 打包源码/数据） |
| `xai-backup.py` | 每日自动备份 SQLite + 配置（launchd 每日 4:00 触发），`--verify` 做恢复演练 |
| `setup.sh` | 从零复现运行环境（装可选依赖 + 构建前端） |
| `com.xai.backup.plist` | 每日备份的 launchd 任务定义 |
| `requirements.txt` | 可选依赖锁（核心服务仅用 Python 标准库） |
