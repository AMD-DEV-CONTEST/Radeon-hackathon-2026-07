# -*- coding: utf-8 -*-
"""
tools/rag_tool.py — 药品目录语义检索工具

封装 rag.retriever 的检索器，供 Agent 按药品名查询目录条目
（类别 / 报销比例 / 自付 / 封顶 / 是否商保创新药 / in_catalog）。
"""

from langchain_core.tools import tool

import tools  # noqa: F401  注入 sys.path
import config as cfg
from rag.retriever import get_retriever


def query_catalog(drug_name: str, top_k: int = None) -> dict:
    """按药品名检索药品目录，返回 {query, matches:[...]}。"""
    top_k = top_k or cfg.RAG_TOP_K
    retriever = get_retriever()
    return retriever.search(drug_name, top_k=top_k)


@tool
def drug_catalog_rag_tool(drug_name: str, top_k: int = 3) -> dict:
    """在药品报销目录知识库中检索与给定药品名最匹配的条目。入参 drug_name 为药品名称
    （可含规格），top_k 为返回条数。返回 matches 列表，每项含 matched_name / category
    (甲类/乙类/目录外) / commercial_innovative(是否商保创新药) / self_pay_2(乙类先行自付) /
    reimburse_ratio(统筹报销比例) / cap(封顶) / score(相似度) / in_catalog(是否在医保目录内)。
    用于判断某药品能否报销及报销参数。"""
    return query_catalog(drug_name, top_k=top_k)
