# Dify 接入本地 14B 推理服务

定位：在 AMD Radeon Cloud（ROCm 平台）上把 Qwen2.5-14B 以 OpenAI 兼容服务暴露出来，
由 Dify 作为前端/编排层接入，实现「100% 本地、数据不出域」的硬件研发私域智能体。

适用场景：AMD 黑客松 Track 2（私有 AI Agent 本地部署）。

---

## 为什么选 vLLM 而不是 llama.cpp

本项目后端推理引擎选用 **vLLM**，而非 llama.cpp。两者均为本地推理引擎，
差异主要体现在部署形态与硬件条件上：

| 维度 | llama.cpp | vLLM |
| --- | --- | --- |
| 定位 | 轻量本地推理（C/C++/GGML） | 高吞吐 GPU 服务框架（Python） |
| 模型格式 | GGUF（量化友好，Q4 等） | safetensors / HF（FP16/BF16 为主） |
| 跑在哪 | CPU / Metal / CUDA / ROCm 均可，可移植性强 | 主要吃 GPU；ROCm 需官方 wheel |
| 显存效率 | 靠量化压显存（14B-Q4 约 9GB） | PagedAttention 管理 KV cache，显存碎片少 |
| 吞吐 | 偏单/少并发，batch 能力弱 | 连续批处理，高并发强 |
| 服务接口 | 自带 `llama-server`，兼容 OpenAI API | 原生 OpenAI 兼容服务（`/v1`） |

本项目的条件决定了 vLLM 更合适：

1. **Dify 依赖 OpenAI 兼容 `/v1` 接口**。vLLM 原生提供，
   `scripts/serve.py` 一行命令即可起服务；llama.cpp 虽也能给，但 batch/吞吐弱一截。
2. **W7900 48GB 显存富余**。FP16 跑 14B 约 30GB 完全够用，
   无需依赖 GGUF 量化省显存——而量化省显存正是 llama.cpp 的主场优势，本项目用不上。
3. **代码已围绕 vLLM 构建**。engine、config、benchmark 全部基于 vLLM，
   切换成本高、收益低。

llama.cpp 的适用场合：显存紧张（如 RX 7900 XT 20GB）、需 CPU 兜底、
或想用 Q4 量化把 32B 塞进小显存时。本机不满足上述条件，故不采用。

---

## 架构

```
Dify (前端/编排)
      │  OpenAI 兼容 API (/v1)
      ▼
vLLM OpenAI 服务 (scripts/serve.py)
      │
Qwen2.5-14B-Instruct  (ROCm / W7900, FP16)
```

全部组件运行在同一台 Radeon Cloud 主机（或同一内网），模型权重不离开本地。

---

## Step 1 — 起 14B 的 OpenAI 兼容服务

```bash
cd submissions/Neoh
python scripts/serve.py --model qwen2.5-14b
```

看到 `Application startup complete` 后，另开终端验证：

```bash
curl http://localhost:8000/v1/models
```

若更换尺寸或端口：

```bash
python scripts/serve.py --model qwen2.5-7b --port 8001
```

---

## Step 2 — 跑 benchmark 拿性能数据（演示/报告用）

```bash
python scripts/benchmark.py --model qwen2.5-14b
```

产出 `docs/benchmark_qwen2.5-14b.md` 与 `.json`，含平均 tokens/s、显存占用、关键词命中率。

---

## Step 3 — 部署 Dify

```bash
git clone https://github.com/langgenius/dify.git
cd dify/docker && cp .env.example .env && docker compose up -d
```

浏览器访问 `http://<host>:80`。

---

## Step 4 — Dify 接入本地 14B

1. `Settings → Model Provider → OpenAI-API-compatible`
2. **Base URL**：`http://<14B服务IP>:8000/v1`
   - 注意：Dify 跑在 Docker 内，不要填 `127.0.0.1`（容器网络隔离），
     填宿主机私网 IP（如 `172.17.0.1` 或云分配的 IP）。
3. **API Key**：任意非空字符串，如 `sk-local`。
4. **Model**：`qwen2.5-14b`（必须与 `--served-model-name` 一致）。
5. 保存后，创建 App 时选择该模型。

---

## Step 5 — 本地知识库（强化「私域/数据不出域」）

Dify 知识库上传芯片 Datasheet / 应用笔记 → 创建 Chatbot App 开启检索，
得到完全本地的硬件问答。embedding 也可走 `serve.py` 已开启的 `/v1/embeddings`
使用本地模型，做到全链路不出域。

---

## 显存与兜底

- 14B FP16 约 30GB，W7900（48GB）无压力。
- 若将来切到 RX 7900 XT（20GB）显存吃紧，可在 `serve.py` 加
  `--dtype half`（默认已 half）或 `--quantization awq`。
- 若云上不便跑 Docker，可改用 **Open WebUI**（对本地 vLLM 一键接入，比 Dify 更轻量）；
  或源码直跑 Dify 的 `api` + `web`。

---

## 进阶（时间充裕）

把自研的 Planner-Executor-Reflector + FAISS RAG 包成 HTTP 服务，
作为 Dify 的「自定义 API 工具」被调用——既保留本项目的差异化架构，
又用 Dify 提供成品前端与编排能力。
