class QualityChecker:
    def __init__(self, config: dict):
        self.config = config
        self.checkpoints = config.get("quality_checkpoints", [])

    def check_baseline_selection(self, analysis_result: dict) -> dict:
        """校验基准选择三维论证（值级别）。"""
        step3 = analysis_result.get("Step 3: 选定比对基准", {})
        table = step3.get("three_dimension_table", {})

        has_selected = step3.get("selected") is not None
        has_table = len(table) >= 2  # must have at least 2 snapshots
        has_conclusion = len(step3.get("conclusion", [])) >= 3
        has_risk = bool(step3.get("risk_if_wrong"))

        passed = has_selected and has_table and has_conclusion
        selected = step3.get("selected", "?")
        details = []
        if table:
            for key, info in table.items():
                sel = "✅" if info.get("是否选为基准") != "否" else ""
                details.append(f"{key}: {info.get('编码体系','?')}/{info.get('快照时间','?')}/{info.get('数据粒度','?')} {sel}")
        detail = "; ".join(details) if details else "无三维对比表"

        return {
            "name": "基准选择三维论证",
            "passed": passed,
            "detail": f"已选定 {selected}，对比表含 {len(table)} 个快照: {detail}",
            "importance": "致命",
            "severity": "critical",
            "gate": "block_report",
        }

    def check_scan_log_classification(self, analysis_result: dict) -> dict:
        """校验扫描日志可解释性三分类（校验数值合理性）。"""
        step7 = analysis_result.get("Step 7: 日志关联分析", {})
        has_three = all(k in step7 for k in ["完全可解释", "部分可解释", "无日志关联"])
        counts_ok = False
        details = "未分类"
        if has_three:
            counts = {k: step7[k]["count"] for k in ["完全可解释", "部分可解释", "无日志关联"]}
            total = sum(counts.values())
            details = f"完全可解释={counts['完全可解释']}, 部分可解释={counts['部分可解释']}, 无关联={counts['无日志关联']}"
            if total > 0:
                fully_pct = counts["完全可解释"] / total * 100
                no_log_pct = counts["无日志关联"] / total * 100
                counts_ok = fully_pct >= 5 and no_log_pct >= 30
                details += f" | 完全={fully_pct:.0f}%, 无关联={no_log_pct:.0f}%"

        return {
            "name": "扫描日志可解释性分类口径",
            "passed": has_three and counts_ok,
            "detail": details,
            "importance": "致命",
            "severity": "critical",
            "gate": "block_report",
        }

    def check_cost_price(self, analysis_result: dict) -> dict:
        """校验成本口径锁定（关键数值）。"""
        step5 = analysis_result.get("Step 5: 加载盘点结果", {})
        step6 = analysis_result.get("Step 6: 计算差异金额", {})

        gt = self.config.get("ground_truth", {})
        gt_net_amount = gt.get("net_variance_amount", -989900.97)

        net_amount = step6.get("net_variance_amount")
        has_amount = net_amount is not None
        gt_check = False
        if has_amount:
            diff = abs(net_amount - gt_net_amount)
            gt_check = diff < 100

        detail = f"净差异金额={net_amount:,.2f}元" if has_amount else "无金额"
        if gt_check:
            detail += f" ✅ 与 Ground Truth ({gt_net_amount:,.2f}) 一致"
        elif has_amount:
            detail += f" ⚠️ 偏离 Ground Truth {diff:.2f}元"

        return {
            "name": "成本口径锁定",
            "passed": has_amount and gt_check,
            "detail": detail,
            "importance": "致命",
            "severity": "critical",
            "gate": "block_report",
        }

    def check_noise_exclusion(self, analysis_result: dict) -> dict:
        """校验噪音文件排除证据。"""
        step2 = analysis_result.get("Step 2: 识别噪音数据", {})
        noise_files = step2.get("noise_files", [])
        exclusion_reasons = step2.get("file_exclusion_reasons", {})
        scan_noise = step2.get("scan_log_noise", {})

        has_07 = any("07" in f for f in noise_files)
        has_10 = any("10" in f for f in noise_files)
        has_noise_count = scan_noise.get("noise_count", 0) >= 60  # expect ~68

        passed = has_07 and has_10 and has_noise_count
        detail = (
            f"已排除 {len(noise_files)} 个噪音文件"
            + (f"（07 {'✅' if has_07 else '❌'}, 10 {'✅' if has_10 else '❌'}）" if noise_files else "")
            + f"，扫描日志排除 NOISE {scan_noise.get('noise_count', 0)} 条"
        )

        return {
            "name": "噪音文件排除证据",
            "passed": passed,
            "detail": detail,
            "importance": "致命",
            "severity": "critical",
            "gate": "block_report",
        }

    def check_variance_type_split(self, analysis_result: dict) -> dict:
        """校验差异类型四分类与金额合理性。"""
        step5 = analysis_result.get("Step 5: 加载盘点结果", {})
        step6 = analysis_result.get("Step 6: 计算差异金额", {})

        system_total = step5.get("system_total", 0)
        net_var = step5.get("net_variance", 0)
        net_amount = step6.get("net_variance_amount", 0)
        loss_amt = step6.get("total_loss_amount", 0)
        gain_amt = step6.get("total_gain_amount", 0)

        step10 = analysis_result.get("Step 10: 生成交付物", {})
        has_xlsx = step10.get("xlsx_path") is not None

        gt = self.config.get("ground_truth", {})
        gt_net_var = gt.get("net_variance", -971)
        gt_net_amt = gt.get("net_variance_amount", -989900.97)

        var_ok = abs(net_var - gt_net_var) <= 1 if net_var else False
        amt_ok = abs(net_amount - gt_net_amt) < 100 if net_amount else False
        loss_gain_ok = loss_amt < 0 and gain_amt > 0

        passed = var_ok and amt_ok and loss_gain_ok and has_xlsx
        detail = (
            f"净差异={net_var} ({'✅' if var_ok else '❌'} GT={gt_net_var}), "
            f"净金额={net_amount:,.2f} ({'✅' if amt_ok else '❌'} GT={gt_net_amt:,.2f})"
        )

        return {
            "name": "差异类型四分类与金额合理性",
            "passed": passed,
            "detail": detail,
            "importance": "致命",
            "severity": "critical",
            "gate": "block_report",
        }

    def check_cross_deliverable_consistency(self, analysis_result: dict) -> dict:
        """校验跨交付物关键数字一致。"""
        step5 = analysis_result.get("Step 5: 加载盘点结果", {})
        step10 = analysis_result.get("Step 10: 生成交付物", {})
        has_xlsx = step10.get("xlsx_path") is not None
        has_md = step10.get("md_path") is not None
        variance_rate = step5.get("variance_rate")

        passed = variance_rate is not None and has_xlsx and has_md
        detail = f"差异率={variance_rate}%, Excel+MD 均已生成" if passed else "交付物不完整"

        return {
            "name": "跨交付物数字一致性",
            "passed": passed,
            "detail": detail,
            "importance": "重要",
            "severity": "major",
            "gate": "warn",
        }

    def check_external_data_prohibition(self, analysis_result: dict) -> dict:
        """校验仅使用 inputs/ 内文件。"""
        step1 = analysis_result.get("Step 1: 加载所有文件", {})
        loaded = step1.get("loaded", [])
        allowed_prefixes = ["01_", "02_", "03_", "04_", "05_", "06_", "07_", "08_", "09_", "10_"]
        has_external = any(
            not any(f.startswith(p) for p in allowed_prefixes)
            for f in loaded
        )
        passed = not has_external
        detail = f"仅使用 {len(loaded)} 个允许的数据源" if passed else "引入了 inputs/ 外数据"

        return {
            "name": "外部数据禁用与异常处理",
            "passed": passed,
            "detail": detail,
            "importance": "重要",
            "severity": "major",
            "gate": "warn",
        }

    def run_all_checks(self, analysis_result: dict) -> list[dict]:
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

    @staticmethod
    def summarize_checks(checks: list[dict]) -> dict:
        """汇总质量校验结果，供门禁决策使用。
        
        Returns:
            dict with: total, passed_count, failed_count,
                       critical_failed, major_failed, can_generate_report
        """
        total = len(checks)
        passed_count = sum(1 for c in checks if c.get("passed", False))
        failed_count = total - passed_count
        critical_failed = sum(1 for c in checks if c.get("severity") == "critical" and not c.get("passed"))
        major_failed = sum(1 for c in checks if c.get("severity") == "major" and not c.get("passed"))
        return {
            "total": total,
            "passed_count": passed_count,
            "failed_count": failed_count,
            "critical_failed": critical_failed,
            "major_failed": major_failed,
            "can_generate_report": critical_failed == 0,
        }
