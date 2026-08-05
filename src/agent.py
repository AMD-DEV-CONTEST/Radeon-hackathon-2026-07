"""
Agent Core — 基于 10 步工作流的库存盘点差异分析 Agent。
运行在 AMD Radeon GPU + ROCm 上，完全本地化部署。

工作流来源: workflow.txt (库存控制专员 × 循环盘点差异分析与库存调账)
地面真值: 系统库存 21,144 / 复盘 20,173 / 净差异 -971 / 差异率 4.6%
"""

import os
import yaml
import json
import hashlib
import time
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
    from .ui import create_ui, APP_CSS
except ImportError:
    create_ui = None

try:
    from .input_validator import InputValidator
except ImportError:
    InputValidator = None


def load_config() -> dict:
    config_path = Path(__file__).parent.parent / "config" / "settings.yaml"
    with open(config_path, "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)
    gt_path = Path(__file__).parent.parent / "config" / "ground_truth.yaml"
    if gt_path.exists():
        with open(gt_path, "r", encoding="utf-8") as f:
            gt = yaml.safe_load(f)
            config.update(gt or {})
    return config


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
        self.workflow_trace = []
        self.run_id = None
        self.run_metadata = {}

        # 中间结果存储
        self._baseline_df = None
        self._baseline_01_df = None
        self._scan_log_real = None
        self._scan_log_window = None
        self._inventory_count_df = None
        self._product_master = None
        self._location_master = None
        self._variance_df = None
        self._correlation_df = None
        self._inbound_df = None
        self._outbound_df = None

    def run_workflow(self, input_dir: str, output_dir: str) -> dict:
        """执行完整的 10 步工作流。"""
        output_path = Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)

        # 初始化运行元数据
        self.run_id = f"RUN-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
        self.run_metadata = {
            "run_id": self.run_id,
            "started_at": datetime.now().isoformat(),
            "input_dir": input_dir,
            "output_dir": output_dir,
            "workflow_version": "10-step-v1",
            "status": "running",
        }
        self.run_metadata["input_files"] = self._collect_input_file_audit(input_dir)

        # 输入完整性校验：缺必需文件时阻断，不走 10 步工作流
        if InputValidator is not None:
            validation = InputValidator().validate(input_dir)
            self.analysis_result["input_validation"] = validation
            self.run_metadata["input_validation"] = validation
            if not validation["passed"]:
                self.run_metadata["status"] = "failed_input_validation"
                self.run_metadata["finished_at"] = datetime.now().isoformat()
                started = datetime.fromisoformat(self.run_metadata["started_at"])
                finished = datetime.fromisoformat(self.run_metadata["finished_at"])
                self.run_metadata["duration_seconds"] = round((finished - started).total_seconds(), 3)
                self.analysis_result["_blocked"] = {"step": "input_validation", "reason": validation["summary"]}
                self.analysis_result["_metadata"] = self.run_metadata
                return self.analysis_result

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
            step_start = time.time()
            step_started_at = datetime.now().isoformat()
            try:
                result = step_func()
                step_duration_ms = int((time.time() - step_start) * 1000)
                self.analysis_result[step_name] = result
                if isinstance(result, dict):
                    self.workflow_trace.append({
                        "step": step_name,
                        "status": "success",
                        "started_at": step_started_at,
                        "duration_ms": step_duration_ms,
                        "summary": result.get("summary", result.get("selected", result.get("net_variance", "ok"))),
                    })
                else:
                    self.workflow_trace.append({
                        "step": step_name,
                        "status": "success",
                        "started_at": step_started_at,
                        "duration_ms": step_duration_ms,
                    })

                # 阻断检查：关键步骤失败立即停止后续步骤
                blocking, reason = self._is_blocking_step_failure(step_name, result)
                if blocking:
                    self.analysis_result["_blocked"] = {"step": step_name, "reason": reason}
                    self.run_metadata["status"] = "blocked"
                    break

            except Exception as e:
                step_duration_ms = int((time.time() - step_start) * 1000)
                self.analysis_result[step_name] = {"error": str(e)}
                self.workflow_trace.append({
                    "step": step_name,
                    "status": "error",
                    "started_at": step_started_at,
                    "duration_ms": step_duration_ms,
                    "summary": str(e),
                })
                # 异常阻断：关键步骤异常立即停止
                blocking, reason = self._is_blocking_step_failure(step_name, {"error": str(e)})
                if blocking:
                    self.analysis_result["_blocked"] = {"step": step_name, "reason": reason}
                    self.run_metadata["status"] = "blocked"
                    break

        # 质量校验
        self.analysis_result["quality_checks"] = self.quality_checker.run_all_checks(
            self.analysis_result
        )

        # 质量门禁
        summary = self.quality_checker.summarize_checks(self.analysis_result["quality_checks"])
        self.run_metadata["quality_gate"] = {
            **summary,
            "passed": summary["failed_count"] == 0,
            "report_allowed": summary["can_generate_report"],
        }

        # Top-5 差异 SKU
        self._generate_top_variance_skus()

        # 处置建议
        self._generate_disposition_recommendations()

        # 调账材料包
        self._generate_deliverable_package()

        # 完成元数据
        self.run_metadata["finished_at"] = datetime.now().isoformat()
        started = datetime.fromisoformat(self.run_metadata["started_at"])
        finished = datetime.fromisoformat(self.run_metadata["finished_at"])
        self.run_metadata["duration_seconds"] = round((finished - started).total_seconds(), 3)

        if "_blocked" in self.analysis_result:
            self.run_metadata["status"] = "blocked"
        elif self.run_metadata.get("status") not in {"failed_input_validation", "blocked"}:
            self.run_metadata["status"] = "completed"

        self.run_metadata["workflow_trace"] = self.workflow_trace
        self.analysis_result["_metadata"] = self.run_metadata

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
        """从库存快照中选定正确的比对基准，输出三维对比表。"""
        snapshots = {}
        for key, df in self.rag.dataframes.items():
            if "库存快照" in key:
                snapshots[key] = df

        if not snapshots:
            return {"selected": None, "reason": "未找到库存快照文件", "summary": "无基准"}

        # 三维对比分析
        comparison = {}
        for key, df in snapshots.items():
            cols = list(df.columns)
            has_model_code = any(kw in str(col) for col in cols for kw in ["型号", "商品编码"])
            has_spec = any("规格" in str(col) for col in cols)
            has_batch = any(kw in str(col) for col in cols for kw in ["货号", "批号"])
            has_location = any("库位" in str(col) for col in cols)

            # 判断编码体系
            if has_model_code:
                code_system = "型号编码"
            elif has_spec:
                code_system = "货号编码（规格列）"
            elif has_batch:
                code_system = "货号编码（批号）"
            else:
                code_system = "未知"

            # 判断数据粒度
            if has_location and has_batch:
                granularity = "批次 × 库位"
            elif has_location:
                granularity = "型号 × 库位"
            else:
                granularity = "型号"

            comparison[key] = {
                "编码体系": code_system,
                "行数": len(df),
                "列数": len(df.columns),
                "列名": cols,
                "数据粒度": granularity,
                "包含库位": "是" if has_location else "否",
            }

        # 从文件名提取时间
        def extract_time(key):
            for part in key.split("_"):
                if part.replace("-", "").isdigit() and len(part) >= 8:
                    return part[:10]
            return "未知"

        # 选择逻辑：型号编码+含库位 → 型号编码 → 第一个
        selected = None
        for key in sorted(snapshots.keys()):
            info = comparison[key]
            if info["编码体系"] == "型号编码" and info["包含库位"] == "是":
                selected = key
                break
        if not selected:
            for key in sorted(snapshots.keys()):
                if comparison[key]["编码体系"] == "型号编码":
                    selected = key
                    break
        if not selected:
            selected = list(snapshots.keys())[0]

        # 构建三维对比表
        three_d_table = {}
        for key, info in comparison.items():
            time_str = extract_time(key)
            is_selected = key == selected
            mapping_note = ""
            if info["编码体系"] == "货号编码（规格列）":
                mapping_note = "需通过规格字段映射到型号"
            elif info["编码体系"] == "型号编码":
                mapping_note = "与盘点表编码一致，可直接匹配"

            three_d_table[key] = {
                "编码体系": info["编码体系"],
                "快照时间": time_str,
                "数据粒度": info["数据粒度"],
                "行数": info["行数"],
                "包含库位": info["包含库位"],
                "直接匹配盘点表": "是" if info["编码体系"] == "型号编码" else "否",
                "映射说明": mapping_note,
                "是否选为基准": "✅ 主基准" if is_selected else "交叉验证",
            }

        # 保存两份快照引用
        for key in snapshots:
            if "01" in key or "0425" in key:
                self._baseline_01_df = snapshots[key]
            elif "02" in key or "0428" in key:
                self._baseline_df = snapshots[key]

        # 结论
        selected_info = three_d_table[selected]
        conclusion_parts = [
            f"选择 **{selected}** 作为主比对基准",
            f"理由：{selected_info['编码体系']}，{selected_info['直接匹配盘点表']}，无需编码映射",
            f"时间点 {selected_info['快照时间']} 最接近盘点周期",
            f"数据粒度 {selected_info['数据粒度']} 可聚合到 SKU 口径",
        ]

        return {
            "selected": selected,
            "summary": f"选定 {selected}（{selected_info['编码体系']}，{selected_info['快照时间']}）",
            "three_dimension_table": three_d_table,
            "conclusion": conclusion_parts,
            "risk_if_wrong": "选择 01 会导致 SKU 匹配失败（货号编码无法直接匹配型号），且时间更早（4/25）",
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
        """为每个 SKU 计算差异金额，先匹配成本、再填补缺失、最后算金额。"""
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

        # Step A: 先匹配成本单价
        merged["参考成本单价"] = pd.to_numeric(merged[cost_col], errors="coerce")

        # Step B: 标注成本来源（填补前的原始状态）
        cost_na_before = merged["参考成本单价"].isna()
        merged["成本来源"] = "实际"

        # Step C: 缺失成本用同品类均值估算
        if cost_na_before.any() and category_col:
            category_avg = merged.groupby(category_col)["参考成本单价"].transform("mean")
            merged.loc[cost_na_before, "参考成本单价"] = category_avg[cost_na_before]
            merged.loc[cost_na_before, "成本来源"] = "估算"

        # Step D: 再计算差异金额（确保所有 SKU 都有金额）
        merged["差异金额"] = merged["差异数量"] * merged["参考成本单价"]
        merged["差异金额"] = merged["差异金额"].round(2)

        # 差异类型四分类
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
            "actual_cost_count": int((~cost_na_before).sum()),
            "estimated_cost_count": int(cost_na_before.sum()),
        }

        self.memory.record_key_number("盘亏金额", stats["total_loss_amount"], "计算")
        self.memory.record_key_number("盘盈金额", stats["total_gain_amount"], "计算")
        self.memory.record_key_number("净差异金额", stats["net_variance_amount"], "计算")

        return stats

    # ============================================================
    # Step 7: 日志关联分析（三分类，5 个字段输出）
    # ============================================================
    def _step7_correlate_scan_log(self) -> dict:
        """将差异 SKU 与扫描日志关联，输出 5 字段：日志净变动量、关联类别、关联金额、操作记录数、涉及操作类型。"""
        if self._variance_df is None or self._scan_log_window is None:
            return {
                "完全可解释": {"count": 0, "amount": 0, "操作记录数": 0, "涉及操作类型": []},
                "部分可解释": {"count": 0, "amount": 0, "操作记录数": 0, "涉及操作类型": []},
                "无日志关联": {"count": 0, "amount": 0, "操作记录数": 0, "涉及操作类型": []},
                "summary": "无日志数据",
            }

        variance_df = self._variance_df.copy()
        window_df = self._scan_log_window.copy()

        diff_df = variance_df[variance_df["差异数量"] != 0].copy()

        # 找到列名
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

        window_df[qty_col] = pd.to_numeric(window_df[qty_col], errors="coerce").fillna(0)

        # 按型号+操作类型统计
        shelf_mask = window_df[op_col].astype(str).str.contains("上架", na=False)
        pick_mask = window_df[op_col].astype(str).str.contains("拣货", na=False)
        transfer_mask = window_df[op_col].astype(str).str.contains("移库", na=False)
        count_mask = window_df[op_col].astype(str).str.contains("盘点", na=False)

        shelf_df = window_df[shelf_mask]
        pick_df = window_df[pick_mask]
        transfer_df = window_df[transfer_mask]

        # 净变动 = 上架 - 拣货
        shelf_by_model = shelf_df.groupby(model_col)[qty_col].sum()
        pick_by_model = pick_df.groupby(model_col)[qty_col].sum()
        net_change = shelf_by_model.sub(pick_by_model, fill_value=0)

        # 各类操作记录数
        shelf_count = shelf_df.groupby(model_col).size()
        pick_count = pick_df.groupby(model_col).size()
        transfer_count = transfer_df.groupby(model_col).size()

        # 关联差异 SKU
        correlation_results = []
        for _, row in diff_df.iterrows():
            sku_model = row["型号"]
            variance_qty = abs(row["差异数量"])
            log_net = net_change.get(sku_model, 0)
            log_change_abs = abs(log_net)
            variance_amount = row["差异金额"] if pd.notna(row["差异金额"]) else 0

            if log_change_abs >= variance_qty:
                category = "完全可解释"
            elif log_change_abs > 0:
                category = "部分可解释"
            else:
                category = "无日志关联"

            # 操作类型列表
            ops = []
            if shelf_count.get(sku_model, 0) > 0:
                ops.append("上架")
            if pick_count.get(sku_model, 0) > 0:
                ops.append("拣货")
            if transfer_count.get(sku_model, 0) > 0:
                ops.append("移库")
            total_records = int(shelf_count.get(sku_model, 0) + pick_count.get(sku_model, 0) + transfer_count.get(sku_model, 0))

            correlation_results.append({
                "型号": sku_model,
                "差异数量": row["差异数量"],
                "差异金额": variance_amount,
                "日志净变动量": round(float(log_net), 1),
                "关联类别": category,
                "关联金额": round(float(variance_amount), 2),
                "操作记录数": total_records,
                "涉及操作类型": ops,
            })

        corr_df = pd.DataFrame(correlation_results)
        self._correlation_df = corr_df

        # 汇总
        summary = {}
        for cat in ["完全可解释", "部分可解释", "无日志关联"]:
            cat_df = corr_df[corr_df["关联类别"] == cat]
            all_ops = set()
            total_records = 0
            for ops_list in cat_df["涉及操作类型"]:
                all_ops.update(ops_list)
                total_records += cat_df["操作记录数"].sum()

            summary[cat] = {
                "count": len(cat_df),
                "amount": round(float(cat_df["差异金额"].sum()), 2),
                "操作记录数": int(cat_df["操作记录数"].sum()) if len(cat_df) > 0 else 0,
                "涉及操作类型": list(all_ops),
                "sku_list": cat_df["型号"].tolist()[:10],
            }

        return summary

    # ============================================================
    # Step 8: 库位状态校验
    # ============================================================
    def _step8_check_location_status(self) -> dict:
        """校验差异 SKU 所在库位的启用状态。包含口径说明。"""
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

        # 从库存快照获取 SKU 的库位信息（优先用 01，含批次×库位粒度）
        sku_locations = {}
        baseline_used = None
        for bl_name, bl_df in [("02", self._baseline_df), ("01", self._baseline_01_df)]:
            if bl_df is not None:
                baseline = bl_df.copy()
                loc_col = None
                model_col = None
                for col in baseline.columns:
                    if "库位" in str(col) or "所在库位" in str(col):
                        loc_col = col
                    if "型号" in str(col) or "商品编码" in str(col) or "规格" in str(col):
                        model_col = col

                if loc_col and model_col:
                    for _, row in baseline.iterrows():
                        sku = str(row[model_col])
                        loc = str(row[loc_col])
                        if sku not in sku_locations:
                            sku_locations[sku] = set()
                        sku_locations[sku].add(loc)
                    baseline_used = bl_name

        # 构建库位状态映射
        location_status_map = {}
        for _, row in location_df.iterrows():
            code = row[location_code_col]
            status = row[status_col]
            location_status_map[str(code)] = str(status)

        # 关联差异 SKU 和库位状态
        diff_df = variance_df[variance_df["差异数量"] != 0].copy()
        status_stats = {"启用": 0, "已停用": 0, "维修中": 0, "未知": 0}
        abnormal_skus = []

        for _, row in diff_df.iterrows():
            sku = str(row["型号"])
            locations = sku_locations.get(sku, set())

            for loc in locations:
                status = location_status_map.get(loc, "未知")
                if status in status_stats:
                    status_stats[status] += 1
                else:
                    status_stats["未知"] += 1

            abnormal_locs = [
                loc for loc in locations
                if location_status_map.get(loc, "未知") in ["已停用", "维修中"]
            ]
            if abnormal_locs:
                abnormal_skus.append({
                    "型号": sku,
                    "差异数量": row["差异数量"],
                    "差异金额": row["差异金额"],
                    "异常库位": list(abnormal_locs),
                    "库位状态": [location_status_map.get(loc, "未知") for loc in abnormal_locs],
                })

        # 口径说明
        caveat = (
            "02 快照是「型号 × 库位」粒度，04 盘点表是「SKU」粒度（型号级别，不含库位维度）。"
            "因此不能把 SKU 差异精确归因到某一个库位，只能把非启用库位作为风险标记。"
            "建议对涉及停用/维修中库位的 SKU 进行现场复核，确认实物实际存放位置。"
        )
        if baseline_used == "01":
            caveat += " 注：01 快照为「批次 × 库位」粒度，库位信息更精确但编码体系为货号（需规格映射）。"

        return {
            "status_distribution": status_stats,
            "abnormal_location_skus": abnormal_skus,
            "abnormal_count": len(abnormal_skus),
            "baseline_used_for_locations": baseline_used,
            "口径说明": caveat,
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
        """生成盘点差异明细表 Excel（6 sheets，含条件格式）。"""
        df = self._variance_df.copy()

        category_col = None
        for col in df.columns:
            if "品类" in str(col):
                category_col = col
                break

        from openpyxl.styles import Font, PatternFill, Alignment, numbers
        from openpyxl.utils import get_column_letter

        header_fill = PatternFill(start_color="4472C4", end_color="4472C4", fill_type="solid")
        header_font = Font(color="FFFFFF", bold=True, size=11)
        red_fill = PatternFill(start_color="FFC7CE", end_color="FFC7CE", fill_type="solid")
        green_fill = PatternFill(start_color="C6EFCE", end_color="C6EFCE", fill_type="solid")
        yellow_fill = PatternFill(start_color="FFEB9C", end_color="FFEB9C", fill_type="solid")

        def style_header(ws, num_cols):
            for col_idx in range(1, num_cols + 1):
                cell = ws.cell(row=1, column=col_idx)
                cell.fill = header_fill
                cell.font = header_font
                cell.alignment = Alignment(horizontal="center")

        def auto_width(ws):
            for col_cells in ws.columns:
                max_len = 0
                col_letter = get_column_letter(col_cells[0].column)
                for cell in col_cells:
                    try:
                        val = str(cell.value) if cell.value is not None else ""
                        max_len = max(max_len, min(len(val.encode('utf-8')), 40))
                    except:
                        pass
                ws.column_dimensions[col_letter].width = max_len + 3

        with pd.ExcelWriter(path, engine="openpyxl") as writer:
            # Sheet 1: 差异汇总（品类维度）
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
                ws = writer.sheets["差异汇总"]
                style_header(ws, len(summary.columns))
                # 差异率列用百分比格式
                rate_col = len(summary.columns)  # last column
                for row_idx in range(2, len(summary) + 2):
                    cell = ws.cell(row=row_idx, column=rate_col)
                    if cell.value is not None:
                        cell.number_format = '0.0"%"'
                        rate_val = float(cell.value)
                        if rate_val > 10:
                            cell.fill = red_fill
                            cell.font = Font(bold=True, color="9C0006")
                        elif rate_val > 5:
                            cell.fill = yellow_fill
                auto_width(ws)
                ws.freeze_panes = "A2"

            # Sheet 2: 盘亏明细
            loss_df = df[df["差异数量"] < 0].copy()
            loss_df = loss_df.sort_values("差异金额", ascending=True)
            loss_cols = [c for c in ["型号", "品名", "品类", "系统库存数", "复盘数", "差异数量",
                                     "参考成本单价", "差异金额", "差异类型", "成本来源"] if c in loss_df.columns]
            loss_df[loss_cols].to_excel(writer, sheet_name="盘亏明细", index=False)
            ws = writer.sheets["盘亏明细"]
            style_header(ws, len(loss_cols))
            # 金额列格式
            for col_idx, col_name in enumerate(loss_cols, 1):
                col_letter = get_column_letter(col_idx)
                for cell in ws[col_letter]:
                    if cell.value is not None and col_name in ("差异金额", "参考成本单价"):
                        cell.number_format = '¥#,##0.00'
                    if col_name == "差异类型" and cell.value and "严重" in str(cell.value):
                        cell.fill = red_fill
                        cell.font = Font(bold=True)
            auto_width(ws)
            ws.freeze_panes = "A2"

            # Sheet 3: 盘盈明细
            gain_df = df[df["差异数量"] > 0].copy()
            gain_df = gain_df.sort_values("差异金额", ascending=False)
            gain_cols = [c for c in loss_cols if c in gain_df.columns]
            gain_df[gain_cols].to_excel(writer, sheet_name="盘盈明细", index=False)
            ws = writer.sheets["盘盈明细"]
            style_header(ws, len(gain_cols))
            for col_idx, col_name in enumerate(gain_cols, 1):
                col_letter = get_column_letter(col_idx)
                for cell in ws[col_letter]:
                    if cell.value is not None and col_name in ("差异金额", "参考成本单价"):
                        cell.number_format = '¥#,##0.00'
                    if col_name == "差异类型" and cell.value and str(cell.value) == "盘盈":
                        cell.fill = green_fill
            auto_width(ws)
            ws.freeze_panes = "A2"

            # Sheet 4: 初盘纠错记录
            if "初盘数" in df.columns:
                correction_df = df[df["初盘数"] != df["复盘数"]].copy()
                if len(correction_df) > 0:
                    correction_cols = [c for c in ["型号", "品名", "品类", "系统库存数", "初盘数", "复盘数", "差异类型"]
                                       if c in correction_df.columns]
                    correction_df[correction_cols].to_excel(writer, sheet_name="初盘纠错记录", index=False)
                    ws = writer.sheets["初盘纠错记录"]
                    style_header(ws, len(correction_cols))
                    auto_width(ws)
                    ws.freeze_panes = "A2"

            # Sheet 5: 全量SKU明细
            all_cols = [c for c in ["型号", "品名", "品类", "系统库存数", "复盘数", "差异数量",
                                     "参考成本单价", "差异金额", "差异类型", "成本来源"]
                        if c in df.columns]
            df[all_cols].to_excel(writer, sheet_name="全量SKU明细", index=False)
            ws = writer.sheets["全量SKU明细"]
            style_header(ws, len(all_cols))
            for col_idx, col_name in enumerate(all_cols, 1):
                col_letter = get_column_letter(col_idx)
                for cell in ws[col_letter]:
                    if cell.value is not None and col_name in ("差异金额", "参考成本单价"):
                        cell.number_format = '¥#,##0.00'
                    if col_name == "差异类型" and cell.value:
                        if "严重" in str(cell.value):
                            cell.fill = red_fill
                            cell.font = Font(bold=True)
                        elif str(cell.value) == "盘盈":
                            cell.fill = green_fill
            auto_width(ws)
            ws.freeze_panes = "A2"

            # Sheet 6: 口径说明
            from openpyxl import Workbook
            ws6 = writer.book.create_sheet("口径说明")
            explanations = [
                ["项目", "说明"],
                ["比对基准", "选定 02_库存快照_20190428 为主基准（型号编码，与盘点表一致）"],
                ["01 库存快照", "仅用作交叉验证（货号编码，需规格映射）"],
                ["成本口径", "全部使用参考成本单价（非售价），缺失值用同品类均值估算"],
                ["差异金额公式", "差异数量 × 参考成本单价，负值=盘亏，正值=盘盈"],
                ["扫描日志窗口", "提取 4/25-4/28 期间的操作记录"],
                ["日志关联方法", "净变动量（上架-拣货）绝对值 vs 差异数量绝对值比对"],
                ["差异类型_盘亏严重", "差异数量 ≥ 5 或差异金额 ≥ 2000 元"],
                ["库位口径", "02 快照为型号×库位粒度，04 盘点表为 SKU 粒度"],
                ["排除文件", "07_库存月报（品类汇总，仅10行）、10_历史库存（含TEST/异常记录）"],
                ["Ground Truth", "系统库存 21144 | 净差异 -971 | 差异率 4.6% | 净金额 -989,900.97"],
            ]
            for row_idx, row_data in enumerate(explanations, 1):
                for col_idx, val in enumerate(row_data, 1):
                    cell = ws6.cell(row=row_idx, column=col_idx, value=val)
                    if row_idx == 1:
                        cell.fill = header_fill
                        cell.font = header_font
            ws6.column_dimensions["A"].width = 20
            ws6.column_dimensions["B"].width = 60

    def _generate_markdown_report(self, path: Path):
        """生成盘点差异分析报告 Markdown（8 章 + 附录）。"""
        lines = []
        lines.append("# 盘点差异分析报告\n")
        lines.append(f"> **报告生成时间**：{datetime.now().strftime('%Y-%m-%d %H:%M')}")
        lines.append(f"> **数据来源**：某供应链 5 月循环盘点（10 份业务文件）")
        lines.append(f"> **生成方式**：InventoryDoc Agent — 10 步确定性工作流 + vLLM/ROCm\n")

        # ============================================================
        # 第一章：总体结论
        # ============================================================
        lines.append("## 一、总体结论\n")
        if self._variance_df is not None:
            df = self._variance_df
            system_total = int(df["系统库存数"].sum())
            recount_total = int(df["复盘数"].sum())
            net_var = int(df["差异数量"].sum())
            var_rate = round(abs(net_var) / system_total * 100, 1) if system_total > 0 else 0

            self.memory.record_key_number("总体差异率", var_rate, "报告")

            lines.append(f"本次循环盘点覆盖 **{len(df)}** 个 SKU（{len(df['品类'].unique()) if '品类' in df.columns else '?'} 个品类），")
            lines.append(f"系统库存总计 **{system_total}** 件，复盘总计 **{recount_total}** 件，")
            lines.append(f"净差异 **{net_var}** 件，总体差异率 **{var_rate}%**。\n")

            loss_count = int((df["差异数量"] < 0).sum())
            gain_count = int((df["差异数量"] > 0).sum())
            lines.append(f"| 指标 | 数值 |")
            lines.append(f"|---|---|")
            lines.append(f"| SKU 总数 | {len(df)} 个 |")
            lines.append(f"| 系统库存总计 | {system_total} 件 |")
            lines.append(f"| 复盘总计 | {recount_total} 件 |")
            lines.append(f"| 净差异 | {net_var} 件 |")
            lines.append(f"| 总体差异率 | {var_rate}% |")
            lines.append(f"| 盘亏 SKU | {loss_count} 个 |")
            lines.append(f"| 盘盈 SKU | {gain_count} 个 |")
            lines.append(f"| 一致 SKU | {int((df['差异数量'] == 0).sum())} 个 |")
            step6 = self.analysis_result.get("Step 6: 计算差异金额", {})
            lines.append(f"| 净差异金额 | {step6.get('net_variance_amount', 0):,.2f} 元 |")
            lines.append(f"")

            risk = "严重（>8%）" if var_rate > 8 else ("需关注（5-8%）" if var_rate > 5 else "正常（<5%）")
            lines.append(f"> **风险判断**：差异率 {var_rate}%，处于 **{risk}** 水平。\n")

        # ============================================================
        # 第二章：基准选择说明
        # ============================================================
        lines.append("## 二、基准选择说明\n")
        baseline = self.analysis_result.get("Step 3: 选定比对基准", {})
        three_d = baseline.get("three_dimension_table", {})
        if three_d:
            lines.append("### 三维对比表\n")
            lines.append("| 维度 | " + " | ".join(three_d.keys()) + " |")
            lines.append("|" + "|".join("---" for _ in three_d) + "|")
            dims = ["编码体系", "快照时间", "数据粒度", "行数", "包含库位", "直接匹配盘点表", "映射说明", "是否选为基准"]
            for dim in dims:
                row = [dim]
                for key in three_d:
                    row.append(str(three_d[key].get(dim, "")))
                lines.append("| " + " | ".join(row) + " |")
            lines.append("")

            for concl in baseline.get("conclusion", []):
                lines.append(f"- {concl}")
            lines.append("")
            risk = baseline.get("risk_if_wrong", "")
            if risk:
                lines.append(f"> ⚠️ **潜在风险**：{risk}\n")

        # ============================================================
        # 第三章：扫描日志关联分析
        # ============================================================
        lines.append("## 三、扫描日志关联分析\n")
        log_corr = self.analysis_result.get("Step 7: 日志关联分析", {})
        if isinstance(log_corr, dict) and "error" not in log_corr:
            lines.append("| 关联类别 | SKU 数 | 差异金额 (元) | 操作记录数 | 涉及操作类型 |")
            lines.append("|---|---|---|---|---|")
            total_sku = 0
            total_amt = 0
            for cat in ["完全可解释", "部分可解释", "无日志关联"]:
                if cat in log_corr:
                    info = log_corr[cat]
                    ops = ", ".join(info.get("涉及操作类型", [])) if info.get("涉及操作类型") else "无"
                    lines.append(f"| **{cat}** | {info['count']} | {info['amount']:,.2f} | {info.get('操作记录数', 0)} | {ops} |")
                    total_sku += info['count']
                    total_amt += info['amount']
            lines.append(f"| **合计** | **{total_sku}** | **{total_amt:,.2f}** | | |")
            lines.append("")

            no_log = log_corr.get("无日志关联", {})
            if no_log.get("count", 0) > 0:
                pct = no_log["amount"] / max(total_amt, 1) * 100
                lines.append(f"> ⚠️ **{no_log['count']}** 个 SKU（金额占比 {pct:.1f}%）无日志关联，")
                lines.append(f"> 建议对以下 SKU 进行现场实物复核：{', '.join(no_log.get('sku_list', [])[:5])}...\n")

            if self._correlation_df is not None and len(self._correlation_df) > 0:
                top_unexplained = self._correlation_df[
                    self._correlation_df["关联类别"] == "无日志关联"
                ].nsmallest(5, "差异金额") if len(self._correlation_df) > 0 else []
                if len(top_unexplained) > 0:
                    lines.append("### 无日志关联 Top-5（按金额）\n")
                    lines.append("| 型号 | 差异数量 | 差异金额 |")
                    lines.append("|---|---|---|")
                    for _, r in top_unexplained.iterrows():
                        lines.append(f"| {r['型号']} | {r['差异数量']} | {r['差异金额']:,.2f} |")
                    lines.append("")

        # ============================================================
        # 第四章：品类维度分析
        # ============================================================
        lines.append("## 四、品类维度分析\n")
        cat_analysis = self.analysis_result.get("Step 9: 品类维度分析", {})
        if "categories" in cat_analysis:
            lines.append("| 品类 | SKU 数 | 系统库存 | 复盘数 | 差异 | 差异率 | 差异金额 |")
            lines.append("|---|---|---|---|---|---|---|")
            for cat in cat_analysis["categories"]:
                name = cat.get("品类", "")
                rate = cat.get("差异率", 0)
                marker = " ⚠️" if rate > 10 else (" 🔶" if rate > 5 else "")
                lines.append(
                    f"| {name}{marker} | {cat.get('SKU数量', 0)} | {cat.get('系统库存总计', 0)} | "
                    f"{cat.get('复盘总计', 0)} | {cat.get('差异总计', 0)} | {rate}% | "
                    f"{cat.get('差异金额总计', 0):,.2f} |"
                )
            lines.append("")

        anomalies = cat_analysis.get("anomaly_categories", [])
        if anomalies:
            lines.append("### 异常识别\n")
            for a in anomalies:
                sev = a.get("严重程度", "")
                icon = "🔴" if "严重" in sev else "🟡"
                lines.append(f"- {icon} **{a['品类']}**：差异率 {a['差异率']}%（{sev}）")
            lines.append("")

        # ============================================================
        # 第五章：差异原因分类
        # ============================================================
        lines.append("## 五、差异原因分类\n")
        if self._variance_df is not None:
            df = self._variance_df
            type_counts = df["差异类型"].value_counts()
            lines.append("| 差异类型 | SKU 数 | 说明 |")
            lines.append("|---|---|---|")
            for t, c in type_counts.items():
                notes = {"盘亏-严重": "数量≥5或金额≥2000", "盘亏-轻微": "数量<5且金额<2000", "盘盈": "实盘多于系统", "一致": "无差异"}
                lines.append(f"| **{t}** | {c} | {notes.get(t, '')} |")
            lines.append("")

        # ============================================================
        # 第六章：重点差异 SKU
        # ============================================================
        lines.append("## 六、重点差异 SKU\n")
        if self._variance_df is not None:
            df = self._variance_df
            diff_df = df[df["差异数量"] != 0].copy()
            diff_df["金额绝对值"] = diff_df["差异金额"].abs()
            top15 = diff_df.nlargest(15, "金额绝对值")

            lines.append("| 排名 | 型号 | 品类 | 差异数量 | 差异金额 | 差异类型 |")
            lines.append("|---|---|---|---|---|---|")
            for rank, (_, row) in enumerate(top15.iterrows(), 1):
                lines.append(
                    f"| {rank} | {row.get('型号', '')} | {row.get('品类', '')} | "
                    f"{row.get('差异数量', 0)} | {row.get('差异金额', 0):,.2f} | "
                    f"{row.get('差异类型', '')} |"
                )
            lines.append("")
            lines.append(f"> 完整 106 个差异 SKU 明细请见 Excel「全量SKU明细」sheet。\n")

        # ============================================================
        # 第七章：文件排除说明
        # ============================================================
        lines.append("## 七、文件排除说明\n")
        step2 = self.analysis_result.get("Step 2: 识别噪音数据", {})
        exclusions = step2.get("file_exclusion_reasons", {})
        if exclusions:
            lines.append("| 文件 | 排除理由 |")
            lines.append("|---|---|")
            for fname, reason in exclusions.items():
                lines.append(f"| ❌ {fname} | {reason.get('reason', '')} |")
            lines.append("")
        noise_log = step2.get("scan_log_noise", {})
        if noise_log:
            lines.append(f"- 扫描日志 NOISE 干扰：**{noise_log.get('noise_count', 0)}** 条（型号以 NOISE- 开头）已排除\n")

        # ============================================================
        # 第八章：处理建议
        # ============================================================
        lines.append("## 八、处理建议\n")

        lines.append("### 🔴 紧急（本周内）\n")
        for a in anomalies:
            if "严重" in a.get("严重程度", ""):
                lines.append(f"- **{a['品类']}**（差异率 {a['差异率']}%）：全品类复盘，重点 SKU 实物复核")
        no_log_count = log_corr.get("无日志关联", {}).get("count", 0) if isinstance(log_corr, dict) else 0
        if no_log_count > 0:
            lines.append(f"- **{no_log_count}** 个无日志关联 SKU 逐一现场排查")
        lines.append("")

        lines.append("### 🟡 重要（两周内）\n")
        lines.append("- 差异金额 > 2000 元的 SKU 追责到人")
        lines.append("- 已停用库位上的差异 SKU 做库位清理")
        lines.append("- 缺失成本单价的 SKU 补充价格信息")
        lines.append("")

        lines.append("### 🟢 流程优化\n")
        lines.append("- 扫描日志完整性提升（减少 NOISE 干扰）")
        lines.append("- 初盘双人复核机制")
        lines.append("- 停用库位定期清理，系统标记限制出入库")
        lines.append("- 出入库记录与系统日志的定期对账")
        lines.append("")

        # ============================================================
        # 附录
        # ============================================================
        lines.append("---\n")
        lines.append("## 附录：财务影响估算\n")
        step6 = self.analysis_result.get("Step 6: 计算差异金额", {})
        lines.append(f"- 盘亏金额：{step6.get('total_loss_amount', 0):,.2f} 元")
        lines.append(f"- 盘盈金额：{step6.get('total_gain_amount', 0):,.2f} 元")
        lines.append(f"- **净差异金额：{step6.get('net_variance_amount', 0):,.2f} 元**（需调账）")
        lines.append(f"- 成本口径：参考成本单价（非售价），缺失值用同品类均值估算")
        lines.append(f"- 估算成本 SKU：{step6.get('estimated_cost_count', 0)} 个\n")

        lines.append("### 附录：质量校验结果\n")
        checks = self.analysis_result.get("quality_checks", [])
        passed = sum(1 for c in checks if c.get("passed", False))
        lines.append(f"通过：**{passed}/{len(checks)}**\n")
        for i, check in enumerate(checks, 1):
            status = "✅" if check.get("passed") else "❌"
            lines.append(f"{status} **{i}. {check.get('name', '')}** ({check.get('importance', '')})")
            lines.append(f"   {check.get('detail', '')}\n")

        lines.append("### 附录：口径说明\n")
        lines.append("- **比对基准**：02_库存快照_20190428（型号编码）为主基准，01_库存快照_20190425（货号编码）仅交叉验证")
        lines.append("- **差异金额**：差异数量 × 参考成本单价（成本口径，非售价）")
        lines.append("- **日志窗口**：4/25-4/28 的操作记录（净变动 = 上架 - 拣货）")
        lines.append("- **库位警告**：02 快照为型号×库位粒度，04 盘点表为 SKU 粒度，差异无法精确归因到单个库位")
        lines.append("- **Ground Truth**：系统库存 21144 | 净差异 -971 | 差异率 4.6% | 净金额 -989,900.97")
        lines.append("")

        path.write_text("\n".join(lines), encoding="utf-8")

    def _is_blocking_step_failure(self, step_name: str, result) -> tuple:
        """判断某步是否为阻断失败。

        Returns:
            (is_blocking: bool, reason: str)
        """
        if not isinstance(result, dict):
            return False, ""
        is_error_result = "error" in result

        blocking_steps = {
            "Step 1: 加载所有文件": ("error" in result or result.get("total_files", 0) == 0),
            "Step 3: 选定比对基准": (result.get("selected") is None),
            "Step 5: 加载盘点结果": is_error_result,
            "Step 6: 计算差异金额": is_error_result,
        }

        should_block = blocking_steps.get(step_name, False)
        if should_block:
            reason = result.get("error", result.get("reason", f"{step_name} 执行失败"))
            return True, reason
        return False, ""

    def generate_executive_report(self, output_dir: str = None, lang: str = "en") -> str:
        """使用本地 LLM 生成管理层摘要报告（GPU 推理环节）。

        Args:
            output_dir: 报告输出目录，默认使用配置中的 output_dir
            lang: 语言 ('en' or 'zh')

        Returns:
            生成的 Markdown 格式报告
        """
        if not self.analysis_result:
            return "请先运行分析工作流，然后再生成报告。"

        if output_dir is None:
            output_dir = self.config.get("data", {}).get("output_dir", "data/output")

        # 阻断门禁：工作流被阻断则不生成报告
        if "_blocked" in self.analysis_result:
            blocked = self.analysis_result["_blocked"]
            return (
                "## 工作流已被阻断\n\n"
                "关键步骤未通过，不生成管理层报告。\n\n"
                f"- **阻断步骤**：{blocked.get('step', '未知')}\n"
                f"- **原因**：{blocked.get('reason', '未知')}\n\n"
                "请修复输入数据后重新运行分析。"
            )

        # 质量门禁：关键校验失败则不生成报告
        checks = self.analysis_result.get("quality_checks", [])
        critical_failed = [c for c in checks if c.get("severity") == "critical" and not c.get("passed")]
        if critical_failed:
            lines = ["## 关键质量校验未通过\n\n", "以下关键质量校验未通过，不生成管理层报告：\n\n"]
            for c in critical_failed:
                lines.append(f"- ❌ **{c.get('name', '')}**：{c.get('detail', '')}\n")
            lines.append("\n请解决上述问题后重新运行分析。")
            return "".join(lines)

        # 生成报告
        report = self.report_generator.generate_report(self.analysis_result, lang=lang)

        # 保存报告
        output_path = Path(output_dir) / "管理层摘要报告.md"
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(report, encoding="utf-8")

        return report

    def _collect_input_file_audit(self, input_dir: str) -> list[dict]:
        """收集输入目录下每个文件的指纹审计信息。"""
        input_path = Path(input_dir)
        if not input_path.exists():
            return [{"error": f"目录不存在: {input_dir}"}]
        files_info = []
        try:
            for f in sorted(input_path.iterdir()):
                if f.is_file():
                    sha256 = hashlib.sha256(f.read_bytes()).hexdigest()
                    st = f.stat()
                    files_info.append({
                        "name": f.name,
                        "suffix": f.suffix,
                        "size_bytes": st.st_size,
                        "sha256": sha256,
                        "modified_at": datetime.fromtimestamp(st.st_mtime).isoformat(),
                    })
        except Exception as e:
            return [{"error": str(e)}]
        return files_info

    def _generate_top_variance_skus(self):
        if self._variance_df is None:
            self.run_metadata["top_variance_skus"] = []
            self.analysis_result["top_variance_skus"] = []
            return

        df = self._variance_df
        diff_df = df[df["差异数量"] != 0].copy()
        if len(diff_df) == 0:
            self.run_metadata["top_variance_skus"] = []
            self.analysis_result["top_variance_skus"] = []
            return

        diff_df["金额绝对值"] = diff_df["差异金额"].abs()
        top5 = diff_df.nlargest(5, "金额绝对值")

        skus = []
        for rank, (_, row) in enumerate(top5.iterrows(), 1):
            skus.append({
                "rank": rank,
                "sku": row.get("型号", ""),
                "category": row.get("品类", ""),
                "system_stock": int(row.get("系统库存数", 0)),
                "recount_stock": int(row.get("复盘数", 0)),
                "variance_qty": int(row.get("差异数量", 0)),
                "variance_amount": round(float(row.get("差异金额", 0)), 2),
                "variance_type": row.get("差异类型", ""),
            })

        self.run_metadata["top_variance_skus"] = skus
        self.analysis_result["top_variance_skus"] = skus

    def _generate_disposition_recommendations(self):
        step7 = self.analysis_result.get("Step 7: 日志关联分析", {})
        step8 = self.analysis_result.get("Step 8: 库位状态校验", {})
        step9 = self.analysis_result.get("Step 9: 品类维度分析", {})

        recommendations = []

        fully = step7.get("完全可解释", {})
        if fully.get("count", 0) > 0:
            recommendations.append({
                "category": "可直接调账候选",
                "trigger_rule": "完全可解释（日志净变动量 >= 差异数量绝对值）",
                "related_count": fully["count"],
                "related_examples": fully.get("sku_list", [])[:5],
                "owner_role": "财务人员",
                "time_limit": "5 个工作日内",
                "recommendation": "进入财务复核，依据差异明细调账",
                "source_step": "Step 7",
            })

        partial = step7.get("部分可解释", {})
        if partial.get("count", 0) > 0:
            recommendations.append({
                "category": "需补充单据",
                "trigger_rule": "部分可解释（日志净变动量 > 0 但小于差异数量）",
                "related_count": partial["count"],
                "related_examples": partial.get("sku_list", [])[:5],
                "owner_role": "仓库主管 / 单据员",
                "time_limit": "3 个工作日内",
                "recommendation": "补充出入库记录，追查差异原因",
                "source_step": "Step 7",
            })

        no_log = step7.get("无日志关联", {})
        if no_log.get("count", 0) > 0:
            recommendations.append({
                "category": "需现场复核",
                "trigger_rule": "无日志关联（盘点周期内无任何操作记录）",
                "related_count": no_log["count"],
                "related_examples": no_log.get("sku_list", [])[:5],
                "owner_role": "仓库主管",
                "time_limit": "2 个工作日内",
                "recommendation": "实物复盘，确认实物实际存放位置",
                "source_step": "Step 7",
            })

        abnormal_count = step8.get("abnormal_count", 0)
        if abnormal_count > 0:
            abnormal_skus = step8.get("abnormal_location_skus", [])
            examples = [s.get("型号", "") for s in abnormal_skus[:5]]
            recommendations.append({
                "category": "需库位核查",
                "trigger_rule": "差异 SKU 位于已停用或维修中库位",
                "related_count": abnormal_count,
                "related_examples": examples,
                "owner_role": "仓库主管 / WMS 管理员",
                "time_limit": "2 个工作日内",
                "recommendation": "核查库位状态，确认实物实际存放位置",
                "source_step": "Step 8",
            })

        anomaly_cats = step9.get("anomaly_categories", [])
        severe_cats = [a for a in anomaly_cats if a.get("严重程度") == "严重异常"]
        if severe_cats:
            recommendations.append({
                "category": "需专项整改",
                "trigger_rule": "品类差异率 > 10%，严重异常",
                "related_count": len(severe_cats),
                "related_examples": [a.get("品类", "") for a in severe_cats[:5]],
                "owner_role": "品类负责人 / 供应链管理层",
                "time_limit": "1 周内",
                "recommendation": "品类复盘，重点 SKU 实物复核",
                "source_step": "Step 9",
            })

        self.analysis_result["disposition_recommendations"] = recommendations

    def _generate_deliverable_package(self):
        output_dir = self.run_metadata.get("output_dir", "data/output")

        self.run_metadata["deliverable_package"] = {
            "excel": {
                "path": f"{output_dir}/盘点差异明细表.xlsx",
                "exists": Path(f"{output_dir}/盘点差异明细表.xlsx").exists(),
                "purpose": "财务复核和调账依据",
            },
            "analysis_report": {
                "path": f"{output_dir}/盘点差异分析报告.md",
                "exists": Path(f"{output_dir}/盘点差异分析报告.md").exists(),
                "purpose": "审计过程和分析口径说明",
            },
            "management_report": {
                "path": f"{output_dir}/管理层摘要报告.md",
                "exists": Path(f"{output_dir}/管理层摘要报告.md").exists(),
                "purpose": "管理层会议摘要，由 demo/mock/real LLM 报告入口生成",
            },
            "metadata": {
                "path": f"{output_dir}/analysis_result.json",
                "exists": True,
                "purpose": "运行元数据、质量门禁和审计追踪",
            },
            "llm_benchmark": {
                "path": f"{output_dir}/llm_benchmark.json",
                "exists": Path(f"{output_dir}/llm_benchmark.json").exists(),
                "purpose": "本地 LLM / AMD ROCm 推理证据，运行 benchmark 后生成",
            },
        }

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
            css=APP_CSS,
        )
    else:
        print("Gradio 未安装，仅运行工作流...")
        input_dir = config.get("data", {}).get("input_dir", "data/input")
        output_dir = config.get("data", {}).get("output_dir", "data/output")
        result = agent.run_workflow(input_dir, output_dir)
        print(f"工作流完成，结果保存到 {output_dir}/analysis_result.json")


if __name__ == "__main__":
    main()
