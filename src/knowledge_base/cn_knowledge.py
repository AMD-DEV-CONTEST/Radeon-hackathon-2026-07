"""Small auditable domestic-market knowledge context for the competition demo."""

CN_KNOWLEDGE = """中国境内证券市场策略约束：
1. A股普通股票买入后通常下一交易日方可卖出（T+1）；演示回测必须避免当日回转卖出。
2. 股票委托数量通常按100股整数手处理；不足一手的买入委托应拒绝或向下取整。
3. 策略必须显式考虑涨跌停、停牌、滑点、佣金和卖出印花税，禁止把无法成交的信号视作成交。
4. 普通现货账户不得裸卖空；entry.short 应为 null，constraints.allow_short 应为 false。
5. 回测必须披露数据来源。合成行情只能用于系统演示，不得宣传为真实历史收益。
6. 风险优先：stop_loss 必须为负数，单标的最大仓位建议不超过30%，最大回撤超过15%应人工复核。
7. 禁止未来函数、前视偏差和幸存者偏差；回测结果不构成投资建议。
"""


def retrieve_cn_knowledge(query: str) -> str:
    return f"用户需求：{query}\n\n{CN_KNOWLEDGE}"
