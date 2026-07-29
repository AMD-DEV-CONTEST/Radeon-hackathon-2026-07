# Development Skills

启动后可选择技能，在 `data/generated_projects/` **真实生成项目文件**。

## Notebook

打开 `notebooks/private_agent_demo.ipynb` → 运行单元格 → 顶部：

1. 下拉选择技能  
2. 填写项目名  
3. 点 **运行技能并生成项目**  
4. 用文件浏览器打开 `data/generated_projects/<项目名>/`

## CLI

```bash
python scripts/run_skill.py --list
python scripts/run_skill.py --skill scaffold_private_agent_mini --name demo_agent
ls data/generated_projects/demo_agent
python data/generated_projects/demo_agent/main.py
```

## Built-in skills

| ID | 产出 |
|----|------|
| `scaffold_private_agent_mini` | 迷你 RAG Agent（main.py/docs/README） |
| `scaffold_fastapi_service` | FastAPI 办公 API |
| `scaffold_ingest_pipeline` | 文档入库流水线 |
| `scaffold_static_dashboard` | 静态 HTML 看板 |
| `write_project_brief` | 项目简报 Markdown |
