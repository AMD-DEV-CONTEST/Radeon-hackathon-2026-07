# Challenge 03: 单据分类 Agent

**Estimated Time:** 45 minutes  
**Difficulty:** Medium

## Introduction

供应链入库环节涉及多种类型的单据：采购订单、送货单、质检报告、入库单、发票。每个单据类型需要不同的处理逻辑。

首先需要一个分类 Agent，能够自动识别上传的单据类型，为后续的字段提取和校验提供基础。

## Prerequisites

- Challenge 01 完成 (LLM 服务)
- Challenge 02 完成 (RAG 引擎)

## Description

构建一个能够自动识别单据类型的 Agent。您的目标是：

1. 使用 LangChain 框架构建 Agent
2. 设计 Prompt，让 LLM 能够准确分类单据
3. 实现分类逻辑，支持 5 种单据类型
4. 处理边界情况（未知类型、模糊类型）

Agent 应能够接收单据文本，返回准确的类型标签。

## Success Criteria

- [ ] Agent 能够正确分类采购订单 (PO)
- [ ] Agent 能够正确分类送货单 (Delivery Note)
- [ ] Agent 能够正确分类发票 (Invoice)
- [ ] 对于格式不标准的单据，返回 "unknown" 或最接近的类型
- [ ] 分类响应时间 < 3 秒

## Hints

<details>
<summary>Hint 1 (broad)</summary>
使用 LangChain 的 `ChatPromptTemplate` 设计分类 Prompt。告诉 LLM 单据类型列表，让它返回最匹配的类型。
</details>

<details>
<summary>Hint 2 (more specific)</summary>
Prompt 模板示例：
```python
prompt = ChatPromptTemplate.from_template("""
根据以下文档内容，判断单据类型。
可选类型：purchase_order, delivery_note, quality_report, receiving_note, invoice
只返回类型名称，不要其他内容。

文档内容：
{content}
""")
```
</details>

<details>
<summary>Hint 3 (almost there)</summary>
使用 `data/sample_docs/` 中的示例文件测试分类器：
- `po_sample.txt` → 应分类为 `purchase_order`
- `delivery_sample.txt` → 应分类为 `delivery_note`
- `invoice_sample.txt` → 应分类为 `invoice`

对于返回结果，使用字符串匹配提取类型：
```python
for doc_type in ["purchase_order", "delivery_note", ...]:
    if doc_type in result.lower():
        return doc_type
return "unknown"
```
</details>

## Learning Resources

- [LangChain 文档](https://python.langchain.com/docs/)
- [Prompt Engineering 指南](https://platform.openai.com/docs/guides/prompt-engineering)
- [单据类型说明](../docs/project_report.md)

## Advanced Challenge (Optional)

实现置信度评分：
- 让 LLM 返回分类置信度 (0-1)
- 对于低置信度结果，请求人工确认
- 记录分类历史，用于后续优化
