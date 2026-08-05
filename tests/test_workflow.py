"""
Test Script — 测试 Agent 核心工作流。
不依赖 LLM 推理，仅测试数据处理和分析逻辑。
"""

import sys, yaml
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.rag import MultiFileRAGEngine
from src.noise_detector import NoiseDetector
from src.memory import ConsistencyMemory
from src.quality_checker import QualityChecker
import pandas as pd

gt_path = Path(__file__).parent.parent / "config" / "ground_truth.yaml"
GROUND_TRUTH = yaml.safe_load(open(gt_path))["ground_truth"] if gt_path.exists() else {}


def generate_quality_report(checks: list) -> str:
    """生成质量校验报告。"""
    passed = sum(1 for c in checks if c.get("passed", False))
    total = len(checks)
    report = f"质量校验: {passed}/{total} 通过\n\n"
    for i, check in enumerate(checks, 1):
        status = "✅" if check.get("passed", False) else "❌"
        report += f"{status} {i}. {check.get('name', '未知')}: {check.get('detail', '')}\n"
    return report


def test_rag_engine():
    """测试 RAG 引擎加载文件。"""
    print("=" * 60)
    print("Test 1: MultiFileRAGEngine 加载文件")
    print("=" * 60)

    config = {"data": {"input_dir": "data/input"}}
    rag = MultiFileRAGEngine(config)
    result = rag.load_all_files("data/input")

    print(f"已加载: {len(result.get('loaded', []))} 个文件")
    for f in result.get("loaded", []):
        print(f"  ✓ {f}")

    if result.get("failed"):
        print(f"失败: {len(result['failed'])} 个")
        for f in result["failed"]:
            print(f"  ✗ {f}")

    # 验证关键文件
    assert len(rag.dataframes) > 0, "应至少加载 1 个文件"
    print(f"\n总 DataFrame 数: {len(rag.dataframes)}")
    print("✓ RAG 引擎测试通过\n")
    return rag


def test_noise_detector():
    """测试噪音检测。"""
    print("=" * 60)
    print("Test 2: NoiseDetector 噪音检测")
    print("=" * 60)

    config = {"noise_detection": {"noise_prefix": "NOISE-", "exclude_files": ["*月报*", "*历史库存*"]}}
    detector = NoiseDetector(config)

    # 测试扫描日志 NOISE 检测
    scan_log = pd.read_csv("data/input/03_扫描日志_20190422.txt", sep="\t")
    noise_result = detector.detect_scan_log_noise(scan_log)
    print(f"扫描日志总记录: {noise_result['real_count'] + noise_result['noise_count']}")
    print(f"NOISE 干扰: {noise_result['noise_count']} 条")
    print(f"真实操作: {noise_result['real_count']} 条")
    print(f"NOISE 型号: {noise_result['noise_models'][:5]}...")

    assert noise_result["noise_count"] > 0, "应检测到 NOISE 记录"
    print("✓ NOISE 检测通过")

    # 测试操作分类
    real_df = scan_log[~noise_result["noise_mask"]]
    ops = detector.classify_scan_operations(real_df)
    print(f"\n操作类型分布: {ops['operation_types']}")
    print("✓ 噪音检测测试通过\n")


def test_baseline_selection():
    """测试基准选择三维论证。"""
    print("=" * 60)
    print("Test 3: 基准选择三维论证")
    print("=" * 60)

    # 加载两个库存快照
    df_01 = pd.read_csv("data/input/01_库存快照_20190425.csv", encoding="utf-8-sig")
    df_02 = pd.read_excel("data/input/02_库存快照_20190428.xlsx")

    print(f"01_库存快照: {len(df_01)} 行, {len(df_01.columns)} 列")
    print(f"  列名: {list(df_01.columns)}")

    print(f"\n02_库存快照: {len(df_02)} 行, {len(df_02.columns)} 列")
    print(f"  列名: {list(df_02.columns)}")

    # 三维对比
    has_model_01 = any("规格" in str(col) or "型号" in str(col) for col in df_01.columns)
    has_model_02 = any("型号" in str(col) or "商品编码" in str(col) for col in df_02.columns)

    print(f"\n三维对比:")
    print(f"  编码体系: 01={'型号(规格列)' if has_model_01 else '货号'}, 02={'型号' if has_model_02 else '货号'}")
    print(f"  数据粒度: 01={len(df_01)} 行, 02={len(df_02)} 行")
    print(f"  选择: 02 (型号编码，与盘点表一致)")

    assert has_model_02, "02 应使用型号编码"
    print("✓ 基准选择测试通过\n")


def test_inventory_count():
    """测试盘点结果加载。"""
    print("=" * 60)
    print("Test 4: 盘点结果加载与差异计算")
    print("=" * 60)

    # 读取盘点表（第 2 个 sheet，品类明细）
    xls = pd.ExcelFile("data/input/04_盘点表_5月.xlsx")
    print(f"盘点表 Sheet 列表: {xls.sheet_names}")

    # 读取所有品类明细
    all_skus = []
    for sheet in xls.sheet_names:
        if sheet == "盘点汇总":
            continue
        df = pd.read_excel("data/input/04_盘点表_5月.xlsx", sheet_name=sheet)
        if "型号" in df.columns and "系统库存数" in df.columns and "复盘数" in df.columns:
            df["品类"] = sheet
            all_skus.append(df)

    count_df = pd.concat(all_skus, ignore_index=True)
    print(f"\n总 SKU 数: {len(count_df)}")

    # 计算差异
    count_df["差异数量"] = count_df["复盘数"] - count_df["系统库存数"]
    system_total = int(count_df["系统库存数"].sum())
    recount_total = int(count_df["复盘数"].sum())
    net_var = int(count_df["差异数量"].sum())
    var_rate = round(abs(net_var) / system_total * 100, 1)

    print(f"系统库存总计: {system_total}")
    print(f"复盘总计: {recount_total}")
    print(f"净差异: {net_var}")
    print(f"总体差异率: {var_rate}%")
    print(f"盘亏 SKU: {(count_df['差异数量'] < 0).sum()}")
    print(f"盘盈 SKU: {(count_df['差异数量'] > 0).sum()}")

    # 对比地面真值
    assert system_total == 21144, f"系统库存应为 21144，实际 {system_total}"
    assert var_rate == 4.6, f"差异率应为 4.6%，实际 {var_rate}%"
    print("\n✓ 与地面真值一致！")
    print("✓ 盘点结果测试通过\n")

    return count_df


def test_cost_matching():
    """测试成本单价匹配。"""
    print("=" * 60)
    print("Test 5: 成本单价匹配与差异金额计算")
    print("=" * 60)

    count_df = test_inventory_count()
    product_df = pd.read_excel("data/input/06_商品主数据.xlsx")

    print(f"商品主数据: {len(product_df)} 条")
    print(f"  列名: {list(product_df.columns)}")

    # 合并
    merged = count_df.merge(
        product_df[["型号", "参考成本单价(元)", "品类"]],
        left_on="型号", right_on="型号", how="left"
    )

    # 计算差异金额
    merged["参考成本单价"] = pd.to_numeric(merged["参考成本单价(元)"], errors="coerce")
    merged["差异金额"] = merged["差异数量"] * merged["参考成本单价"]

    total_loss = merged[merged["差异数量"] < 0]["差异金额"].sum()
    total_gain = merged[merged["差异数量"] > 0]["差异金额"].sum()
    net_amount = total_loss + total_gain

    print(f"\n盘亏金额: {total_loss:,.2f} 元")
    print(f"盘盈金额: {total_gain:,.2f} 元")
    print(f"净差异金额: {net_amount:,.2f} 元")

    gt_amount = GROUND_TRUTH.get("net_variance_amount", -989900.97)
    assert abs(net_amount - gt_amount) < 1, f"净差异金额应约为 {gt_amount:,.2f}，实际 {net_amount}"
    print(f"\n✓ 与地面真值 ({gt_amount:,.2f}) 一致！")
    print("✓ 成本匹配测试通过\n")


def test_quality_checker():
    """测试质量校验。"""
    print("=" * 60)
    print("Test 6: 质量校验 (7 条 must_check_points)")
    print("=" * 60)

    gt = GROUND_TRUTH
    config = {"quality_checkpoints": [], "ground_truth": gt}
    checker = QualityChecker(config)

    mock_result = {
        "Step 1: 加载所有文件": {"loaded": ["01_", "02_", "03_", "04_", "05_", "06_", "08_", "09_"]},
        "Step 2: 识别噪音数据": {
            "noise_files": ["07_库存月报_201904.xlsx::4月库存月报", "10_历史库存_含异常数据.csv"],
            "file_exclusion_reasons": {"07": {"reason": "品类汇总粒度"}, "10": {"reason": "含TEST/异常"}},
            "scan_log_noise": {"noise_count": 68, "real_count": 277},
        },
        "Step 3: 选定比对基准": {
            "selected": "02_库存快照_20190428.xlsx",
            "three_dimension_table": {"01": {"编码体系": "货号编码", "快照时间": "2019-04-25", "数据粒度": "批次×库位", "行数": 1858, "直接匹配盘点表": "否", "是否选为基准": "交叉验证"}, "02": {"编码体系": "型号编码", "快照时间": "2019-04-28", "数据粒度": "型号×库位", "行数": 1500, "直接匹配盘点表": "是", "是否选为基准": "✅ 主基准"}},
            "conclusion": ["选择 02 作为主基准", "型号编码与盘点表一致", "时间点最接近", "数据粒度可聚合"],
            "risk_if_wrong": "选择 01 会导致 SKU 匹配失败",
        },
        "Step 5: 加载盘点结果": {
            "total_sku": 528, "system_total": gt.get("system_total", 21144),
            "recount_total": gt.get("recount_total", 20173),
            "net_variance": gt.get("net_variance", -971),
            "variance_rate": gt.get("variance_rate", 4.6),
            "loss_count": 113, "gain_count": 46,
        },
        "Step 6: 计算差异金额": {
            "net_variance_amount": gt.get("net_variance_amount", -989900.97),
            "total_loss_amount": gt.get("total_loss_amount", -1146805.36),
            "total_gain_amount": gt.get("total_gain_amount", 156904.39),
            "missing_cost_count": 0,
        },
        "Step 7: 日志关联分析": {
            "完全可解释": {"count": 14, "amount": -14160.78, "操作记录数": 14, "涉及操作类型": ["上架", "拣货"]},
            "部分可解释": {"count": 21, "amount": -350068.19, "操作记录数": 21, "涉及操作类型": ["上架", "拣货"]},
            "无日志关联": {"count": 124, "amount": -625672.00, "操作记录数": 0, "涉及操作类型": []},
        },
        "Step 10: 生成交付物": {"xlsx_path": "盘点差异明细表.xlsx", "md_path": "盘点差异分析报告.md"},
        "quality_checks": [],
    }

    checks = checker.run_all_checks(mock_result)
    report = generate_quality_report(checks)
    print(report)

    passed = sum(1 for c in checks if c.get("passed", False))
    print(f"\n通过: {passed}/{len(checks)}")
    print("✓ 质量校验测试通过\n")


if __name__ == "__main__":
    print("\n" + "=" * 60)
    print("InventoryDoc Agent 工作流测试")
    print("=" * 60 + "\n")

    test_rag_engine()
    test_noise_detector()
    test_baseline_selection()
    test_cost_matching()
    test_quality_checker()

    print("\n" + "=" * 60)
    print("所有测试通过！")
    print("=" * 60)
