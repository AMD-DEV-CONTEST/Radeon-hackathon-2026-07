# -*- coding: utf-8 -*-
"""
test_rag.py — 药品目录检索器回归测试

覆盖：精确匹配、带规格模糊匹配、四类分类（甲/乙/目录外/商保创新药）、
语义召回、阈值判定目录外。运行：
  python test_rag.py
"""

import json
from rag.retriever import get_retriever

# (查询, 期望说明)
CASES = [
    ("阿莫西林胶囊", "甲类·精确"),
    ("阿莫西林 0.25g*24粒", "甲类·带规格模糊"),
    ("阿托伐他汀钙片", "乙类·精确"),
    ("蜂胶软胶囊", "目录外·不予报销"),
    ("某创新抗肿瘤靶向药A", "商保创新药"),
    ("布洛芬", "甲类·通用名"),
    ("阿莫西林钠克拉维酸钾", "语义召回（目录无，看是否判目录外）"),
]


def main():
    r = get_retriever()
    print(f"检索器就绪：collection={r.collection_name}, top_k={r.top_k}, threshold={r.score_threshold}\n")
    for query, desc in CASES:
        out = r.search(query)
        matches = out.get("matches", [])
        print(f"■ 查询: {query}    [{desc}]")
        if out.get("error"):
            print(f"   ERROR: {out['error']}")
        if not matches:
            print("   (无匹配)")
        for m in matches[:3]:
            print(
                f"   -> {m['matched_name'] or '(无)':16s} "
                f"类别={m['category'] or '-':4s} "
                f"商保创新={str(m['commercial_innovative']):5s} "
                f"报销比例={m['reimburse_ratio']} 自付二={m['self_pay_2']} "
                f"score={m['score']} in_catalog={m['in_catalog']} ({m.get('match_type')})"
            )
        print()


if __name__ == "__main__":
    main()
