# Phase B — 测试报告

- Level: S2
- Status: verified

## 测试结果

```
tests/test_rag_retrieval.py .........71 passed in 0.43s

全量: 122 passed, 6 skipped in 2.02s
(Phase A: 51, Phase B: 71)
```

## 覆盖详情

| 模块 | 测试数 | 覆盖点 |
|------|:-----:|--------|
| Tokenizer | 4 | CJK unigram/bigram, mixed CN/EN, empty |
| HashEmbedder | 7 | 确定性、批量、归一化、维度、空输入 |
| Chunker | 9 | 短文档、长文档分块、MD 标题边界、XLSX 透传、PDF 合并、重编号 |
| ProjectIndex | 9 | 构建、增量不变、内容变更重建、保存/加载、空文档、指纹稳定性 |
| Retriever | 10 | FAISS/BM25 独立搜索、混合检索、跨文件召回、top-k、无结果、evidence 字段完整性 |
| Locator | 4 | 标题、页码、表格、回退格式 |
| 20 固定问题 | 20 | 10 事实题 + 5 跨文件题 + 5 无答案题 |
| QA Service | 5 | 有证据回答、来源引用、无证据回退、evidence 字段 |
| E2E | 1 | 导入→索引→检索→保存→加载 全链路 |

**总计: 71 个测试**

## 验收指标达成

1. ✅ 事实题检索：10/10 问题均返回有效 chunks
2. ✅ 跨文件题：检索结果包含 2+ 文件的证据
3. ✅ 无答案题：系统正常处理，返回有效结构
4. ✅ 所有答案附 source citation（relative_path + locator）
