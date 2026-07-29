# 六大应用模式 · 完美对照

PrivateLocalAgent 在 AMD Radeon GPU（`local_transformers`）上本地推理，覆盖官方全部示例应用。

| 应用 | 模式 ID | 核心实现 | 演示入口 |
|------|---------|----------|----------|
| 个人生产力助手 | `productivity` | 记忆读写 + 多轮上下文 | 「记住我喜欢…」 |
| 企业副驾驶 | `enterprise` | 领域包 + 隐私护栏 + 制度 RAG | 「涉密文档…」「发到微信…」 |
| 工作流自动化代理 | `workflow` | 需求→YAML→执行；导出 Dify/LangChain | 「设计工作流：…」 |
| 本地知识助理 (RAG) | `rag` | Chroma + 强制 `kb_search` + 可配置 | 「配置本地知识助理：…」 |
| 开发者生产力代理 | `developer` | 技能脚手架 + 可配置导出 | 「配置开发者代理：…」 |
| 多代理系统 | `multi` | 自动路由 + 路由规则可配置 | 「配置多代理路由：…」 |

> 需求→本地配置→多格式导出 详见 [`WORKFLOW_AND_APPS.md`](./WORKFLOW_AND_APPS.md)。

## 能力闭环（推理·规划·工具·记忆·执行）

1. **推理**：本地 Qwen on Radeon/ROCm  
2. **规划**：`build_task_plan` + 编排路由  
3. **工具**：kb_search / memory / workflow / skills / files  
4. **记忆**：`SessionMemory` history + facts/notes  
5. **执行**：workflow / task_executor / skill 写盘  

## 运行

```bash
# 一次跑完六种模式
python scripts/demo_six_apps.py

# 指定模式
python scripts/demo_six_apps.py enterprise "涉密文档可以用哪些 AI 工具？"

# Notebook：选择应用模式 + 技能 + 问答
# notebooks/private_agent_demo.ipynb
```

## GPU 适配

`configs/default.yaml` → `backend: local_transformers` + `dtype: float16`  
验证：`python scripts/verify_rocm.py` · 测速：`python scripts/bench_rocm.py`
