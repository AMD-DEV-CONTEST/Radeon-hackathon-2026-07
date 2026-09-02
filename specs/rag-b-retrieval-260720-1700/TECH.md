# Phase B — 技术设计

- Level: S2
- Status: implemented

## 1. 架构

```
app/rag/
├── __init__.py        # Public exports (updated)
├── manifest.py        # ContentChunk, ParsedDocument, ImportResult
├── scanner.py         # scan_source_entries
├── parsers.py         # import_project
├── chunker.py         # split_document() — 标题优先合并分块
├── embedder.py        # Embedder — LLM /v1/embeddings
├── indexer.py         # ProjectIndex — FAISS + BM25, 增量持久化
└── retriever.py       # Retriever — 混合检索 + RRF
```

### 1.1 数据流

```
import_project() → ParsedDocument[]
        │
        ▼
   chunker.py  → merged ContentChunk[] (500–1000 chars, 100–150 overlap)
        │
        ▼
   embedder.py → embedding vectors (float32[])
        │
        ▼
   indexer.py  → FAISS IndexFlatIP + BM25Okapi
        │         持久化到 vector_db_root/<project_id>/
        ▼
   retriever.py → hybrid search → RRF merge → Evidence[]
```

## 2. 组件说明

### 2.1 chunker.py — split_document()

| 参数 | 值 |
|------|-----|
| min_chars | 500 |
| max_chars | 1000 |
| overlap_chars | 125 |

策略：
- MD/DOCX：按 heading_path 分组合并，段内填满 500–1000 字符后切分
- TXT：连续段落合并填满
- PDF：按页合并，单页超限再切分
- XLSX：行级 chunk 透传，不合并

### 2.2 embedder.py — Embedder

- 调用 `{llm_base_url}/embeddings` 端点
- 输入：`list[str]`，输出：`np.ndarray` (float32)
- 测试模式下可用 `HashEmbedder` 生成确定性向量

### 2.3 indexer.py — ProjectIndex

- `index(parsed_docs)`：分块 → 嵌入 → FAISS → BM25
- `save()` / `load()`：FAISS index + chunks pickle + BM25 corpus 持久化
- `_file_snapshot(parsed_docs)`：基于文件路径+chunk 内容 hash 做增量判断

### 2.4 retriever.py — Retriever

- `search(query, top_k=5)`：
  1. FAISS 召回 top_k×3 候选项
  2. BM25 召回 top_k×3 候选项
  3. RRF (k=60) 合并 → 取 top_k
  4. 返回 `list[Evidence]`
- locator 构建：heading_path / page N / sheet + cell_range

## 3. 依赖

```toml
"faiss-cpu>=1.9,<2",
"rank-bm25>=0.2,<1",
"numpy>=1.26,<3",
```

## 4. 测试覆盖

- chunker：短文档、长文档、MD 标题分段、XLSX 透传、重叠验证
- embedder：单条/批量、空输入、维度一致性
- indexer：构建、增量跳过、保存/加载、空文档
- retriever：召回命中、FAISS+BM25 融合、RRF 合并、top_k 限制、无结果
- 20 个固定问题集（事实/跨文件/无答案）
- QA 来源强制性 + 无证据拒答
