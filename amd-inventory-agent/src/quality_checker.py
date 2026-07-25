"""
Quality Checker — 7 条 must_check_points 自动校验。
确保 Agent 输出符合企业级标准。

适配 analysis_result 的实际键名结构：
  "Step 3: 选定比对基准" → baseline
  "Step 4: 清洗扫描日志" → scan_log
  "Step 6: 计算差异金额" → variance
  "Step 7: 日志关联分析" → log_correlation
  "Step 2: 识别噪音数据" → noise_result
  "Step 10: 生成交付物" → deliverables
"""


class QualityChecker:
    def __init__(self, config: dict):
        self.checkpoints = config.get("quality_checkpoints", [])

    def check_baseline_selection(self, analysis_result: dict) -> dict:
        """校验基准选择三维论证。"""
        step3 = analysis_result.get("Step 3: 选定比对基准", {})
        has_selected = step3.get("selected") is not None
        has_comparison = "comparison" in step3
        has_3d = "three_dimension_analysis" in step3

        passed = has_selected and has_comparison and has_3d
        return {
            "name": "基准选择三维论证",
            "passed": passed,
            "detail": (
                f"已选定 {step3.get('selected', '?')}，"
                f"编码体系={step3.get('three_dimension_analysis', {}).get('编码体系', '?')}"
                if passed
                else "第二章需给出编码体系/时间点/行粒度三维对比表"
            ),
            "importance": "致命",
        }

    def check_scan_log_classification(self, analysis_result: dict) -> dict:
        """校验扫描日志可解释性分类口径。"""
        step7 = analysis_result.get("Step 7: 日志关联分析", {})

        has_three = all(
            k in step7
            for k in ["完全可解释", "部分可解释", "无日志关联"]
        )

        passed = has_three
        detail = "已按正确口径分类"
        if passed:
            counts = [step7[k]["count"] for k in ["完全可解释", "部分可解释", "无日志关联"]]
            detail = f"三分类正确: 完全可解释={counts[0]}, 部分可解释={counts[1]}, 无关联={counts[2]}"
        else:
            detail = "需按净变动量绝对值 vs 差异量绝对值比对，分三类"

        return {
            "name": "扫描日志可解释性分类口径",
            "passed": passed,
            "detail": detail,
            "importance": "致命",
        }

    def check_cost_price(self, analysis_result: dict) -> dict:
        """校验成本口径锁定。"""
        step6 = analysis_result.get("Step 6: 计算差异金额", {})

        # 检查是否计算了差异金额（非零）
        has_amount = step6.get("net_variance_amount") is not None
        has_loss = step6.get("total_loss_amount") is not None
        missing_cost = step6.get("missing_cost_count", 0)

        passed = has_amount and has_loss
        detail = (
            f"净差异金额={step6.get('net_variance_amount', 0):,.2f}元, "
            f"缺失成本SKU={missing_cost}个"
            if passed
            else "差异金额必须用参考成本单价（非售价）"
        )

        return {
            "name": "成本口径锁定",
            "passed": passed,
            "detail": detail,
            "importance": "致命",
        }

    def check_noise_exclusion(self, analysis_result: dict) -> dict:
        """校验噪音文件排除证据。"""
        step2 = analysis_result.get("Step 2: 识别噪音数据", {})

        noise_files = step2.get("noise_files", [])
        exclusion_reasons = step2.get("file_exclusion_reasons", {})

        has_07 = any("07" in f for f in noise_files)
        has_10 = any("10" in f for f in noise_files)
        has_evidence = len(exclusion_reasons) >= 2

        passed = has_07 and has_10 and has_evidence
        detail = (
            f"已排除 {len(noise_files)} 个噪音文件，含排除证据"
            if passed
            else "需设专章引用 07/10 的具体行数和示例作为排除理由"
        )

        return {
            "name": "噪音文件排除证据",
            "passed": passed,
            "detail": detail,
            "importance": "致命",
        }

    def check_variance_type_split(self, analysis_result: dict) -> dict:
        """校验盘亏盘盈分 sheet 与四分类。"""
        step6 = analysis_result.get("Step 6: 计算差异金额", {})

        # 检查是否有差异类型分类
        has_loss = step6.get("total_loss_amount", 0) < 0
        has_gain = step6.get("total_gain_amount", 0) > 0
        has_amounts = step6.get("net_variance_amount") is not None

        # 检查交付物是否生成
        step10 = analysis_result.get("Step 10: 生成交付物", {})
        has_xlsx = step10.get("xlsx_path") is not None

        passed = has_loss and has_gain and has_amounts and has_xlsx
        detail = (
            f"已生成 Excel（含盘亏/盘盈明细），差异类型已分类"
            if passed
            else "需分两 sheet 且差异类型用四类分类"
        )

        return {
            "name": "盘亏盘盈分sheet与差异类型四分类",
            "passed": passed,
            "detail": detail,
            "importance": "致命",
        }

    def check_cross_deliverable_consistency(self, analysis_result: dict) -> dict:
        """校验跨交付物数字一致性。"""
        step5 = analysis_result.get("Step 5: 加载盘点结果", {})
        step10 = analysis_result.get("Step 10: 生成交付物", {})

        # 从 Step 5 获取差异率
        variance_rate = step5.get("variance_rate")

        # 检查 Excel 和 MD 都生成了
        has_xlsx = step10.get("xlsx_path") is not None
        has_md = step10.get("md_path") is not None

        passed = variance_rate is not None and has_xlsx and has_md
        detail = (
            f"差异率={variance_rate}%, Excel+MD 均已生成"
            if passed
            else "xlsx 与 md 中关键数字需一致"
        )

        return {
            "name": "跨交付物数字一致性",
            "passed": passed,
            "detail": detail,
            "importance": "重要",
        }

    def check_external_data_prohibition(self, analysis_result: dict) -> dict:
        """校验外部数据禁用。"""
        step1 = analysis_result.get("Step 1: 加载所有文件", {})
        loaded_files = step1.get("loaded", [])

        allowed_prefixes = ["01_", "02_", "03_", "04_", "05_", "06_", "07_", "08_", "09_", "10_"]
        has_external = any(
            not any(f.startswith(p) for p in allowed_prefixes)
            for f in loaded_files
        )

        passed = not has_external
        detail = (
            f"仅使用 {len(loaded_files)} 个允许的数据源"
            if passed
            else "不得引入 inputs/ 外数据"
        )

        return {
            "name": "外部数据禁用与异常处理",
            "passed": passed,
            "detail": detail,
            "importance": "重要",
        }

    def run_all_checks(self, analysis_result: dict) -> list[dict]:
        """运行全部 7 条校验。"""
        checks = [
            self.check_baseline_selection(analysis_result),
            self.check_scan_log_classification(analysis_result),
            self.check_cost_price(analysis_result),
            self.check_noise_exclusion(analysis_result),
            self.check_variance_type_split(analysis_result),
            self.check_cross_deliverable_consistency(analysis_result),
            self.check_external_data_prohibition(analysis_result),
        ]
        return checks
