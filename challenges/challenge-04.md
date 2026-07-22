# Challenge 04: 字段提取 Agent

**Estimated Time:** 45 minutes  
**Difficulty:** Medium

## Introduction

识别单据类型后，需要从非结构化文本中提取结构化字段。不同类型的单据需要提取不同的字段：

- 采购订单：PO号、供应商、物料编码、数量、单价、金额
- 送货单：送货单号、PO参考、实收数量、送货日期
- 发票：发票号、PO参考、金额、税额、总额

本挑战将构建字段提取 Agent，使用 LLM 从文档中提取结构化数据。

## Prerequisites

- Challenge 03 完成 (单据分类)

## Description

构建一个能够从单据中提取结构化字段的 Agent。您的目标是：

1. 为每种单据类型定义字段列表
2. 设计 Prompt，让 LLM 提取指定字段
3. 解析 LLM 输出为 JSON 格式
4. 处理字段缺失和格式错误

Agent 应能够接收单据文本和类型标签，返回结构化的 JSON 数据。

## Success Criteria

- [ ] 从采购订单中提取至少 8 个字段
- [ ] 从送货单中提取至少 5 个字段
- [ ] 从发票中提取至少 6 个字段
- [ ] 提取结果为有效的 JSON 格式
- [ ] 对于缺失字段，返回 null 或空字符串

## Hints

<details>
<summary>Hint 1 (broad)</summary>
在 `config/settings.yaml` 中定义了每种单据类型的提取字段。使用这些配置来动态生成 Prompt。
</details>

<details>
<summary>Hint 2 (more specific)</summary>
Prompt 模板示例：
```python
fields = config["documents"]["extraction_fields"][doc_type]
prompt = f"""
从以下{doc_type}文档中提取以下字段，以JSON格式返回：
字段列表：{', '.join(fields)}

文档内容：
{content[:3000]}

只返回JSON，格式如：{{"{fields[0]}": "值", ...}}
"""
```
</details>

<details>
<summary>Hint 3 (almost there)</summary>
解析 JSON 输出时处理可能的错误：
```python
import json
try:
    return json.loads(result)
except json.JSONDecodeError:
    # 尝试提取 JSON 部分
    import re
    json_match = re.search(r'\{.*\}', result, re.DOTALL)
    if json_match:
        return json.loads(json_match.group())
    return {"raw": result}
```
</details>

## Learning Resources

- [JSON 提取技术](https://python.langchain.com/docs/modules/model_io/output_parsers/)
- [结构化输出](https://platform.openai.com/docs/guides/structured-outputs)
- [正则表达式教程](https://docs.python.org/3/library/re.html)

## Advanced Challenge (Optional)

实现字段验证：
- 检查数量字段是否为数字
- 验证日期格式 (YYYY-MM-DD)
- 检查金额计算是否正确 (数量 × 单价 = 金额)
