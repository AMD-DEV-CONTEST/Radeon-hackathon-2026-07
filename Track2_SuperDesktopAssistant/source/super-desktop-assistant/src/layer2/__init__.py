"""
Layer 2: 中央调度层（HR/Supervisor）

- 意图分类（粗粒度）
- 任务粗分与显式依赖声明（DAG）
- 路由分发到第3层工头
- 结果汇总（含部分成功/超时降级）
- 公共记忆读取 + Manifest 下发
- 上下文重置信号检测
"""

from .supervisor import (
    Supervisor,
    IntentClassifier,
    TaskSplitter,
    ContextResetDetector,
    SubTask,
    TaskResult,
)
