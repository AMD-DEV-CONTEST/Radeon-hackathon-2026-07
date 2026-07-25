"""
Noise Detector — 智能噪音识别模块。
自动识别并分类：NOISE 干扰数据、异常记录、不适用文件。
"""

from pathlib import Path
import pandas as pd


class NoiseDetector:
    def __init__(self, config: dict):
        self.noise_prefix = config.get("noise_detection", {}).get("noise_prefix", "NOISE-")
        self.exclude_patterns = config.get("noise_detection", {}).get("exclude_files", [])

    def detect_scan_log_noise(self, df: pd.DataFrame, model_col: str = "商品型号") -> dict:
        """检测扫描日志中的 NOISE 干扰记录。"""
        if model_col not in df.columns:
            return {"noise_count": 0, "real_count": len(df), "noise_mask": pd.Series([False] * len(df))}

        noise_mask = df[model_col].astype(str).str.startswith(self.noise_prefix)
        noise_records = df[noise_mask]
        real_records = df[~noise_mask]

        return {
            "noise_count": len(noise_records),
            "real_count": len(real_records),
            "noise_mask": noise_mask,
            "noise_models": noise_records[model_col].unique().tolist() if len(noise_records) > 0 else [],
        }

    def detect_history_anomalies(self, df: pd.DataFrame) -> dict:
        """检测历史库存数据中的异常记录。"""
        anomalies = {
            "test_prefix": 0,
            "negative_qty": 0,
            "extreme_dates": 0,
            "empty_rows": 0,
            "total_anomalies": 0,
        }

        for col in df.columns:
            if df[col].dtype == object:
                test_mask = df[col].astype(str).str.startswith("TEST", na=False)
                anomalies["test_prefix"] += test_mask.sum()

        if "数量" in df.columns:
            anomalies["negative_qty"] = (pd.to_numeric(df["数量"], errors="coerce") < 0).sum()

        if "效期" in df.columns:
            extreme_mask = df["效期"].astype(str).isin(["12/31/9999", "01/01/1900", "9999-12-31", "1900-01-01"])
            anomalies["extreme_dates"] = extreme_mask.sum()

        anomalies["empty_rows"] = df.isnull().all(axis=1).sum()
        anomalies["total_anomalies"] = sum(v for k, v in anomalies.items() if k != "total_anomalies")

        return anomalies

    def should_exclude_file(self, file_path: Path) -> dict:
        """判断文件是否应被排除。"""
        file_name = file_path.name
        for pattern in self.exclude_patterns:
            if pattern.replace("*", "") in file_name:
                return {"exclude": True, "reason": f"文件名匹配排除模式: {pattern}"}
        return {"exclude": False, "reason": ""}

    def classify_scan_operations(self, df: pd.DataFrame) -> dict:
        """分类扫描日志操作类型。"""
        if "操作类型" not in df.columns:
            return {}

        op_counts = df["操作类型"].value_counts().to_dict()
        return {
            "total_records": len(df),
            "operation_types": op_counts,
            "has_shelf": "上架" in op_counts,
            "has_pick": "拣货" in op_counts,
            "has_transfer": "移库" in op_counts,
            "has_count": "盘点" in op_counts,
        }
