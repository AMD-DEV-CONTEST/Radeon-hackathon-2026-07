"""
Agent Core — 基于 10 步工作流的库存盘点差异分析 Agent。
运行在 AMD Radeon GPU + ROCm 上，完全本地化部署。

工作流来源: workflow.txt (库存控制专员 × 循环盘点差异分析与库存调账)
地面真值: 系统库存 21,144 / 复盘 20,173 / 净差异 -971 / 差异率 4.6%
"""

import yaml
import json
from pathlib import Path
from datetime import datetime

import pandas as pd
import numpy as np

from .rag import MultiFileRAGEngine
from .noise_detector import NoiseDetector
from .tools import get_tools
from .memory import ConsistencyMemory
from .quality_checker import QualityChecker
from .report_generator import ReportGenerator

try:
    from .ui import create_ui
except ImportError:
    create_ui = None


def load_config() -> dict:
    config_path = Path(__file__).parent.parent / "config" / "settings.yaml"
    with open(config_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


class InventoryDocAgent:
    def __init__(self, config: dict):
        self.config = config
        self.rag = MultiFileRAGEngine(config)
        self.noise_detector = NoiseDetector(config)
        self.memory = ConsistencyMemory(config)
        self.quality_checker = QualityChecker(config)
        self.report_generator = ReportGenerator(config)
        self.tools = get_tools()
        self.analysis_result = {}

        # 中间结果存储
        self._baseline_df = None
        self._scan_log_real = None
        self._scan_log_window = None
        self._inventory_count_df = None
        self._product_master = None
        self._location_master = None
        self._variance_df = None
        self._inbound_df = None
        self._outbound_df = None

    def run_workflow(self, input_dir: str, output_dir: str) -> dict:
        """执行完整的 10 步工作流。"""
        output_path = Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)

        steps = [
            ("Step 1: 加载所有文件", self._step1_load_files),
            ("Step 2: 识别噪音数据", self._step2_detect_noise),
            ("Step 3: 选定比对基准", self._step3_select_baseline),
            ("Step 4: 清洗扫描日志", self._step4_clean_scan_log),
            ("Step 5: 加载盘点结果", self._step5_load_inventory_count),
            ("Step 6: 计算差异金额", self._step6_calculate_variance),
            ("Step 7: 日志关联分析", self._step7_correlate_scan_log),
            ("Step 8: 库位状态校验", self._step8_check_location_status),
            ("Step 9: 品类维度分析", self._step9_analyze_by_category),
            ("Step 10: 生成交付物", lambda: self._step10_generate_deliverables(output_dir)),
        ]

        for step_name, step_func in steps:
            try:
                result = step_func()
                self.analysis_result[step_name] = result
            except Exception as e:
                self.analysis_result[step_name] = {"error": str(e)}

        # 质量校验
        self.analysis_result["quality_checks"] = self.quality_checker.run_all_checks(
            self.analysis_result
        )

        # 保存分析结果
        self._save_analysis_result(output_dir)

        return self.analysis_result

    # ============================================================
    # Step 1: 加载所有文件
    # ============================================================
    def _step1_load_files(self) -> dict:
        """加载目录下所有支持的数据文件。"""
        input_dir = self.config.get("data", {}).get("input_dir", "data/input")
        load_result = self.rag.load_all_files(input_dir)

        # 加载关键文件到实例变量
        self._load_key_dataframes()

        return {
            "loaded": load_result.get("loaded", []),
            "failed": load_result.get("failed", []),
            "total_files": len(load_result.get("loaded", [])),
        }

    def _load_key_dataframes(self):
        """将关键文件加载到实例变量。"""
        # 特殊处理盘点表：合并所有品类 sheet
        inventory_sheets = []
        for key, df in self.rag.dataframes.items():
            if "盘点表" in key and "汇总" not in key:
                inventory_sheets.append(df)

        if inventory_sheets:
            self._inventory_count_df = pd.concat(inventory_sheets, ignore_index=True)

        for key, df in self.rag.dataframes.items():
            if "库存快照" in key and "xlsx" in key.lower():
                self._baseline_df = df
            elif "扫描日志" in key:
                self._scan_log_real = df
            elif "商品主数据" in key:
                self._product_master = df
            elif "库位主数据" in key:
                self._location_master = df
            elif "入库明细" in key:
                self._inbound_df = df
            elif "出库记录" in key:
                self._outbound_df = df

    # ============================================================
    # Step 2: 识别噪音数据
    # ============================================================
    def _step2_detect_noise(self) -> dict:
        """识别噪音文件和扫描日志中的 NOISE 干扰。"""
        results = {
            "noise_files": [],
            "scan_log_noise": {},
            "history_anomalies": {},
            "file_exclusion_reasons": {},
        }

        for key, df in self.rag.dataframes.items():
            # 检测扫描日志 NOISE
            if "扫描日志" in key:
                results["scan_log_noise"] = self.noise_detector.detect_scan_log_noise(df)

            # 检测历史库存异常
            elif "历史库存" in key:
                results["history_anomalies"] = self.noise_detector.detect_history_anomalies(df)
                results["noise_files"].append(key)
                results["file_exclusion_reasons"][key] = {
                    "reason": "含约 200 条 TEST/异常记录，负数库存，时间远早于盘点周期，货号编码无法映射",
                    "anomaly_count": results["history_anomalies"].get("total_anomalies", 0),
                }

            # 检测月报（品类汇总粒度）
            elif "月报" in key:
                results["noise_files"].append(key)
                results["file_exclusion_reasons"][key] = {
                    "reason": "品类汇总粒度（仅 10 行），月度口径不匹配时点快照，备注提示数据不完整",
                    "row_count": len(df),
                }

        return results

    # ============================================================
    # Step 3: 选定比对基准（三维论证）
    # ============================================================
    def _step3_select_baseline(self) -> dict:
        """从库存快照中选定正确的比对基准。"""
        snapshots = {}
        for key, df in self.rag.dataframes.items():
            if "库存快照" in key:
                snapshots[key] = df

        if not snapshots:
            return {"selected": None, "reason": "未找到库存快照文件"}

        # 三维对比分析
        comparison = {}
        for key, df in snapshots.items():
            has_model_code = any(
                col for col in df.columns
                if any(kw in str(col) for kw in ["型号", "商品编码", "规格"])
            )
            has_batch_code = any(
                col for col in df.columns
                if any(kw in str(col) for kw in ["货号", "批号"])
            )

            comparison[key] = {
                "编码体系": "型号编码" if has_model_code else "货号编码",
                "行数": len(df),
                "列数": len(df.columns),
                "列名": list(df.columns),
            }

        # 选择逻辑：优先选型号编码的 xlsx
        selected = None
        for key in sorted(snapshots.keys()):
            if "xlsx" in key.lower() and comparison[key]["编码体系"] == "型号编码":
                selected = key
                break

        if not selected:
            # 退而求其次：选型号编码的
            for key, info in comparison.items():
                if info["编码体系"] == "型号编码":
                    selected = key
                    break

        if not selected:
            # 最后选择第一个
            selected = list(snapshots.keys())[0]

        # 论证理由
        baseline_comparison = {}
        for key, info in comparison.items():
            is_selected = key == selected
            baseline_comparison[key] = {
                **info,
                "是否选为基准": "是" if is_selected else "否",
            }

        return {
            "selected": selected,
            "reason": f"编码体系为{comparison[selected]['编码体系']}，与盘点表一致",
            "comparison": baseline_comparison,
            "three_dimension_analysis": {
                "编码体系": comparison[selected]["编码体系"],
                "数据粒度": f"{comparison[selected]['行数']} 行",
                "列结构": comparison[selected]["列名"],
            },
        }

    # ============================================================
    # Step 4: 清洗扫描日志
    # ============================================================
    def _step4_clean_scan_log(self) -> dict:
        """清洗扫描日志，排除 NOISE 干扰，保留真实操作。"""
        if self._scan_log_real is None:
            return {"error": "未找到扫描日志文件"}

        df = self._scan_log_real
        noise_result = self.noise_detector.detect_scan_log_noise(df)

        # 排除 NOISE 记录
        real_df = df[~noise_result["noise_mask"]].copy()

        # 按操作类型分类
        op_stats = self.noise_detector.classify_scan_operations(real_df)

        # 提取时间窗口 4/25-4/28 的记录
        if "时间" in real_df.columns:
            real_df["_parsed_time"] = pd.to_datetime(real_df["时间"], format="%Y-%m-%d %H:%M:%S", errors="coerce")
            window_start = pd.Timestamp("2019-04-25")
            window_end = pd.Timestamp("2019-04-28 23:59:59")
            window_mask = (real_df["_parsed_time"] >= window_start) & (real_df["_parsed_time"] <= window_end)
            self._scan_log_window = real_df[window_mask].copy()
            window_count = len(self._scan_log_window)
        else:
            self._scan_log_window = real_df
            window_count = len(real_df)

        return {
            "total_records": len(df),
            "noise_removed": noise_result["noise_count"],
            "noise_models": noise_result.get("noise_models", []),
            "real_records": len(real_df),
            "window_records": window_count,
            "operations": op_stats,
        }

    # ============================================================
    # Step 5: 加载盘点结果
    # ============================================================
    def _step5_load_inventory_count(self) -> dict:
        """加载盘点结果，以复盘数为准。"""
        if self._inventory_count_df is None:
            return {"error": "未找到盘点表文件"}

        df = self._inventory_count_df

        # 检查必要列
        required_cols = ["型号", "系统库存数", "复盘数"]
        missing_cols = [col for col in required_cols if col not in df.columns]

        if missing_cols:
            return {"error": f"盘点表缺少必要列: {missing_cols}"}

        # 计算差异（以复盘数为准）
        df["差异数量"] = df["复盘数"] - df["系统库存数"]
        df["差异方向"] = df["差异数量"].apply(
            lambda x: "盘亏" if x < 0 else ("盘盈" if x > 0 else "一致")
        )

        # 初盘纠错记录
        if "初盘数" in df.columns:
            correction_mask = df["初盘数"] != df["复盘数"]
            correction_df = df[correction_mask].copy()
        else:
            correction_df = pd.DataFrame()

        # 统计
        stats = {
            "total_sku": len(df),
            "system_total": int(df["系统库存数"].sum()),
            "recount_total": int(df["复盘数"].sum()),
            "net_variance": int(df["差异数量"].sum()),
            "variance_rate": round(abs(df["差异数量"].sum()) / df["系统库存数"].sum() * 100, 1),
            "loss_count": int((df["差异数量"] < 0).sum()),
            "gain_count": int((df["差异数量"] > 0).sum()),
            "consistent_count": int((df["差异数量"] == 0).sum()),
            "correction_count": len(correction_df),
            "columns": list(df.columns),
        }

        # 记录关键数字到记忆
        self.memory.record_key_number("系统库存总计", stats["system_total"], "04_盘点表")
        self.memory.record_key_number("复盘总计", stats["recount_total"], "04_盘点表")
        self.memory.record_key_number("净差异", stats["net_variance"], "计算")
        self.memory.record_key_number("总体差异率", stats["variance_rate"], "计算")

        self._inventory_count_df = df
        self._correction_df = correction_df

        return stats

    # ============================================================
    # Step 6: 计算差异金额
    # ============================================================
    def _step6_calculate_variance(self) -> dict:
        """为每个 SKU 计算差异金额，匹配成本单价。"""
        if self._inventory_count_df is None or self._product_master is None:
            return {"error": "缺少盘点表或商品主数据"}

        count_df = self._inventory_count_df.copy()
        product_df = self._product_master.copy()

        # 确保型号列名一致
        count_model_col = "型号"
        product_model_col = None
        for col in product_df.columns:
            if "型号" in str(col) or "商品编码" in str(col):
                product_model_col = col
                break

        if not product_model_col:
            return {"error": "商品主数据中未找到型号列"}

        # 找到成本单价列
        cost_col = None
        for col in product_df.columns:
            if "成本" in str(col) and "单价" in str(col):
                cost_col = col
                break

        if not cost_col:
            return {"error": "商品主数据中未找到参考成本单价列"}

        # 找到品类列
        category_col = None
        for col in product_df.columns:
            if "品类" in str(col):
                category_col = col
                break

        # 合并盘点数据和商品主数据
        merged = count_df.merge(
            product_df[[product_model_col, cost_col] + ([category_col] if category_col else [])],
            left_on=count_model_col,
            right_on=product_model_col,
            how="left",
        )

        # 计算差异金额
        merged["参考成本单价"] = pd.to_numeric(merged[cost_col], errors="coerce")
        merged["差异金额"] = merged["差异数量"] * merged["参考成本单价"]

        # 缺失成本单价的 SKU：用同品类均值估算
        missing_cost = merged["参考成本单价"].isna()
        if missing_cost.any() and category_col:
            category_avg = merged.groupby(category_col)["参考成本单价"].transform("mean")
            merged.loc[missing_cost, "参考成本单价"] = category_avg[missing_cost]
            merged.loc[missing_cost, "成本来源"] = "估算"
        else:
            merged["成本来源"] = "实际"

        merged["差异金额"] = merged["差异金额"].round(2)

        # 差异类型分类
        def classify_variance(row):
            qty = row["差异数量"]
            amount = abs(row["差异金额"]) if pd.notna(row["差异金额"]) else 0
            if qty < 0 and (abs(qty) >= 5 or amount >= 2000):
                return "盘亏-严重"
            elif qty < 0:
                return "盘亏-轻微"
            elif qty > 0:
                return "盘盈"
            else:
                return "一致"

        merged["差异类型"] = merged.apply(classify_variance, axis=1)

        # 初盘纠错标记
        if "初盘数" in merged.columns:
            merged["初盘纠错"] = merged["初盘数"] != merged["复盘数"]

        self._variance_df = merged

        # 统计
        total_loss = merged[merged["差异数量"] < 0]["差异金额"].sum()
        total_gain = merged[merged["差异数量"] > 0]["差异金额"].sum()

        stats = {
            "total_skus": len(merged),
            "total_loss_amount": round(float(total_loss), 2),
            "total_gain_amount": round(float(total_gain), 2),
            "net_variance_amount": round(float(total_loss + total_gain), 2),
            "missing_cost_count": int(missing_cost.sum()),
            "estimated_cost_count": int((merged.get("成本来源", pd.Series()) == "估算").sum()),
        }

        self.memory.record_key_number("盘亏金额", stats["total_loss_amount"], "计算")
        self.memory.record_key_number("盘盈金额", stats["total_gain_amount"], "计算")
        self.memory.record_key_number("净差异金额", stats["net_variance_amount"], "计算")

        return stats

    # ============================================================
    # Step 7: 日志关联分析（三分类）
    # ============================================================
    def _step7_correlate_scan_log(self) -> dict:
        """将差异 SKU 与扫描日志关联，分三类。"""
        if self._variance_df is None or self._scan_log_window is None:
            return {
                "完全可解释": {"count": 0, "amount": 0},
                "部分可解释": {"count": 0, "amount": 0},
                "无日志关联": {"count": 0, "amount": 0},
            }

        variance_df = self._variance_df.copy()
        window_df = self._scan_log_window.copy()

        # 只分析有差异的 SKU
        diff_df = variance_df[variance_df["差异数量"] != 0].copy()

        # 计算每个 SKU 在窗口期的日志净变动量
        # 净变动 = Σ上架数量 - Σ拣货数量（移库不计入）
        model_col = None
        for col in window_df.columns:
            if "型号" in str(col) or "商品型号" in str(col):
                model_col = col
                break

        op_col = None
        for col in window_df.columns:
            if "操作类型" in str(col):
                op_col = col
                break

        qty_col = None
        for col in window_df.columns:
            if "数量" in str(col):
                qty_col = col
                break

        if not all([model_col, op_col, qty_col]):
            return {"error": "扫描日志缺少必要列"}

        # 计算净变动
        window_df[qty_col] = pd.to_numeric(window_df[qty_col], errors="coerce").fillna(0)
        shelf_df = window_df[window_df[op_col] == "上架"]
        pick_df = window_df[window_df[op_col] == "拣货"]

        shelf_by_model = shelf_df.groupby(model_col)[qty_col].sum()
        pick_by_model = pick_df.groupby(model_col)[qty_col].sum()

        net_change = shelf_by_model.sub(pick_by_model, fill_value=0)

        # 关联差异 SKU 和日志净变动
        correlation_results = []
        for _, row in diff_df.iterrows():
            sku_model = row["型号"]
            variance_qty = abs(row["差异数量"])
            log_change = abs(net_change.get(sku_model, 0))
            variance_amount = abs(row["差异金额"]) if pd.notna(row["差异金额"]) else 0

            if log_change >= variance_qty:
                category = "完全可解释"
            elif log_change > 0:
                category = "部分可解释"
            else:
                category = "无日志关联"

            correlation_results.append({
                "型号": sku_model,
                "差异数量": row["差异数量"],
                "差异金额": row["差异金额"],
                "日志净变动": net_change.get(sku_model, 0),
                "关联类别": category,
            })

        corr_df = pd.DataFrame(correlation_results)

        # 汇总
        summary = {}
        for cat in ["完全可解释", "部分可解释", "无日志关联"]:
            cat_df = corr_df[corr_df["关联类别"] == cat]
            summary[cat] = {
                "count": len(cat_df),
                "amount": round(float(cat_df["差异金额"].sum()), 2),
                "sku_list": cat_df["型号"].tolist()[:10],  # 前 10 个
            }

        self._correlation_df = corr_df
        return summary

    # ============================================================
    # Step 8: 库位状态校验
    # ============================================================
    def _step8_check_location_status(self) -> dict:
        """校验差异 SKU 所在库位的启用状态。"""
        if self._variance_df is None or self._location_master is None:
            return {"error": "缺少数据"}

        variance_df = self._variance_df.copy()
        location_df = self._location_master.copy()

        # 找到库位列
        location_code_col = None
        for col in location_df.columns:
            if "库位编码" in str(col) or "库位" in str(col):
                location_code_col = col
                break

        status_col = None
        for col in location_df.columns:
            if "状态" in str(col):
                status_col = col
                break

        if not all([location_code_col, status_col]):
            return {"error": "库位主数据缺少必要列"}

        # 从库存快照获取 SKU 的库位信息
        sku_locations = {}
        if self._baseline_df is not None:
            baseline = self._baseline_df.copy()
            loc_col = None
            model_col = None
            for col in baseline.columns:
                if "库位" in str(col) or "所在库位" in str(col):
                    loc_col = col
                if "型号" in str(col) or "商品编码" in str(col):
                    model_col = col

            if loc_col and model_col:
                for _, row in baseline.iterrows():
                    sku = row[model_col]
                    loc = row[loc_col]
                    if sku not in sku_locations:
                        sku_locations[sku] = set()
                    sku_locations[sku].add(loc)

        # 构建库位状态映射
        location_status_map = {}
        for _, row in location_df.iterrows():
            code = row[location_code_col]
            status = row[status_col]
            location_status_map[code] = status

        # 关联差异 SKU 和库位状态
        diff_df = variance_df[variance_df["差异数量"] != 0].copy()
        status_stats = {"启用": 0, "已停用": 0, "维修中": 0}
        abnormal_skus = []

        for _, row in diff_df.iterrows():
            sku = row["型号"]
            locations = sku_locations.get(sku, set())

            for loc in locations:
                status = location_status_map.get(loc, "未知")
                if status in status_stats:
                    status_stats[status] += 1

            # 检查是否有非正常库位
            abnormal_locs = [
                loc for loc in locations
                if location_status_map.get(loc) in ["已停用", "维修中"]
            ]
            if abnormal_locs:
                abnormal_skus.append({
                    "型号": sku,
                    "差异数量": row["差异数量"],
                    "差异金额": row["差异金额"],
                    "异常库位": list(abnormal_locs),
                    "库位状态": [location_status_map.get(loc, "未知") for loc in abnormal_locs],
                })

        return {
            "status_distribution": status_stats,
            "abnormal_location_skus": abnormal_skus,
            "abnormal_count": len(abnormal_skus),
        }

    # ============================================================
    # Step 9: 品类维度分析
    # ============================================================
    def _step9_analyze_by_category(self) -> dict:
        """按品类汇总差异并识别异常品类。"""
        if self._variance_df is None:
            return {"error": "缺少差异数据"}

        df = self._variance_df.copy()

        # 找到品类列
        category_col = None
        for col in df.columns:
            if "品类" in str(col):
                category_col = col
                break

        if not category_col:
            return {"error": "缺少品类列"}

        # 按品类汇总
        category_summary = df.groupby(category_col).agg(
            SKU数量=("型号", "count"),
            系统库存总计=("系统库存数", "sum"),
            复盘总计=("复盘数", "sum"),
            差异总计=("差异数量", "sum"),
            差异金额总计=("差异金额", "sum"),
        ).reset_index()

        category_summary["差异率"] = (
            category_summary["差异总计"].abs() / category_summary["系统库存总计"] * 100
        ).round(1)

        # 按差异率降序排列
        category_summary = category_summary.sort_values("差异率", ascending=False)

        # 识别异常品类
        anomaly_categories = []
        for _, row in category_summary.iterrows():
            if row["差异率"] > 10:
                anomaly_categories.append({
                    "品类": row[category_col],
                    "差异率": row["差异率"],
                    "严重程度": "严重异常",
                })
            elif row["差异率"] > 5:
                anomaly_categories.append({
                    "品类": row[category_col],
                    "差异率": row["差异率"],
                    "严重程度": "需关注",
                })

        return {
            "categories": category_summary.to_dict("records"),
            "anomaly_categories": anomaly_categories,
            "category_count": len(category_summary),
        }

    # ============================================================
    # Step 10: 生成交付物
    # ============================================================
    def _step10_generate_deliverables(self, output_dir: str) -> dict:
        """生成盘点差异明细表.xlsx 和盘点差异分析报告.md。"""
        results = {"xlsx_path": None, "md_path": None}

        # 生成 Excel
        if self._variance_df is not None:
            xlsx_path = Path(output_dir) / "盘点差异明细表.xlsx"
            self._generate_excel(xlsx_path)
            results["xlsx_path"] = str(xlsx_path)

        # 生成 Markdown 报告
        md_path = Path(output_dir) / "盘点差异分析报告.md"
        self._generate_markdown_report(md_path)
        results["md_path"] = str(md_path)

        results["generated"] = True
        return results

    def _generate_excel(self, path: Path):
        """生成盘点差异明细表 Excel（4 sheets）。"""
        df = self._variance_df.copy()

        with pd.ExcelWriter(path, engine="openpyxl") as writer:
            # Sheet 1: 差异汇总
            category_col = None
            for col in df.columns:
                if "品类" in str(col):
                    category_col = col
                    break

            if category_col:
                summary = df.groupby(category_col).agg(
                    SKU数量=("型号", "count"),
                    系统库存总计=("系统库存数", "sum"),
                    复盘总计=("复盘数", "sum"),
                    差异总计=("差异数量", "sum"),
                    差异金额总计=("差异金额", "sum"),
                ).reset_index()
                summary["差异率"] = (summary["差异总计"].abs() / summary["系统库存总计"] * 100).round(1)
                summary.to_excel(writer, sheet_name="差异汇总", index=False)

            # Sheet 2: 盘亏明细
            loss_df = df[df["差异数量"] < 0].copy()
            loss_df = loss_df.sort_values("差异金额", ascending=True)
            loss_cols = [c for c in ["型号", "品名", "品类", "系统库存数", "复盘数", "差异数量",
                                     "参考成本单价", "差异金额", "差异类型", "成本来源"] if c in loss_df.columns]
            loss_df[loss_cols].to_excel(writer, sheet_name="盘亏明细", index=False)

            # Sheet 3: 盘盈明细
            gain_df = df[df["差异数量"] > 0].copy()
            gain_df = gain_df.sort_values("差异金额", ascending=False)
            gain_df[loss_cols].to_excel(writer, sheet_name="盘盈明细", index=False)

            # Sheet 4: 初盘纠错记录
            if "初盘数" in df.columns:
                correction_df = df[df["初盘数"] != df["复盘数"]].copy()
                if len(correction_df) > 0:
                    correction_cols = [c for c in ["型号", "品名", "品类", "系统库存数", "初盘数", "复盘数"]
                                       if c in correction_df.columns]
                    correction_df[correction_cols].to_excel(writer, sheet_name="初盘纠错记录", index=False)

    def _generate_markdown_report(self, path: Path):
        """生成盘点差异分析报告 Markdown。"""
        lines = []
        lines.append("# 盘点差异分析报告\n")
        lines.append(f"> 报告生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M')}")
        lines.append(f"> 数据来源：inputs/ 目录业务资料\n")

        # 第一章：总体结论
        lines.append("## 一、总体结论\n")
        if self._variance_df is not None:
            df = self._variance_df
            system_total = int(df["系统库存数"].sum())
            recount_total = int(df["复盘数"].sum())
            net_var = int(df["差异数量"].sum())
            var_rate = round(abs(net_var) / system_total * 100, 1) if system_total > 0 else 0

            self.memory.record_key_number("总体差异率", var_rate, "报告")

            lines.append(f"系统库存总计 **{system_total}** 件，复盘总计 **{recount_total}** 件，")
            lines.append(f"净差异 **{net_var}** 件，总体差异率 **{var_rate}%**。\n")

            loss_count = int((df["差异数量"] < 0).sum())
            gain_count = int((df["差异数量"] > 0).sum())
            lines.append(f"存在差异的 SKU 共 **{loss_count + gain_count}** 个")
            lines.append(f"（盘亏 {loss_count} 个、盘盈 {gain_count} 个）。\n")

        # 第二章：基准选择
        lines.append("## 二、基准选择说明\n")
        baseline = self.analysis_result.get("Step 3: 选定比对基准", {})
        if "comparison" in baseline:
            lines.append("| 维度 | 对比结果 |")
            lines.append("|---|---|")
            for key, info in baseline["comparison"].items():
                selected = "✅" if info.get("是否选为基准") == "是" else ""
                lines.append(f"| {key} | {info['编码体系']}, {info['行数']} 行 {selected} |")
            lines.append("")

        # 第三章：扫描日志关联
        lines.append("## 三、扫描日志关联分析\n")
        log_corr = self.analysis_result.get("Step 7: 日志关联分析", {})
        if isinstance(log_corr, dict) and "error" not in log_corr:
            lines.append("| 关联类别 | SKU 数 | 差异金额 (元) |")
            lines.append("|---|---|---|")
            for cat in ["完全可解释", "部分可解释", "无日志关联"]:
                if cat in log_corr:
                    info = log_corr[cat]
                    lines.append(f"| {cat} | {info['count']} | {info['amount']:,.2f} |")
            lines.append("")

        # 第四章：品类分析
        lines.append("## 四、品类维度分析\n")
        cat_analysis = self.analysis_result.get("Step 9: 品类维度分析", {})
        if "categories" in cat_analysis:
            lines.append("| 品类 | SKU 数 | 系统库存 | 复盘数 | 差异 | 差异率 |")
            lines.append("|---|---|---|---|---|---|")
            for cat in cat_analysis["categories"]:
                name = cat.get("品类", cat.get(list(cat.keys())[0], ""))
                lines.append(
                    f"| {name} | {cat.get('SKU数量', 0)} | {cat.get('系统库存总计', 0)} | "
                    f"{cat.get('复盘总计', 0)} | {cat.get('差异总计', 0)} | {cat.get('差异率', 0)}% |"
                )
            lines.append("")

        # 附录：质量校验
        lines.append("## 附录：质量校验结果\n")
        checks = self.analysis_result.get("quality_checks", [])
        for i, check in enumerate(checks, 1):
            status = "✅" if check.get("passed") else "❌"
            lines.append(f"{status} **{i}. {check.get('name', '')}** ({check.get('importance', '')})")
            lines.append(f"   {check.get('detail', '')}\n")

        path.write_text("\n".join(lines), encoding="utf-8")

    def generate_executive_report(self, output_dir: str = None) -> str:
        """使用本地 LLM 生成管理层摘要报告（GPU 推理环节）。

        Args:
            output_dir: 报告输出目录，默认使用配置中的 output_dir

        Returns:
            生成的 Markdown 格式报告
        """
        if not self.analysis_result:
            return "请先运行分析工作流，然后再生成报告。"

        if output_dir is None:
            output_dir = self.config.get("data", {}).get("output_dir", "data/output")

        # 生成报告
        report = self.report_generator.generate_report(self.analysis_result)

        # 保存报告
        output_path = Path(output_dir) / "管理层摘要报告.md"
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(report, encoding="utf-8")

        return report

    def _save_analysis_result(self, output_dir: str):
        """保存分析结果到 JSON。"""
        save_path = Path(output_dir) / "analysis_result.json"

        # 转换不可序列化的对象
        def make_serializable(obj):
            if isinstance(obj, (pd.DataFrame, pd.Series)):
                return obj.to_dict("records") if len(obj) > 0 else []
            if isinstance(obj, pd.Timestamp):
                return str(obj)
            if isinstance(obj, datetime):
                return obj.isoformat()
            if isinstance(obj, np.integer):
                return int(obj)
            if isinstance(obj, np.floating):
                return float(obj)
            if isinstance(obj, np.bool_):
                return bool(obj)
            if isinstance(obj, set):
                return list(obj)
            return obj

        serializable = {}
        for k, v in self.analysis_result.items():
            try:
                json.dumps(v, default=make_serializable, ensure_ascii=False)
                serializable[k] = v
            except (TypeError, ValueError):
                serializable[k] = str(v)

        with open(save_path, "w", encoding="utf-8") as f:
            json.dump(serializable, f, default=make_serializable, ensure_ascii=False, indent=2)


def main():
    config = load_config()
    agent = InventoryDocAgent(config)

    if create_ui is not None:
        ui = create_ui(agent)
        ui.launch(
            server_name=config["ui"]["host"],
            server_port=config["ui"]["port"],
            share=config["ui"]["share"],
        )
    else:
        print("Gradio 未安装，仅运行工作流...")
        input_dir = config.get("data", {}).get("input_dir", "data/input")
        output_dir = config.get("data", {}).get("output_dir", "data/output")
        result = agent.run_workflow(input_dir, output_dir)
        print(f"工作流完成，结果保存到 {output_dir}/analysis_result.json")


if __name__ == "__main__":
    main()
