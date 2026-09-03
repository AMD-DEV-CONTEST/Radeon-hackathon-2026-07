"""AutoFlow Compiler - 自然语言驱动 -> Bundle 自动化系统 (MVP).

分层架构：
- planner:   Task Planner (LLM 生成结构化任务计划)
- capture:   录制执行层 (Computer Use + 事件捕获抽象)
- compiler:  Bundle 编译 (录制 + 语义标注 -> 确定性程序)
- replay:    确定性执行引擎 (Resolution Ladder 分层定位)
- repair:    AI 修复链路 (Halt -> 诊断 -> 版本化)
- registry:  技能仓库 (Bundle 存储 / 语义检索 / 版本管理)
- cli:       Typer 命令行入口
"""

__version__ = "0.6.0"
