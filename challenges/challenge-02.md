# Challenge 02: RAG 引擎构建

**Estimated Time:** 40 minutes  
**Difficulty:** Easy

## Introduction

供应链单据处理需要参考历史案例和模板知识。RAG (Retrieval-Augmented Generation) 技术可以让 LLM 在生成回答时参考外部知识库，提高准确性和可解释性。

本挑战将帮助您构建基于 LlamaIndex 的 RAG 引擎，用于存储和检索单据模板、历史异常案例等知识。

## Prerequisites

- Challenge 01 完成
- vLLM 服务正在运行

## Description

构建一个能够检索供应链单据知识的 RAG 引擎。您的目标是：

1. 安装 LlamaIndex 和 BGE Embeddings 模型
2. 加载示例文档到知识库
3. 实现文档分块和向量化
4. 构建检索管道，支持语义搜索

引擎应能够根据查询返回相关的文档片段，用于增强 LLM 的回答。

## Success Criteria

- [ ] BGE Embeddings 模型成功加载
- [ ] 示例文档（采购订单模板、质检报告模板）被正确索引
- [ ] 查询 "采购订单包含哪些字段" 返回相关文档片段
- [ ] 检索结果包含文档来源和相关度分数
- [ ] 响应时间 < 500ms

## Hints

<details>
<summary>Hint 1 (broad)</summary>
LlamaIndex 提供了 `VectorStoreIndex` 类，可以自动处理文档分块、向量化和存储。查看 LlamaIndex 快速入门文档。
</details>

<details>
<summary>Hint 2 (more specific)</summary>
使用 `SimpleDirectoryReader` 加载 `data/sample_docs/` 目录下的文档：
```python
from llama_index.core import VectorStoreIndex, SimpleDirectoryReader
documents = SimpleDirectoryReader("data/sample_docs").load_data()
index = VectorStoreIndex.from_documents(documents)
```
</details>

<details>
<summary>Hint 3 (almost there)</summary>
对于 Embeddings 模型，使用 HuggingFace 的 BGE 模型：
```python
from llama_index.embeddings.huggingface import HuggingFaceEmbedding
embed_model = HuggingFaceEmbedding(model_name="BAAI/bge-small-en-v1.5")
```
将其设置为全局 Embeddings：
```python
from llama_index.core import Settings
Settings.embed_model = embed_model
```
</details>

## Learning Resources

- [LlamaIndex 文档](https://docs.llamaindex.ai/)
- [BGE Embeddings](https://huggingface.co/BAAI/bge-small-en-v1.5)
- [RAG 概念介绍](https://docs.llamaindex.ai/en/stable/understanding/rag/)

## Advanced Challenge (Optional)

实现混合检索策略：
- 结合向量检索和关键词检索
- 使用 `BM25Retriever` 和 `VectorIndexRetriever` 的混合
- 测试不同检索策略的准确率
