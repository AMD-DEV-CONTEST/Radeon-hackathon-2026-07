# ADR 0005: 分层架构 + 设计模式选型

- **状态**: Accepted
- **日期**: 2026-07-16
- **决策者**: AMD Radeon Studio Team

## 背景

v0.1 需要决定:
1. 怎么组织代码目录
2. 用哪些设计模式
3. 怎么分离关注点

## 决策

### 目录结构
```
src/
├── core/         # 抽象层(无业务,无具体模型)
│   ├── device.py          # ROCm / CUDA / CPU 检测
│   ├── base_model.py      # BaseModel + GenerationRequest / Result
│   └── pipeline_factory.py
├── models/       # 策略实现 — 每个文件一个 BaseModel 子类
├── api/          # FastAPI(routes / schemas / app)
├── ui/           # Gradio(pages / components / app)
└── utils/        # 工具(image / io / logging)
```

### 设计模式

| 模式 | 用在哪 | 解决了什么 |
|---|---|---|
| **策略模式** | `BaseModel` + 三个子类 | 加新模型不动其他代码 |
| **工厂模式** | `PipelineFactory` + `@register_model` | 调用方按 key 拿实例 |
| **单一职责** | 每个文件一个明确职责 | 文件 ≤ 300 行 |
| **依赖注入** | FastAPI `Depends` | 路由可测,模型单例 |
| **数据契约** | `GenerationRequest` / `Pydantic schemas` | 跨层类型一致 |
| **注册表** | `_REGISTRY` 字典 + 装饰器 | 解耦注册 vs 创建 |

## 后果

### ✅ 优点
- **易扩展** — 加"图生视频"模块 = 新建 `src/models/img2video.py` + `@register_model("img2video")`,零修改
- **易测试** — `core/` 完全无 I/O,纯单测;`models/` 用 mock 测逻辑
- **易替换** — SDXL → FLUX,改一个文件
- **易维护** — 目录一眼能看明白在哪改什么

### ❌ 缺点
- 文件多,新手上手有学习成本
- 装饰器注册依赖 import 顺序(`load_default_registry()` 集中处理)

## 备注

- 单文件 ≤ 300 行(超过必拆,见 AGENTS.md)
- 注释写"为什么"不写"是什么"
- 跨层依赖单向:`ui → api → models → core`,反向要 PR 评审
