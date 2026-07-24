# Challenge 05: 三单校验引擎

**Estimated Time:** 60 minutes  
**Difficulty:** Hard

## Introduction

供应链管理的核心流程是"三单匹配"：采购订单 (PO)、送货单、发票必须相互一致。任何差异都可能意味着：

- 数量不符：多收或少收货物
- 价格异常：供应商错误计费
- 物料错误：发错货物

传统方式依赖人工逐单核对，效率低且容易出错。本挑战将构建自动化的三单校验引擎。

## Prerequisites

- Challenge 04 完成 (字段提取)

## Description

构建一个能够自动校验三单一致性的引擎。您的目标是：

1. 实现 PO 与送货单的交叉校验
2. 实现 PO 与发票的交叉校验
3. 支持数量和金额的容差设置
4. 生成详细的校验报告

引擎应能够接收三份单据的结构化数据，输出校验结果和差异详情。

## Success Criteria

- [ ] 实现 PO 号匹配校验
- [ ] 实现物料编码匹配校验
- [ ] 实现数量匹配校验（支持 ±5% 容差）
- [ ] 实现金额匹配校验（支持 ±1% 容差）
- [ ] 生成包含通过/失败状态的校验报告
- [ ] 对于测试数据中的差异，正确识别并报告

## Hints

<details>
<summary>Hint 1 (broad)</summary>
在 `config/settings.yaml` 中定义了校验规则和容差设置。使用这些配置来驱动校验逻辑。
</details>

<details>
<summary>Hint 2 (more specific)</summary>
校验逻辑框架：
```python
def validate(po, delivery, invoice, config):
    results = []
    rules = config["validation"]["cross_check"]
    tolerance = config["validation"]["tolerance"]
    
    for rule in rules:
        po_field, target_field = rule.split(":")
        po_val = po.get(po_field)
        target_val = delivery.get(target_field) or invoice.get(target_field)
        
        # 实现比较逻辑
        # ...
    
    return {"all_pass": all(r["status"] == "pass" for r in results), "details": results}
```
</details>

<details>
<summary>Hint 3 (almost there)</summary>
处理数值比较时注意：
```python
try:
    po_num = float(str(po_val).replace(",", ""))
    target_num = float(str(target_val).replace(",", ""))
    diff_pct = abs(po_num - target_num) / max(po_num, 1) * 100
    
    if "quantity" in rule and diff_pct <= tolerance["quantity_percent"]:
        results.append({"rule": rule, "status": "pass"})
    # ...
except (ValueError, TypeError):
    # 非数值字段，使用字符串比较
    if str(po_val).strip() == str(target_val).strip():
        results.append({"rule": rule, "status": "pass"})
```
</details>

## Learning Resources

- [三单匹配概念](https://www.investopedia.com/terms/t/three-way-match.asp)
- [容差设置最佳实践](https://www.sap.com/documents/2015/03/6d7b68d9-6dbb-4d4f-9b6e-3b0e8d8f5a2c.html)
- [Python 数值处理](https://docs.python.org/3/library/decimal.html)

## Advanced Challenge (Optional)

实现智能异常分类：
- 区分"可接受差异"和"需要审批的异常"
- 根据差异类型推荐处理方式
- 生成人类可读的校验报告 (Markdown 格式)
