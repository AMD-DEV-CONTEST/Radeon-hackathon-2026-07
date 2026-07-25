"""
RAG Engine — 多文件异构数据理解引擎。
支持 CSV/XLSX/TXT 混合格式的文档索引和语义检索。
"""

from pathlib import Path
import pandas as pd


class MultiFileRAGEngine:
    def __init__(self, config: dict):
        self.config = config
        self.file_registry = {}
        self.dataframes = {}

    def load_all_files(self, input_dir: str) -> dict:
        """加载目录下所有支持的数据文件。"""
        input_path = Path(input_dir)
        if not input_path.exists():
            return {"error": f"目录不存在: {input_dir}"}

        results = {"loaded": [], "failed": [], "excluded": []}

        for file_path in sorted(input_path.glob("*")):
            if file_path.suffix.lower() == ".csv":
                self._load_csv(file_path, results)
            elif file_path.suffix.lower() == ".xlsx":
                self._load_xlsx(file_path, results)
            elif file_path.suffix.lower() == ".txt":
                self._load_txt(file_path, results)

        return results

    def _load_csv(self, path: Path, results: dict):
        """加载 CSV 文件（自动处理 BOM 头）。"""
        try:
            df = pd.read_csv(path, encoding="utf-8-sig")
            self.file_registry[path.name] = {"path": str(path), "type": "csv", "rows": len(df)}
            self.dataframes[path.name] = df
            results["loaded"].append(path.name)
        except Exception as e:
            results["failed"].append({"file": path.name, "error": str(e)})

    def _load_xlsx(self, path: Path, results: dict):
        """加载 XLSX 文件（多 sheet）。"""
        try:
            xls = pd.ExcelFile(path)
            for sheet in xls.sheet_names:
                df = pd.read_excel(path, sheet_name=sheet)
                key = f"{path.name}::{sheet}"
                self.file_registry[key] = {"path": str(path), "sheet": sheet, "type": "xlsx", "rows": len(df)}
                self.dataframes[key] = df
            results["loaded"].append(f"{path.name} ({len(xls.sheet_names)} sheets)")
        except Exception as e:
            results["failed"].append({"file": path.name, "error": str(e)})

    def _load_txt(self, path: Path, results: dict):
        """加载 TXT/TSV 文件。"""
        try:
            df = pd.read_csv(path, sep="\t")
            self.file_registry[path.name] = {"path": str(path), "type": "txt", "rows": len(df)}
            self.dataframes[path.name] = df
            results["loaded"].append(path.name)
        except Exception as e:
            results["failed"].append({"file": path.name, "error": str(e)})

    def get_dataframe(self, key: str) -> pd.DataFrame:
        """获取指定文件的 DataFrame。"""
        return self.dataframes.get(key)

    def search_by_keyword(self, keyword: str) -> list[dict]:
        """在所有文件中搜索关键词。"""
        results = []
        for key, df in self.dataframes.items():
            if df is None:
                continue
            for col in df.columns:
                if df[col].dtype == object:
                    matches = df[df[col].astype(str).str.contains(keyword, na=False)]
                    if len(matches) > 0:
                        results.append({
                            "file": key,
                            "column": col,
                            "matches": len(matches),
                            "sample": matches.head(3).to_dict("records"),
                        })
        return results

    def get_file_summary(self) -> dict:
        """获取所有已加载文件的概览。"""
        summary = {}
        for key, meta in self.file_registry.items():
            summary[key] = {
                "type": meta["type"],
                "rows": meta["rows"],
                "columns": list(self.dataframes[key].columns) if key in self.dataframes else [],
            }
        return summary
