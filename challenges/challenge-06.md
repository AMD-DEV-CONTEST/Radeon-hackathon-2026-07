# Challenge 06: 多 Agent 编排

**Estimated Time:** 60 minutes  
**Difficulty:** Hard

## Introduction

单据处理是一个复杂的流程，涉及多个步骤和决策点。单一 Agent 难以处理所有场景，需要多个专业 Agent 协作完成：

1. **Classify Agent** - 识别单据类型
2. **Extract Agent** - 提取结构化字段
3. **Validate Agent** - 三单交叉校验
4. **Entry Agent** - ERP 数据录入
5. **Exception Agent** - 异常处理与通知

本挑战将构建多 Agent 编排系统，协调各 Agent 完成完整的单据处理流程。

## Prerequisites

- Challenge 03 完成 (分类)
- Challenge 04 完成 (提取)
- Challenge 05 完成 (校验)

## Description

构建多 Agent 协作系统。您的目标是：

1. 实现 Agent 编排器，协调各 Agent 执行顺序
2. 设计数据流转机制，确保 Agent 间数据传递
3. 处理异常流程，当校验失败时触发异常 Agent
4. 实现完整的单据处理管道

系统应能够接收原始单据文本，自动完成分类、提取、校验、录入的全流程。

## Success Criteria

- [ ] 实现 Agent 编排器，支持顺序执行
- [ ] 数据在 Agent 间正确流转
- [ ] 校验通过时，触发录入流程
- [ ] 校验失败时，触发异常处理流程
- [ ] 处理完整的单据处理流程（输入 → 分类 → 提取 → 校验 → 结果）
- [ ] 生成处理日志，记录每个 Agent 的执行结果

## Hints

<details>
<summary>Hint 1 (broad)</summary>
使用 LangChain 的 `LCEL` (LangChain Expression Language) 或简单的函数调用来编排 Agent。
</details>

<details>
<summary>Hint 2 (more specific)</summary>
编排器框架：
```python
class DocAgent:
    def __init__(self, config):
        self.classify_agent = DocClassifyAgent(config)
        self.extract_agent = FieldExtractAgent(config)
        self.validate_agent = CrossValidateAgent(config)
    
    def process_document(self, content, filename=""):
        # 1. 分类
        doc_type = self.classify_agent.classify(content)
        
        # 2. 提取
        extracted = self.extract_agent.extract(content, doc_type)
        
        # 3. 存储结果
        result = {"doc_type": doc_type, "extracted_fields": extracted}
        
        return result
```
</details>

<details>
<summary>Hint 3 (almost there)</summary>
处理三单校验需要收集所有单据：
```python
def cross_validate(self, documents):
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
```
</details>

## Learning Resources

- [LangChain LCEL](https://python.langchain.com/docs/expression_language/)
- [多 Agent 系统设计](https://docs.langchain.com/docs/use_cases/multi_agent/)
- [工作流编排模式](https://www.langchain.com/use-cases/agents)

## Advanced Challenge (Optional)

实现并行 Agent 执行：
- 分类和字段提取可以并行进行
- 使用 `asyncio` 或线程池实现并发
- 测量并行执行的性能提升
