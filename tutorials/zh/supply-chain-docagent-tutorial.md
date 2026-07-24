# 在 AMD ROCm 上构建供应链单据智能处理 Agent：从零到部署的完整指南

> **适用赛道**: 赛道二 - 私有 AI Agent 开发与本地部署  
> **预计时长**: 60-90 分钟  
> **难度**: 中级  
> **作者**: cyslmsolomon  
> **GitHub**: [AMD-DEV-CONTEST/Radeon-hackathon-2026-07](https://github.com/AMD-DEV-CONTEST/Radeon-hackathon-2026-07)

---

## 目录

1. [环境搭建](#1-环境搭建)
2. [LLM 推理服务部署](#2-llm-推理服务部署)
3. [RAG 引擎构建](#3-rag-引擎构建)
4. [单据分类 Agent](#4-单据分类-agent)
5. [字段提取 Agent](#5-字段提取-agent)
6. [三单校验引擎](#6-三单校验引擎)
7. [多 Agent 编排](#7-多-agent-编排)
8. [Web UI 与优化](#8-web-ui-与优化)

---

## 前置要求

### 硬件要求

| 组件 | 最低要求 | 推荐配置 |
|------|---------|---------|
| GPU | AMD Radeon RX 6800 XT (16GB) | AMD Radeon RX 7900 XTX (24GB) |
| 内存 | 16GB | 32GB |
| 存储 | 50GB 可用空间 | 100GB SSD |

### 软件要求

- Ubuntu 22.04 LTS (推荐)
- Python 3.10+
- ROCm 6.x
- Git

### 知识要求

- 基础 Python 编程
- 了解 LLM 和 RAG 基本概念
- 熟悉命令行操作

---

## 1. 环境搭建

**预计时间**: 15 分钟

### 1.1 安装 ROCm

首先，安装 AMD ROCm 6.x 驱动和工具：

```bash
# 添加 ROCm 仓库
wget -qO - https://repo.radeon.com/rocm/rocm.gpg.key | sudo tee /etc/apt/trusted.gpg.d/rocm-keyring.gpg

echo 'deb [arch=amd64] https://repo.radeon.com/rocm/apt/6.1/ ubuntu main' | sudo tee /etc/apt/sources.list.d/rocm.list

# 安装 ROCm
sudo apt update
sudo apt install rocm-hip-runtime rocm-hip-sdk rocm-dev

# 添加用户到 render 和 video 组
sudo usermod -aG render,video $USER

# 重新登录后生效
```

### 1.2 验证 ROCm 安装

```bash
# 检查 GPU 信息
rocm-smi

# 预期输出应显示您的 AMD GPU 信息
```

### 1.3 克隆项目

```bash
# 克隆仓库
git clone https://github.com/cyslmsolomon/Radeon-hackathon-2026-07.git
cd Radeon-hackathon-2026-07

# 创建虚拟环境
python -m venv venv
source venv/bin/activate

# 安装依赖
pip install -r requirements.txt
```

### 1.4 验证 PyTorch GPU 支持

```bash
python -c "
import torch
print(f'PyTorch version: {torch.__version__}')
print(f'CUDA available: {torch.cuda.is_available()}')
if torch.cuda.is_available():
    print(f'GPU: {torch.cuda.get_device_name(0)}')
    print(f'GPU Memory: {torch.cuda.get_device_properties(0).total_mem / 1024**3:.1f} GB')
"
```

**预期输出**:
```
PyTorch version: 2.4.0+rocm6.1
CUDA available: True
GPU: AMD Radeon RX 7900 XTX
GPU Memory: 24.0 GB
```

---

## 2. LLM 推理服务部署

**预计时间**: 15 分钟

### 2.1 安装 vLLM

```bash
# 安装 vLLM (ROCm 版本)
pip install vllm
```

### 2.2 下载模型

```bash
# 使用 huggingface-cli 下载模型
pip install huggingface_hub
huggingface-cli download meta-llama/Llama-3.1-8B-Instruct --local-dir models/llama-3.1-8b
```

### 2.3 启动 vLLM 服务

```bash
# 启动 vLLM 服务
python -m vllm.entrypoints.openai.api_server \
    --model models/llama-3.1-8b \
    --device cuda \
    --dtype half \
    --max-model-len 4096 \
    --port 8000 &
```

### 2.4 验证服务

```bash
# 检查模型列表
curl http://localhost:8000/v1/models

# 发送测试请求
curl http://localhost:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "meta-llama/Llama-3.1-8B-Instruct",
    "messages": [{"role": "user", "content": "你好，请用中文回复"}],
    "max_tokens": 100
  }'
```

---

## 3. RAG 引擎构建

**预计时间**: 10 分钟

### 3.1 创建 RAG 模块

创建 `src/rag.py`：

```python
"""
RAG 引擎 - 使用 LlamaIndex 构建单据知识库
"""

from pathlib import Path
from llama_index.core import VectorStoreIndex, SimpleDirectoryReader, Settings
from llama_index.embeddings.huggingface import HuggingFaceEmbedding


class RAGEngine:
    """RAG 引擎类"""
    
    def __init__(self, config: dict):
        self.config = config
        self._init_embedding()
        self.index = None
        self._build_index()
    
    def _init_embedding(self):
        """初始化 Embedding 模型（运行在 AMD GPU 上）"""
        embed_model_name = self.config["rag"]["embedding_model"]
        Settings.embed_model = HuggingFaceEmbedding(model_name=embed_model_name)
        Settings.chunk_size = self.config["rag"]["chunk_size"]
        Settings.chunk_overlap = self.config["rag"]["chunk_overlap"]
    
    def _build_index(self):
        """从 data/ 目录构建向量索引"""
        data_dir = Path(__file__).parent.parent / "data" / "sample_docs"
        if data_dir.exists() and list(data_dir.glob("*")):
            documents = SimpleDirectoryReader(str(data_dir)).load_data()
            self.index = VectorStoreIndex.from_documents(documents)
    
    def retrieve(self, query: str) -> str:
        """检索与查询相关的知识库内容"""
        if self.index is None:
            return ""
        
        query_engine = self.index.as_query_engine(
            similarity_top_k=self.config["rag"]["top_k"]
        )
        response = query_engine.query(query)
        return str(response)
    
    def add_documents(self, file_paths: list[str]):
        """动态添加新文档到索引"""
        from llama_index.core import Document
        
        docs = []
        for fp in file_paths:
            path = Path(fp)
            if path.exists():
                text = path.read_text(encoding="utf-8")
                docs.append(Document(text=text, metadata={"source": str(path)}))
        
        if docs:
            if self.index is None:
                self.index = VectorStoreIndex.from_documents(docs)
            else:
                for doc in docs:
                    self.index.insert(doc)
```

### 3.2 测试 RAG 引擎

```python
from src.rag import RAGEngine
import yaml

# 加载配置
with open("config/settings.yaml") as f:
    config = yaml.safe_load(f)

# 初始化 RAG 引擎
rag = RAGEngine(config)

# 测试查询
result = rag.retrieve("采购订单包含哪些字段？")
print(result)
```

---

## 4. 单据分类 Agent

**预计时间**: 10 分钟

### 4.1 分类 Agent 实现

`DocClassifyAgent` 类定义在 `src/agent.py` 中：

```python
class DocClassifyAgent:
    """单据分类 Agent — 识别上传的单据类型"""
    
    def __init__(self, llm, config):
        self.llm = llm
        self.doc_types = config["documents"]["types"]
    
    def classify(self, content: str) -> str:
        prompt = (
            f"根据以下文档内容，判断单据类型。"
            f"可选类型：{', '.join(self.doc_types)}。\n"
            f"只返回类型名称，不要其他内容。\n\n文档内容：\n{content[:2000]}"
        )
        result = self.llm.invoke(prompt)
        for doc_type in self.doc_types:
            if doc_type in result.lower():
                return doc_type
        return "unknown"
```

### 4.2 测试分类

```python
# 测试采购订单分类
with open("data/sample_docs/po_sample.txt") as f:
    po_content = f.read()

doc_type = classify_agent.classify(po_content)
print(f"分类结果: {doc_type}")  # 预期: purchase_order
```

---

## 5. 字段提取 Agent

**预计时间**: 10 分钟

### 5.1 提取 Agent 实现

`FieldExtractAgent` 类定义在 `src/agent.py` 中：

```python
class FieldExtractAgent:
    """字段提取 Agent — 从单据中提取结构化字段"""
    
    def __init__(self, llm, config):
        self.llm = llm
        self.fields = config["documents"]["extraction_fields"]
    
    def extract(self, content: str, doc_type: str) -> dict:
        fields = self.fields.get(doc_type, [])
        if not fields:
            return {}
        
        prompt = (
            f"从以下{doc_type}文档中提取以下字段，以JSON格式返回：\n"
            f"字段列表：{', '.join(fields)}\n\n"
            f"文档内容：\n{content[:3000]}\n\n"
            f"只返回JSON，格式如：{{\"{fields[0]}\": \"值\", ...}}"
        )
        result = self.llm.invoke(prompt)
        
        import json
        try:
            return json.loads(result)
        except json.JSONDecodeError:
            return {"raw": result}
```

### 5.2 测试字段提取

```python
# 测试采购订单字段提取
extracted = extract_agent.extract(po_content, "purchase_order")
print(f"提取结果: {json.dumps(extracted, indent=2, ensure_ascii=False)}")
```

---

## 6. 三单校验引擎

**预计时间**: 15 分钟

### 6.1 校验 Agent 实现

`CrossValidateAgent` 类定义在 `src/agent.py` 中：

```python
class CrossValidateAgent:
    """三单校验 Agent — 交叉核对 PO、送货单、发票"""
    
    def __init__(self, config):
        self.config = config["validation"]
    
    def validate(self, po: dict, delivery: dict, invoice: dict) -> dict:
        results = []
        rules = self.config["cross_check"]
        tolerance = self.config["tolerance"]
        
        for rule in rules:
            po_field, target_field = rule.split(":")
            po_val = po.get(po_field)
            target_val = delivery.get(target_field) or invoice.get(target_field)
            
            if po_val is None or target_val is None:
                results.append({"rule": rule, "status": "skip", "reason": "字段缺失"})
                continue
            
            try:
                po_num = float(str(po_val).replace(",", ""))
                target_num = float(str(target_val).replace(",", ""))
                diff_pct = abs(po_num - target_num) / max(po_num, 1) * 100
                
                if "quantity" in rule and diff_pct <= tolerance["quantity_percent"]:
                    results.append({"rule": rule, "status": "pass"})
                elif "amount" in rule or "price" in rule:
                    if diff_pct <= tolerance["amount_percent"]:
                        results.append({"rule": rule, "status": "pass"})
                    else:
                        results.append({"rule": rule, "status": "fail",
                                         "diff": f"{diff_pct:.1f}%"})
                elif po_num == target_num:
                    results.append({"rule": rule, "status": "pass"})
                else:
                    results.append({"rule": rule, "status": "fail",
                                     "diff": f"{diff_pct:.1f}%"})
            except (ValueError, TypeError):
                if str(po_val).strip() == str(target_val).strip():
                    results.append({"rule": rule, "status": "pass"})
                else:
                    results.append({"rule": rule, "status": "fail"})
        
        all_pass = all(r["status"] in ("pass", "skip") for r in results)
        return {"all_pass": all_pass, "details": results}
```

### 6.2 测试校验

```python
# 测试三单校验
po_data = {"po_number": "PO-2026-001", "quantity": 50, "total_amount": 49950}
delivery_data = {"po_reference": "PO-2026-001", "quantity_delivered": 50}
invoice_data = {"po_reference": "PO-2026-001", "amount": 49950}

result = validate_agent.validate(po_data, delivery_data, invoice_data)
print(f"校验结果: {'通过' if result['all_pass'] else '失败'}")
print(f"详情: {result['details']}")
```

---

## 7. 多 Agent 编排

**预计时间**: 10 分钟

### 7.1 创建主 Agent

实际项目中，所有 Agent 都在 `src/agent.py` 中定义。以下是核心结构：

```python
"""
Supply Chain DocAgent — 多 Agent 协作的供应链单据智能处理系统。
支持单据识别、信息提取、三单校验、异常处理和 ERP 录入。
"""

import yaml
from pathlib import Path
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder

from .rag import RAGEngine
from .tools import get_tools
from .memory import ConversationMemory
from .ui import create_ui


def load_config() -> dict:
    config_path = Path(__file__).parent.parent / "config" / "settings.yaml"
    with open(config_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


class DocClassifyAgent:
    """单据分类 Agent — 识别上传的单据类型"""
    
    def __init__(self, llm, config):
        self.llm = llm
        self.doc_types = config["documents"]["types"]
    
    def classify(self, content: str) -> str:
        prompt = (
            f"根据以下文档内容，判断单据类型。"
            f"可选类型：{', '.join(self.doc_types)}。\n"
            f"只返回类型名称，不要其他内容。\n\n文档内容：\n{content[:2000]}"
        )
        result = self.llm.invoke(prompt)
        for doc_type in self.doc_types:
            if doc_type in result.lower():
                return doc_type
        return "unknown"


class FieldExtractAgent:
    """字段提取 Agent — 从单据中提取结构化字段"""
    
    def __init__(self, llm, config):
        self.llm = llm
        self.fields = config["documents"]["extraction_fields"]
    
    def extract(self, content: str, doc_type: str) -> dict:
        fields = self.fields.get(doc_type, [])
        if not fields:
            return {}
        
        prompt = (
            f"从以下{doc_type}文档中提取以下字段，以JSON格式返回：\n"
            f"字段列表：{', '.join(fields)}\n\n"
            f"文档内容：\n{content[:3000]}\n\n"
            f"只返回JSON，格式如：{{\"{fields[0]}\": \"值\", ...}}"
        )
        result = self.llm.invoke(prompt)
        
        import json
        try:
            return json.loads(result)
        except json.JSONDecodeError:
            return {"raw": result}


class CrossValidateAgent:
    """三单校验 Agent — 交叉核对 PO、送货单、发票"""
    
    def __init__(self, config):
        self.config = config["validation"]
    
    def validate(self, po: dict, delivery: dict, invoice: dict) -> dict:
        results = []
        rules = self.config["cross_check"]
        tolerance = self.config["tolerance"]
        
        for rule in rules:
            po_field, target_field = rule.split(":")
            po_val = po.get(po_field)
            target_val = delivery.get(target_field) or invoice.get(target_field)
            
            if po_val is None or target_val is None:
                results.append({"rule": rule, "status": "skip", "reason": "字段缺失"})
                continue
            
            try:
                po_num = float(str(po_val).replace(",", ""))
                target_num = float(str(target_val).replace(",", ""))
                diff_pct = abs(po_num - target_num) / max(po_num, 1) * 100
                
                if "quantity" in rule and diff_pct <= tolerance["quantity_percent"]:
                    results.append({"rule": rule, "status": "pass"})
                elif "amount" in rule or "price" in rule:
                    if diff_pct <= tolerance["amount_percent"]:
                        results.append({"rule": rule, "status": "pass"})
                    else:
                        results.append({"rule": rule, "status": "fail",
                                         "diff": f"{diff_pct:.1f}%"})
                elif po_num == target_num:
                    results.append({"rule": rule, "status": "pass"})
                else:
                    results.append({"rule": rule, "status": "fail",
                                     "diff": f"{diff_pct:.1f}%"})
            except (ValueError, TypeError):
                if str(po_val).strip() == str(target_val).strip():
                    results.append({"rule": rule, "status": "pass"})
                else:
                    results.append({"rule": rule, "status": "fail"})
        
        all_pass = all(r["status"] in ("pass", "skip") for r in results)
        return {"all_pass": all_pass, "details": results}


class DocAgent:
    """主 Agent — 编排多 Agent 协作流程"""
    
    def __init__(self, config: dict):
        self.config = config
        self.rag = RAGEngine(config)
        self.memory = ConversationMemory(config)
        self.tools = get_tools(config["tools"]["enabled"])
        self._init_llm()
        self.classify_agent = DocClassifyAgent(self.llm, config)
        self.extract_agent = FieldExtractAgent(self.llm, config)
        self.validate_agent = CrossValidateAgent(config)
    
    def _init_llm(self):
        """初始化 LLM（使用 HuggingFace Pipeline）"""
        from langchain_community.llms import HuggingFacePipeline
        from transformers import AutoTokenizer, AutoModelForCausalLM, pipeline
        import torch
        
        model_name = self.config["model"]["name"]
        device = self.config["model"]["device"]
        tokenizer = AutoTokenizer.from_pretrained(model_name)
        model = AutoModelForCausalLM.from_pretrained(
            model_name, torch_dtype=torch.float16, device_map=device,
        )
        self.llm = HuggingFacePipeline(
            pipeline=pipeline(
                "text-generation", model=model, tokenizer=tokenizer,
                max_new_tokens=self.config["model"]["max_tokens"],
                temperature=self.config["model"]["temperature"],
            )
        )
    
    def process_document(self, content: str, filename: str = "") -> dict:
        """处理单张单据的完整流程"""
        # 1. 分类
        doc_type = self.classify_agent.classify(content)
        
        # 2. 提取字段
        extracted = self.extract_agent.extract(content, doc_type)
        
        # 3. RAG 检索相似案例
        rag_context = self.rag.retrieve(f"{doc_type} 异常处理")
        
        return {
            "filename": filename,
            "doc_type": doc_type,
            "extracted_fields": extracted,
            "rag_context": rag_context[:500] if rag_context else "",
            "status": "extracted"
        }
    
    def cross_validate(self, documents: list[dict]) -> dict:
        """三单交叉校验"""
        po_data = {}
        delivery_data = {}
        invoice_data = {}
        
        for doc in documents:
            if doc["doc_type"] == "purchase_order":
                po_data = doc["extracted_fields"]
            elif doc["doc_type"] == "delivery_note":
                delivery_data = doc["extracted_fields"]
            elif doc["doc_type"] == "invoice":
                invoice_data = doc["extracted_fields"]
        
        return self.validate_agent.validate(po_data, delivery_data, invoice_data)
    
    def query(self, user_input: str) -> str:
        """对话式查询"""
        rag_context = self.rag.retrieve(user_input)
        enhanced = user_input
        if rag_context:
            enhanced = f"[知识库参考]\n{rag_context}\n\n[问题]\n{user_input}"
        
        history = self.memory.get_history()
        prompt = ChatPromptTemplate.from_messages([
            ("system", "你是供应链单据处理专家助手。基于知识库回答问题，用中文回复。"),
            MessagesPlaceholder(variable_name="history"),
            ("human", "{input}"),
        ])
        chain = prompt | self.llm
        response = chain.invoke({"input": enhanced, "history": history})
        self.memory.add(user_input, response)
        return response


def main():
    config = load_config()
    agent = DocAgent(config)
    ui = create_ui(agent)
    ui.launch(
        server_name=config["ui"]["host"],
        server_port=config["ui"]["port"],
        share=config["ui"]["share"],
    )


if __name__ == "__main__":
    main()
```

### 7.2 测试完整流程

```python
# 测试完整处理流程
with open("data/sample_docs/po_sample.txt") as f:
    po_content = f.read()

result = agent.process_document(po_content, "po_sample.txt")
print(f"处理结果: {result}")
```

---

## 8. Web UI 与优化

**预计时间**: 10 分钟

### 8.1 创建 Gradio UI

创建 `src/ui.py`：

```python
"""
Web UI - 使用 Gradio 构建用户界面
"""

import gradio as gr


def create_ui(agent):
    """创建 Gradio 界面"""
    
    def process_document(file):
        """处理上传的文件"""
        content = file.read().decode("utf-8")
        result = agent.process_document(content, file.name)
        return result
    
    def query_agent(message, history):
        """对话式查询"""
        response = agent.query(message)
        return response
    
    with gr.Blocks(title="Supply Chain DocAgent") as demo:
        gr.Markdown("# Supply Chain DocAgent")
        gr.Markdown("基于 AMD ROCm 的供应链单据智能处理 Agent")
        
        with gr.Tab("单据处理"):
            with gr.Row():
                file_input = gr.File(label="上传单据", type="binary")
                process_btn = gr.Button("处理")
            
            output = gr.JSON(label="处理结果")
            process_btn.click(process_document, inputs=file_input, outputs=output)
        
        with gr.Tab("对话查询"):
            chatbot = gr.Chatbot()
            msg = gr.Textbox(label="输入问题")
            
            def respond(message, chat_history):
                response = agent.query(message)
                chat_history.append((message, response))
                return "", chat_history
            
            msg.submit(respond, [msg, chatbot], [msg, chatbot])
    
    return demo
```

### 8.2 启动服务

```python
# main.py
from src.agent import DocAgent
from src.ui import create_ui
import yaml

# 加载配置
with open("config/settings.yaml") as f:
    config = yaml.safe_load(f)

# 初始化 Agent
agent = DocAgent(config)

# 启动 UI
demo = create_ui(agent)
demo.launch(server_port=7860)
```

### 8.3 性能优化建议

1. **FP16 推理**: 已在 vLLM 启动时配置 `--dtype half`
2. **批处理**: 调整 `--max-num-seqs` 参数支持并发
3. **缓存**: 使用 Redis 缓存频繁查询的 RAG 结果
4. **异步**: 使用 `asyncio` 处理并发请求

---

## 运行演示

```bash
# 启动 vLLM 服务
python -m vllm.entrypoints.openai.api_server \
    --model models/llama-3.1-8b \
    --dtype half \
    --port 8000 &

# 启动 Web UI
python main.py
```

访问 http://localhost:7860 打开 Web UI。

---

## 提交到黑客松

完成教程后，您可以将项目提交到 AMD AI DevMaster 黑客松：

1. Fork [AMD-DEV-CONTEST/Radeon-hackathon-2026-07](https://github.com/AMD-DEV-CONTEST/Radeon-hackathon-2026-07)
2. 将代码推送到您的 fork
3. 创建 Pull Request，标题格式：`Track 2, [Team Name], [Project Name]`

### 提交清单

- [x] 项目源代码
- [x] README 文档
- [x] 技术报告 (PDF)
- [x] 演示视频 (3-5 分钟)
- [x] PPT/海报 (可选)

---

## 常见问题

### Q: `torch.cuda.is_available()` 返回 False？

A: 检查以下几点：
1. ROCm 驱动是否安装：`rocm-smi`
2. 用户是否在 render/video 组：`groups $USER`
3. 环境变量是否设置：`echo $ROCR_VISIBLE_DEVICES`

### Q: vLLM 启动失败？

A: 检查 GPU 显存是否足够（至少 16GB），并确保模型路径正确。

### Q: Gradio 界面无法访问？

A: 确保端口 7860 未被占用，并检查防火墙设置。

---

## 进阶扩展

1. **图像单据支持**: 集成多模态 LLM，支持拍照识别
2. **ERP 集成**: 对接 SAP/Oracle/用友系统
3. **多仓库协同**: 支持多仓库并行处理
4. **监控告警**: 集成 Prometheus 监控

---

## 参考资源

- [AMD ROCm 文档](https://rocm.docs.amd.com/)
- [vLLM 文档](https://docs.vllm.ai/)
- [LangChain 文档](https://python.langchain.com/)
- [LlamaIndex 文档](https://docs.llamaindex.ai/)
- [Gradio 文档](https://www.gradio.app/)

---

## 许可证

MIT License

---

**恭喜！您已经完成了在 AMD ROCm 上构建供应链单据智能处理 Agent 的完整教程。**

现在，您可以：
1. 运行项目并测试功能
2. 根据需要进行定制和扩展
3. 提交到 AMD AI DevMaster 黑客松
