# Radeon-Assistant 功能测试报告

**项目**：Radeon-Assistant（作品名「磐石」）
**赛道**：Track 2 — 私有 AI Agent 开发与本地部署
**队伍**：Neoh
**测试日期**：2026-08-06
**被测模型**：Qwen2.5-14B-Instruct（FP16），全程运行在本地 AMD Radeon GPU 上

> 本文为 [`TEST_REPORT.md`](./TEST_REPORT.md)（英文版）的中文译本。赛事提交以英文版为准。

---

## 1. 结论摘要

系统各功能模块均已在目标硬件上用 14B 模型做了端到端实测。**全程不调用任何外部 API** ——
推理、embedding、向量检索都在本地 Radeon GPU 上完成。

| # | 模块 | 覆盖范围 | 结果 |
|---|------|---------|:----:|
| A | 推理引擎 + agent 核心 | 引擎加载、对话、多步任务、摘要、prompt 模式切换 | 通过 (5/5) |
| B | 工具注册表 | 14 个内置工具全部经 registry 调用 | 通过 (14/14) |
| C | 人工审批 + 审计 | 批准放行、拒绝阻断、审计日志写入 | 通过 (3/3) |
| D | 硬件特化生成 | 引擎注入、Verilog 与 testbench 落盘 | 通过 (3/3) |
| E | RAG / 文档流水线 | 建库、PDF **表格**提取、检索、有据问答 | 通过 (4/4) |
| F | 服务入口 | Streamlit Web UI、`/v1/models`、`/v1/chat/completions` | 通过 (3/3) |
| G | 性能基准 | 5 个硬件研发场景 | 平均 27.4 tok/s |

**合计 32 / 32 项功能检查通过。** 已知局限在[第 11 节](#11-已知局限)如实列出 ——
其中最重要的一条：生成的 HDL **未**经仿真器验证。

---

## 2. 测试环境

| 项 | 值 |
|----|----|
| GPU | AMD Radeon Pro W7900D（gfx1100，48 GB）— Radeon Cloud |
| 操作系统 | Ubuntu 22.04.5 LTS，glibc 2.35 |
| Python | 3.14.3（venv 位于 `/opt/venv314`） |
| PyTorch | 2.11.0+rocm7.14.0 |
| vLLM | 0.23.1.dev1+rocm7.14.0（ROCm 构建，cp314） |
| transformers | 5.14.1 |
| flash-attn | 2.8.3 |
| Embedding 模型 | all-MiniLM-L6-v2（384 维），本地 |
| 向量库 | FAISS `IndexFlatL2` |
| `torch.cuda.is_available()` | `True`（HIP 后端） |

本硬件上有两项环境细节是必需的，已由 `setenv-rocm.sh` 统一处理：

- `HSA_OVERRIDE_GFX_VERSION=11.0.0` —— 不设置的话 vLLM 无法识别 gfx1100（W7900 / RX 7900）。
- 通过 `LD_PRELOAD` 预载 `__isoc23_*` 兼容 shim —— 官方 wheel 基于 glibc 2.38 构建，
  而 Ubuntu 22.04 只有 glibc 2.35。

**技术栈为纯 ROCm。机器上没有 CUDA 运行时，也没有安装任何 NVIDIA 包。**

### 引擎运行时指标（14B，FP16）

| 指标 | 值 |
|------|----|
| 模型权重占用显存 | 27.57 GiB |
| GPU KV cache | 78,736 tokens（13.73 GiB） |
| 8,192 tokens/请求下最大并发 | 9.61x |
| 引擎初始化（profile + KV cache + warmup） | 20.83 s（编译 3.55 s） |
| 冷启动模型加载 | 约 76 s |

---

## 3. 测试方法

所有检查都在目标 GPU 上针对真实 14B 模型执行 —— 不用 mock，不用 stub。
工具经由真实的 `ToolRegistry` 调用而非直接调函数，因此注册表查找与分发路径也一并被覆盖。

不依赖 GPU 的检查（工具执行、RAG 建库、PDF 解析、检索）额外做了一轮 CPU-only 复跑，
确认结果可复现、且不受引擎状态影响。

每项检查都断言一个具体的可观测值 —— stdout 里的唯一标记、从文档表格中检索到的特定数值、
磁盘上出现的文件 —— 而不是仅仅断言「没有抛异常」。

---

## 4. A — 推理引擎与 Agent 核心

| 编号 | 检查项 | 证据 | 结果 |
|------|--------|------|:----:|
| A0 | 引擎从本地路径加载 14B | `./models/Qwen2.5-14B-Instruct` | 通过 |
| A1 | `agent.chat()` 硬件 prompt 模式 | 7,423 字符的有据回复 | 通过 |
| A2 | `agent.run_task()` 规划 → 执行 → 反思 | `success=True`，`steps=1` | 通过 |
| A3 | `summarize_conversation()` | 1,102 字符摘要 | 通过 |
| A4 | `agent.chat()` generic prompt 模式 | 7,382 字符回复 | 通过 |

A4 确认 `get_system_prompt(mode)` 的两个分支都可达，且
`chat(prompt_mode=) > RadeonAgent(prompt_mode=) > config.yaml > "hardware"` 的优先级链生效。

Agent 循环（`Planner → Executor → Reflector`）为手写实现，未使用 LangChain 等外部 agent 框架。

---

## 5. B — 工具注册表（14 个工具）

14 个已注册工具全部经 `registry.call_tool()` 调用，并对返回值做断言。

| 类别 | 工具 | 断言内容 | 结果 |
|------|------|---------|:----:|
| 文件 | `read_file` | 读到的内容与写入内容一致 | 通过 |
| 文件 | `write_file` | 执行后文件确实存在 | 通过 |
| 文件 | `delete_file` | 执行后文件确实不存在 | 通过 |
| 文件 | `list_directory` | 列表中含预期条目 | 通过 |
| 文件 | `create_directory` | 执行后目录确实存在 | 通过 |
| Shell | `execute_command` | stdout 含唯一 echo 标记 | 通过 |
| Shell | `execute_python` | stdout 含唯一 print 标记 | 通过 |
| 代码 | `code_interpreter` | 返回的命名空间含计算结果 | 通过 |
| 代码 | `format_code` | 返回 black 格式化后的代码 | 通过 |
| 系统 | `get_system_info` | CPU / 内存字段有值 | 通过 |
| 系统 | `get_gpu_info` | 正确报告 AMD GPU | 通过 |
| 系统 | `get_process_list` | 返回非空进程列表 | 通过 |
| 硬件 | `generate_verilog` | 返回符合可综合风格的 Verilog | 通过 |
| 硬件 | `generate_testbench` | 返回与 DUT 对应的 testbench | 通过 |

工具注册是靠 import 副作用完成的：`tools/__init__.py` 导入每个工具模块，各模块在导入时调用
`register_tool()`。本测试确认该副作用注册路径最终产出的正是 `config.yaml` 中 `agent.tools`
列出的 14 个工具。

---

## 6. C — 人工审批（HITL）与审计追踪

标记了 `requires_approval=True` 的工具（`write_file`、`delete_file`、`execute_command`、
`execute_python`、`code_interpreter`）在执行前必须暂停等待审批回调。

| 编号 | 检查项 | 证据 | 结果 |
|------|--------|------|:----:|
| C1 | 审批**通过** → 工具执行 | 回调返回 `True`，观察到副作用 | 通过 |
| C2 | 审批**拒绝** → 工具被跳过 | 回调返回 `False`，无任何副作用 | 通过 |
| C3 | 审计日志写入 | `logs/audit.log` 同时含 `approval` 与 `tool_call` 记录 | 通过 |

C2 是安全相关的关键用例：拒绝必须真正阻止执行，而不能只是记一条警告。
该测试断言的是副作用的**不存在**，所以若工具偷偷执行了就会判定失败。

审计记录以 JSON Lines 写入。对话内容只记录长度摘要，因此审计轨迹本身不会泄露用户内容 ——
这与「数据不出本机」的目标一致。

---

## 7. D — 硬件特化生成

| 编号 | 检查项 | 证据 | 结果 |
|------|--------|------|:----:|
| D0 | 引擎已注入硬件工具 | agent 构造时调用了 `set_engine(engine)` | 通过 |
| D1 | `generate_verilog` 写入 `./generated/` | 生成带同步复位的 8 位向上计数器 | 通过 |
| D2 | `generate_testbench` 写入 `./generated/` | 生成 `up_counter_tb.v`，与 DUT 对应 | 通过 |

`generate_verilog` / `generate_testbench` 需要推理引擎，因此 `agent/core.py` 通过
`hardware_tools.set_engine(engine)` 做了一次有意的有状态注入，其余工具函数保持无状态。
D0 验证这次注入确实发生了。

> 参见[第 11 节](#11-已知局限) —— 生成的 HDL 由 LLM 产出，**未**经 iverilog / Verilator
> 等仿真器校验。

---

## 8. E — RAG 与文档流水线

这是与硬件研发场景关联最紧的模块：芯片手册的关键信息都承载在**表格**里
（引脚定义、电气参数），而朴素的 PDF 文本提取会把表格结构破坏掉。

测试准备了一份合成 datasheet，含一张带框线的引脚表和一张电气参数表，
每张表内埋入一个别处都不出现的唯一标记值 —— 这样一旦检索命中，就证明该数值确实
从 PDF 表格出发、经索引、完整地传到了模型侧。

| 编号 | 检查项 | 证据 | 结果 |
|------|--------|------|:----:|
| E1 | 从 PDF + Markdown 建库 | `.md` 出 1 块，`.pdf` 出 2 块（正文 + 表格） | 通过 |
| E2 | **PDF 表格提取** + 检索 | 检索到 `Pin Name Type Voltage_VPP / 1 VDD PWR 2.85` | 通过 |
| E3 | Markdown 表格检索 | 检索到 `ILIM_ZX ... 1.80` 限流阈值 | 通过 |
| E4 | 端到端有据问答 | 模型答出「Pin1（VDD）为 2.85V」**并标注来源** | 通过 |

E2 是决定性结果：`pdfplumber` 把表格还原成了结构化行，而不是塌缩成无序文本，
且该行经过分块、embedding、检索后依然完整。

E4 展示了完整链路 —— 模型正确回答了引脚电压问题并引用了来源文档，全程只用本地检索到的上下文。

---

## 9. F — 服务入口

| 编号 | 检查项 | 证据 | 结果 |
|------|--------|------|:----:|
| F1 | Streamlit Web UI（`app.py --mode web`） | 应用路径与 `/healthz` 均返回 HTTP 200，启动日志干净 | 通过 |
| F2 | `GET /v1/models` | HTTP 200，`{"object":"list","data":[{"id":"qwen2.5-14b",...}]}` | 通过 |
| F3 | `POST /v1/chat/completions` | 返回合法 OpenAI 格式响应，含 `usage` 统计 | 通过 |

F2/F3 验证了 `scripts/serve.py` 提供的 OpenAI 兼容端点，这正是
[`DIFY_INTEGRATION.md`](./DIFY_INTEGRATION.md) 中 Dify 接入方案的基础：
任何 OpenAI 兼容客户端都能不改代码直接指向这个本地端点。

Web UI 采用首次对话时才加载模型的懒加载策略，所以启动很快，用户真正发消息前 GPU 保持空闲。

---

## 10. G — 性能基准

完整结果见 [`benchmark_qwen2.5-14b.md`](./benchmark_qwen2.5-14b.md) /
[`benchmark_qwen2.5-14b.json`](./benchmark_qwen2.5-14b.json)。

| 指标 | 值 |
|------|----|
| 平均生成速度 | **27.4 tokens/s** |
| 总 token / 总耗时 | 10,238 / 373.3 s |
| 通过场景数 | 5 / 5 |
| 平均关键词命中率 | 91% |

| # | 场景 | tokens/s | 关键词命中 |
|---|------|---------:|----------:|
| T1 | 知识检索 | 27.3 | 75% |
| T2 | 参数比对 | 27.5 | 100% |
| T3 | 日志分析 | 27.4 | 80% |
| T4 | 代码生成 | 27.4 | 100% |
| T5 | 工程计算 | 27.4 | 100% |

五个场景的吞吐非常稳定（27.3–27.5 tok/s），说明在 48 GB W7900 上跑这个规模的模型
没有出现散热或显存压力。

---

## 11. 已知局限

作为学习 / 开发阶段的作品，如实列出：

1. **生成的 HDL 未经仿真器验证。** `generate_verilog` / `generate_testbench` 属于 LLM 生成，
   没有 iverilog/Verilator 环节做门禁，因此产出 RTL 的语法与功能正确性不做保证。
   接入仿真器做自动自检是最有价值的下一步。
2. **硬件能力属于使用场景特化，不是从零自研的 EDA 引擎。** 它构建在通用 agent 框架之上
   （领域 system prompt + 生成工具 + 手册 RAG）。
3. **关键词命中率是自动化代理指标**，非人工判分。它可用于 7B/14B/32B 的相对比较，
   但不应被当作准确率。要给出有说服力的质量结论，需要人工判分或 LLM-as-judge。
4. **本轮只测了 14B 模型。** 7B 与 32B 代码路径支持但未做基准测试，因此尚无选型对比数据。
   另外 `scripts/serve.py` 提供了 32B 选项，而 `scripts/download_model.py` 尚未列入该尺寸。
5. **表格提取是在合成 datasheet 上验证的**，不是完整的厂商芯片手册。真实手册版式复杂得多
   （跨页表格、合并单元格、旋转文本）。
6. **`install_rocm.sh` 本轮未在干净机器上从头跑通。** 测试环境是逐步搭建的。
   该脚本已通过语法检查、步骤也与已验证的可用技术栈一致，但干净实例上的一键安装验证仍待补。
7. **没有单元测试框架。** 项目没有 pytest 套件，验证方式是上述端到端、场景驱动的实测。
8. **ROCm 推理需要 Linux + AMD GPU**，无法在 Windows 桌面环境运行。

---

## 12. 复现步骤

以下命令均在 `submissions/Neoh/` 目录下、带 AMD GPU 的 Linux 主机上执行。

### 12.1 安装

```bash
bash install_rocm.sh
```

该脚本创建 Python 3.14 venv，安装 ROCm 版 torch/vLLM/flash-attn，并构建 glibc shim。
末尾自带校验步骤，必须打印出 HIP 版本的 torch、ROCm 版 vLLM 版本号，以及设备可用为 `True`。

> 请**不要**单独执行 `pip install -r requirements.txt` —— 公共源会解析到 CUDA 版本的
> torch/vLLM，在本硬件上无法工作。

### 12.2 加载环境

```bash
source setenv-rocm.sh
```

每开一个新 shell 都需要执行。它会导出 `HSA_OVERRIDE_GFX_VERSION=11.0.0`、amd_smi 的
`PYTHONPATH`、`FLASH_ATTENTION_TRITON_AMD_ENABLE=TRUE`，以及 `LD_PRELOAD` 的 glibc shim。

### 12.3 下载模型

```bash
python scripts/download_model.py --model qwen2.5-14b
```

约 28 GB。下载源按 ModelScope → hf-mirror → HuggingFace 顺序回退。

### 12.4 逐项复现

| 对应章节 | 命令 | 观察要点 |
|---------|------|---------|
| A、B、C | `python app.py --mode cli` | 正常对话；再用 `task <描述>` 触发多步规划。调用 `write_file` / `execute_command` 时必须**暂停等待审批** —— 这即复现第 6 节。 |
| C3 | `cat logs/audit.log` | 工具调用与审批的 JSON Lines 记录 |
| D | CLI 中执行：`task 生成一个带同步复位的8位向上计数器` | `./generated/` 下出现 `.v` 文件 |
| E | 把 datasheet 放入 `data/hardware_documents/`，然后 `python scripts/init_hardware_rag.py` | 报告的分块数 > 0；随后提问一个只存在于表格中的数值 |
| F1 | `python app.py --mode web --port 7860` | Web UI 可访问，返回 HTTP 200 |
| F2/F3 | `python scripts/serve.py --model qwen2.5-14b` | 然后 `curl http://localhost:8000/v1/models`，并 POST `/v1/chat/completions` |
| G | `python scripts/benchmark.py` | 重新生成 `docs/benchmark_qwen2.5-14b.{md,json}` |

### 12.5 验证无 CUDA / 无外部 API

```bash
# 必须打印 HIP 版本与 True —— 且不得出现任何 nvidia/cuda 包
python -c "import torch; print(torch.__version__, torch.cuda.is_available())"
pip list | grep -iE "nvidia|cuda" || echo "无 CUDA 包 —— 正确"
```

推理过程不访问任何外部网络端点：模型从本地路径加载，embedding 由本地 all-MiniLM-L6-v2 计算，
向量检索由 FAISS 在进程内完成。
