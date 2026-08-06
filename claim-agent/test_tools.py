# -*- coding: utf-8 -*-
"""
test_tools.py — 四工具单元测试

- decision：纯规则计算，确定性断言（三层判定 + 封顶 + 拒赔）
- rag：离线检索断言（依赖 data/chroma 已建库）
- verify：联网实测官方查验（经隧道；不可达时告警不判失败）
- ocr：联网实测多模态提取（经隧道 localhost:8000；不可达时告警不判失败）

运行：python test_tools.py
"""

import os
import json
import traceback

from tools.decision_tool import decide_claim_core
from tools.rag_tool import query_catalog
from tools.verify_tool import verify_invoice_core
from tools.ocr_tool import extract_invoice

PASS, FAIL, WARN = "[PASS]", "[FAIL]", "[WARN]"
_results = []


def check(cond, name, detail=""):
    tag = PASS if cond else FAIL
    _results.append(cond)
    print(f"  {tag} {name}" + (f" — {detail}" if detail else ""))
    return cond


# ---------------------------------------------------------------------------
# 1) decision：纯规则计算
# ---------------------------------------------------------------------------
def test_decision():
    print("\n== decision_tool ==")
    items = [
        {"name": "阿莫西林胶囊", "priceSum": 120.0, "category": "甲类",
         "in_catalog": True, "commercial_innovative": False,
         "self_pay_2": 0.0, "reimburse_ratio": 0.8, "cap": None},
        {"name": "某乙类药", "priceSum": 140.0, "category": "乙类",
         "in_catalog": True, "commercial_innovative": False,
         "self_pay_2": 0.1, "reimburse_ratio": 0.7, "cap": None},
        {"name": "某创新靶向药", "priceSum": 100.0, "category": "目录外",
         "in_catalog": False, "commercial_innovative": True,
         "self_pay_2": 0.0, "reimburse_ratio": 0.0, "cap": None},
        {"name": "某进口保健品", "priceSum": 40.0, "category": "目录外",
         "in_catalog": False, "commercial_innovative": False,
         "self_pay_2": 0.0, "reimburse_ratio": 0.0, "cap": None},
    ]
    out = decide_claim_core(True, items)
    print("   " + out["summary_text"])
    check(out["total_amount"] == 400.0, "总金额=400", str(out["total_amount"]))
    check(out["items"][0]["medical_reimbursable"] == 96.0, "甲类 120*0.8=96", str(out["items"][0]["medical_reimbursable"]))
    check(out["items"][1]["medical_reimbursable"] == 88.2, "乙类(140-14)*0.7=88.2", str(out["items"][1]["medical_reimbursable"]))
    check(out["items"][2]["commercial_reimbursable"] == 100.0, "商保创新药商保=100", str(out["items"][2]["commercial_reimbursable"]))
    check(out["items"][3]["medical_reimbursable"] == 0.0 and out["items"][3]["commercial_reimbursable"] == 0.0, "目录外=0")
    check(out["total_medical_insurance"] == 184.2, "医保合计=184.2", str(out["total_medical_insurance"]))
    check(out["total_commercial"] == 100.0, "商保合计=100", str(out["total_commercial"]))
    check(out["total_reimbursable"] == 284.2, "可报合计=284.2", str(out["total_reimbursable"]))
    check(out["conclusion"] == "部分通过", "结论=部分通过", out["conclusion"])

    # 封顶线
    capped = decide_claim_core(True, [
        {"name": "封顶药", "priceSum": 200.0, "category": "甲类", "in_catalog": True,
         "commercial_innovative": False, "self_pay_2": 0.0, "reimburse_ratio": 0.8, "cap": 100.0}])
    check(capped["items"][0]["medical_reimbursable"] == 100.0, "封顶 min(160,100)=100", str(capped["items"][0]["medical_reimbursable"]))

    # 全额通过
    full = decide_claim_core(True, [
        {"name": "全报药", "priceSum": 100.0, "category": "甲类", "in_catalog": True,
         "commercial_innovative": False, "self_pay_2": 0.0, "reimburse_ratio": 1.0, "cap": None}])
    check(full["conclusion"] == "全额通过", "结论=全额通过", full["conclusion"])

    # 拒赔（真伪未通过）
    rejected = decide_claim_core(False, items)
    check(rejected["conclusion"] == "拒赔" and rejected["total_reimbursable"] == 0.0, "verified=False → 拒赔")


# ---------------------------------------------------------------------------
# 2) rag：离线检索
# ---------------------------------------------------------------------------
def test_rag():
    print("\n== drug_catalog_rag_tool ==")
    try:
        jia = query_catalog("阿莫西林胶囊")["matches"][0]
        check(jia["category"] == "甲类" and jia["in_catalog"], "阿莫西林胶囊→甲类 in_catalog", jia["category"])
        outside = query_catalog("蜂胶软胶囊")["matches"][0]
        check(outside["category"] == "目录外" and not outside["in_catalog"], "蜂胶软胶囊→目录外", outside["category"])
        innov = query_catalog("某创新抗肿瘤靶向药A")["matches"][0]
        check(innov["commercial_innovative"] is True, "创新药→commercial_innovative", str(innov["commercial_innovative"]))
        none_hit = query_catalog("感冒清热颗粒")["matches"]
        check(all(not m["in_catalog"] for m in none_hit), "目录无→语义分支全 in_catalog=False")
    except Exception as e:
        check(False, "rag 检索异常", str(e))


# ---------------------------------------------------------------------------
# 3) verify：联网实测（容错）
# ---------------------------------------------------------------------------
def test_verify():
    print("\n== invoice_verify_tool (联网) ==")
    # M1 已确认可查验通过的样例发票
    out = verify_invoice_core("", "26442000007766995501", "20260708", "777.35")
    print("   verified=%s code=%s message=%s" % (out.get("verified"), out.get("code"), out.get("message")))
    if out.get("code") in ("-1",):
        print(f"   {WARN} 查验接口不可达（网络/隧道问题），跳过断言")
        return
    check(out.get("verified") is True, "样例发票查验通过 code=0")
    check(bool(out.get("official", {}).get("xfmc")), "官方回填销售方名称")


# ---------------------------------------------------------------------------
# 4) ocr：联网实测（容错，需隧道 localhost:8000）
# ---------------------------------------------------------------------------
def test_ocr():
    print("\n== invoice_ocr_tool (联网/隧道) ==")
    img = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fapiao2.jpg")
    if not os.path.exists(img):
        print(f"   {WARN} 样例图片 fapiao2.jpg 不存在，跳过")
        return
    out = extract_invoice(img)
    if out.get("error"):
        print(f"   {WARN} 模型不可达/解析失败（{out['error']}），跳过断言")
        return
    print("   fphm=%s date=%s code=%s items=%d" % (out.get("fphm"), out.get("date"), out.get("code"), len(out.get("items", []))))
    check(bool(out.get("fphm")), "提取到发票号码 fphm")
    check(isinstance(out.get("items"), list), "items 为列表")


def main():
    test_decision()
    test_rag()
    test_verify()
    test_ocr()
    total = len(_results)
    passed = sum(1 for r in _results if r)
    print(f"\n==== 断言 {passed}/{total} 通过 ====")


if __name__ == "__main__":
    main()
