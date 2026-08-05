# MoonRabbits 月兔瓷话 — AMD AI DevMaster Hackathon 2026-07 · Track 2

一支会讲故事的 AI 瓷乐队：以中国陶瓷色釉为线索的多 Agent 叙事产品。
四专家 Agent 并行考据 + 工头（Foreman）云端工具调用，本地大模型保底、云端 API 增强。

## 硬件与系统环境

| 项 | 规格 |
|---|---|
| GPU | AMD Radeon Pro W7900（gfx1100，48 GB VRAM） |
| ROCm | 7.2.1 |
| OS / Python | Ubuntu · Python 3.12.3 |
| 推理运行时 | Ollama（本地保底，端口 11434）+ 可选 vLLM ROCm 版（端口 8001） |
| 本地模型 | qwen2.5:14b-instruct-q8_0（实测 42.6 tok/s 单流） |
| 量化模型 | Qwen2.5-14B-Instruct AWQ（vLLM，官方量化加分项） |

## 架构

- **四专家 Agent**（中文模式）：考据官 Historian / 格物官 Scientist / 灵感官 Muse / 讲述者 Narrator
  - 知识库：ChromaDB + 关键词/向量双路检索（`moonrabbits_agents.py`）
- **工头 Foreman**（`foreman.py`）：优先走 Radeon Cloud 模型 API（工具调用、朝代年号 lookup 等内置工具），
  云端不可达时自动降级到本地 Ollama 链路；`radeon_api_key.txt` 为密钥文件，**不进 git**
- **前端**：单文件 `index.html`，渲染 Agent 回答 + 工具徽标（foreman.badges）+ backend 标识
- **会话持久化**：`sessions_store.json` 落盘，重启服务后历史会话可恢复（官方"本地多轮记忆"证据）

## 快速开始

```bash
# 1. 依赖
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt

# 2. 本地推理保底（Ollama）
ollama serve &
ollama pull qwen2.5:14b-instruct-q8_0

# 3. 构建知识库（生成 chroma/ 与 kb_text_index.json）
python ingest_kb.py

# 4. 启动产品（http://localhost:8000）
python app.py

# 5. 可选：工头云端后端（无 key 时自动降级本地，不影响使用）
echo "<your-radeon-cloud-key>" > radeon_api_key.txt

# 6. 可选：vLLM 量化推理服务（端口 8001，AWQ）
# 见 benchmarks 与 vllm 独立 venv 说明
```

## 文件说明

| 文件 | 作用 |
|---|---|
| `app.py` | 产品主服务（8000 端口）：会话、四 Agent 编排、安全门、SSE 推送 |
| `moonrabbits_agents.py` | 检索（ChromaDB 双路）+ Ollama 链路封装 |
| `foreman.py` | 工头模块：Radeon Cloud API + 内置工具 + 降级链 |
| `ingest_kb.py` | 知识库导入脚本（kb_entries.jsonl → chroma） |
| `index.html` | 前端页面 |
| `kb_entries.jsonl` / `kb_entries_core.jsonl` | 陶瓷知识库条目 |
| `tools/` | 剧集成片包批量生成管线（Ollama 串行，质量门自检） |

## 内容生产线

`tools/` 下的批处理脚本调用同一条本地推理链，为纪录片式内容生成"成片包"
（集标题 / 60s 旁白 / 3 镜头分镜 / 即梦提示词中英 / 字幕），内置名单自净与
五节结构 + 引用角标 + 字数三重质量门，产出见 `episodes/`（不进 git）。

## 安全说明

- `radeon_api_key.txt` 已加入 `.gitignore`，任何情况下不提交
- 所有外部输入经过安全门（词边界正则）过滤
