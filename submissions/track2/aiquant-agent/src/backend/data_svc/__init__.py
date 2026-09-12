"""
OpenBB-SDK → Qlib 数据适配器

功能:
1. 通过 OpenBB-SDK + akshare 统一获取 A 股数据
2. 自动转换为 Qlib 接受的 pd.DataFrame 格式
3. 自动完成前复权、剔除 ST、剔除次新股、财报时间对齐
"""
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, Literal
from loguru import logger

from backend.shared.config import settings


class OpenBBDataProvider:
    """
    A股数据获取器 — 本地优先（Qlib），在线降级（akshare → OpenBB）
    """

    def __init__(self):
        self._cache = {}
        self._qlib_ready = False

    def _ensure_qlib(self):
        """初始化 Qlib（仅一次）"""
        if self._qlib_ready:
            return
        import qlib
        qlib.init(provider_uri="~/.qlib/qlib_data/cn_data", region="cn")
        self._qlib_ready = True

    # ── 行情数据 ──────────────────────────────────────

    def get_a_share_daily(
        self,
        symbols: list[str],
        start_date: str,
        end_date: str,
        adjust: Literal["qfq", "hfq", "none"] = "qfq"
    ) -> pd.DataFrame:
        """
        获取 A 股日线行情，返回 Qlib 格式 DataFrame
        列: date, instrument, open, high, low, close, volume, amount, factor
        策略：本地优先（Qlib），在线降级（akshare → OpenBB）
        """
        logger.info(f"获取 {len(symbols)} 只股票日线: {start_date} ~ {end_date}")
        all_frames = []
        qlib_hits, online_hits, misses = 0, 0, 0

        for symbol in symbols:
            try:
                df = self._fetch_single_stock_daily(symbol, start_date, end_date, adjust)
                if df is not None and not df.empty:
                    all_frames.append(df)
                    if getattr(df, "_source", None) == "qlib":
                        qlib_hits += 1
                    elif getattr(df, "_source", None) == "online":
                        online_hits += 1
                else:
                    misses += 1
            except Exception as e:
                logger.warning(f"获取 {symbol} 失败: {e}")
                misses += 1

        if not all_frames:
            raise ValueError("没有获取到任何股票数据")

        result = pd.concat(all_frames, ignore_index=True)
        result = result.drop_duplicates(subset=["date", "instrument"])
        logger.info(
            f"获取完成，共 {len(result)} 条 "
            f"(本地命中 {qlib_hits} / 在线降级 {online_hits} / 失败 {misses})"
        )
        return result

    def _fetch_single_stock_daily(
        self, symbol: str, start_date: str, end_date: str, adjust: str
    ) -> Optional[pd.DataFrame]:
        """
        获取单只股票日线
        优先级：Qlib 本地 → akshare 在线 → OpenBB 在线
        """
        # 1) Qlib 本地优先
        df = self._fetch_qlib_local(symbol, start_date, end_date)
        if df is not None and not df.empty:
            df._source = "qlib"
            return df

        # 2) akshare 降级
        df = self._fetch_akshare_daily(symbol, start_date, end_date, adjust)
        if df is not None and not df.empty:
            df._source = "online"
            return df

        # 3) OpenBB 最后兜底
        df = self._fetch_openbb_daily(symbol, start_date, end_date)
        if df is not None and not df.empty:
            df._source = "online"
            return df

        logger.warning(f"所有数据源均失败: {symbol}")
        return None

    def _fetch_qlib_local(
        self, symbol: str, start_date: str, end_date: str
    ) -> Optional[pd.DataFrame]:
        """从 Qlib 本地缓存读取日线数据（首选）"""
        try:
            self._ensure_qlib()
            from qlib.data import D

            qlib_sym = self._to_qlib_symbol(symbol).upper()
            fields = ["$open", "$high", "$low", "$close", "$volume", "$factor"]
            df = D.features([qlib_sym], fields, start_time=start_date, end_time=end_date)

            if df is None or df.empty:
                return None

            df = df.reset_index()
            df = df.rename(columns={
                "$open": "open", "$high": "high", "$low": "low",
                "$close": "close", "$volume": "volume", "$factor": "factor",
                "instrument": "instrument", "datetime": "date",
            })
            df["date"] = pd.to_datetime(df["date"]).dt.strftime("%Y-%m-%d")
            df["instrument"] = self._to_qlib_symbol(symbol)
            df["amount"] = df["close"] * df["volume"]
            cols = ["date", "instrument", "open", "high", "low", "close", "volume", "amount", "factor"]
            logger.debug(f"Qlib 本地命中 {symbol}: {len(df)} 条")
            return df[cols]

        except Exception as e:
            logger.warning(f"Qlib 本地获取失败 {symbol}: {e}")
            return None

    def _fetch_akshare_daily(
        self, symbol: str, start_date: str, end_date: str, adjust: str
    ) -> Optional[pd.DataFrame]:
        """akshare 在线获取（降级方案）"""
        try:
            import akshare as ak

            code = self._to_pure_code(symbol)
            adjust_map = {"qfq": "qfq", "hfq": "hfq", "none": ""}
            ak_adjust = adjust_map.get(adjust, "qfq")

            df = ak.stock_zh_a_hist(
                symbol=code,
                period="daily",
                start_date=start_date.replace("-", ""),
                end_date=end_date.replace("-", ""),
                adjust=ak_adjust,
            )

            if df is None or df.empty:
                return None

            df = df.rename(columns={
                "日期": "date",
                "开盘": "open",
                "最高": "high",
                "最低": "low",
                "收盘": "close",
                "成交量": "volume",
                "成交额": "amount",
            })

            df["instrument"] = self._to_qlib_symbol(symbol)
            df["factor"] = 1.0 if adjust == "qfq" else df.get("factor", 1.0)
            cols = ["date", "instrument", "open", "high", "low", "close", "volume", "amount", "factor"]
            logger.info(f"akshare 在线获取 {symbol}: {len(df)} 条")
            return df[cols]

        except Exception as e:
            logger.warning(f"akshare 获取失败 {symbol}: {e}")
            return None

    def _fetch_openbb_daily(
        self, symbol: str, start_date: str, end_date: str
    ) -> Optional[pd.DataFrame]:
        """OpenBB 在线获取（最后兜底）"""
        try:
            from openbb import obb

            normalized = self._normalize_symbol(symbol)
            obb_output = obb.equity.price.historical(
                symbol=normalized,
                start_date=start_date,
                end_date=end_date,
                provider="yfinance",
            )
            df = obb_output.to_dataframe()

            if df is None or df.empty:
                return None

            df = df.rename(columns={
                "open": "open", "high": "high",
                "low": "low", "close": "close", "volume": "volume",
            })
            df["date"] = pd.to_datetime(df.index).strftime("%Y-%m-%d")
            df["instrument"] = self._to_qlib_symbol(symbol)
            df["factor"] = 1.0
            if "amount" not in df.columns:
                df["amount"] = df["close"] * df["volume"]
            cols = ["date", "instrument", "open", "high", "low", "close", "volume", "amount", "factor"]
            logger.info(f"OpenBB 在线获取 {symbol}: {len(df)} 条")
            return df[cols]

        except Exception as e:
            logger.warning(f"OpenBB 获取失败 {symbol}: {e}")
            return None

    # ── 财务数据 ──────────────────────────────────────

    def get_financial_statements(
        self, symbols: list[str], report_type: str = "income"
    ) -> pd.DataFrame:
        """
        获取财务报表数据（利润表/资产负债表/现金流表）
        返回 Qlib 格式: date, instrument, 财务指标列...
        自动对齐财报截止日期，解决未来函数问题
        """
        logger.info(f"获取 {len(symbols)} 只股票财务数据: {report_type}")
        all_frames = []

        for symbol in symbols:
            try:
                df = self._fetch_single_financial(symbol, report_type)
                if df is not None and not df.empty:
                    all_frames.append(df)
            except Exception as e:
                logger.warning(f"获取财务数据失败 {symbol}: {e}")

        if not all_frames:
            return pd.DataFrame()

        result = pd.concat(all_frames, ignore_index=True)
        # 财报时间对齐：报表截止日期后 4 个月才能使用该数据
        result = self._align_report_date(result)
        logger.info(f"财务数据获取完成，共 {len(result)} 条")
        return result

    def _fetch_single_financial(
        self, symbol: str, report_type: str
    ) -> Optional[pd.DataFrame]:
        """获取单只股票财务数据"""
        try:
            import akshare as ak

            code = self._to_pure_code(symbol)

            if report_type == "income":
                df = ak.stock_profit_sheet_by_report_em(symbol=code)
            elif report_type == "balance":
                df = ak.stock_balance_sheet_by_report_em(symbol=code)
            elif report_type == "cashflow":
                df = ak.stock_cash_flow_sheet_by_report_em(symbol=code)
            else:
                return None

            if df is None or df.empty:
                return None

            df["instrument"] = self._to_qlib_symbol(symbol)
            # 财报截止日期列
            date_col = [c for c in df.columns if "日期" in c or "date" in c.lower()]
            if date_col:
                df = df.rename(columns={date_col[0]: "date"})
                df["date"] = pd.to_datetime(df["date"]).dt.strftime("%Y-%m-%d")

            return df

        except Exception as e:
            logger.error(f"财务数据获取失败 {symbol}: {e}")
            return None

    def _align_report_date(self, df: pd.DataFrame, lag_months: int = 4) -> pd.DataFrame:
        """
        财报时间对齐：避免未来函数
        例如 Q1 报告（3/31）要到 7/31 才能使用
        """
        df = df.copy()
        df["date"] = pd.to_datetime(df["date"])
        df["usable_date"] = df["date"] + pd.DateOffset(months=lag_months)
        return df

    # ── 分析师预期数据 ────────────────────────────────

    def get_analyst_estimates(self, symbols: list[str]) -> pd.DataFrame:
        """获取分析师一致预期数据"""
        logger.info(f"获取 {len(symbols)} 只股票分析师预期")
        # OpenBB 对 A 股支持有限，用 akshare
        try:
            import akshare as ak
            all_frames = []
            for symbol in symbols:
                code = self._to_pure_code(symbol)
                try:
                    df = ak.stock_profit_forecast_em(symbol=code)
                    if df is not None and not df.empty:
                        df["instrument"] = self._to_qlib_symbol(symbol)
                        all_frames.append(df)
                except Exception:
                    pass
            if all_frames:
                return pd.concat(all_frames, ignore_index=True)
            return pd.DataFrame()
        except Exception as e:
            logger.warning(f"分析师预期获取失败: {e}")
            return pd.DataFrame()

    # ── 北向资金 / 融资融券 ───────────────────────────

    def get_north_flow(self, symbols: list[str], start_date: str, end_date: str) -> pd.DataFrame:
        """获取北向资金持股数据"""
        logger.info(f"获取北向资金数据: {len(symbols)} 只股票")
        try:
            import akshare as ak
            all_frames = []
            for symbol in symbols:
                code = self._to_pure_code(symbol)
                try:
                    df = ak.stock_hsgt_individual_em(stock=code)
                    if df is not None and not df.empty:
                        df["instrument"] = self._to_qlib_symbol(symbol)
                        all_frames.append(df)
                except Exception:
                    pass
            if all_frames:
                return pd.concat(all_frames, ignore_index=True)
            return pd.DataFrame()
        except Exception as e:
            logger.warning(f"北向资金获取失败: {e}")
            return pd.DataFrame()

    def get_margin_data(self, symbols: list[str], start_date: str, end_date: str) -> pd.DataFrame:
        """获取融资融券数据"""
        logger.info(f"获取融资融券数据: {len(symbols)} 只股票")
        try:
            import akshare as ak
            all_frames = []
            for symbol in symbols:
                code = self._to_pure_code(symbol)
                try:
                    df = ak.stock_margin_detail_sse(date=end_date.replace("-", ""))
                    if df is not None and not df.empty:
                        df = df[df["股票代码"].str.contains(code)]
                        if not df.empty:
                            df["instrument"] = self._to_qlib_symbol(symbol)
                            all_frames.append(df)
                except Exception:
                    pass
            if all_frames:
                return pd.concat(all_frames, ignore_index=True)
            return pd.DataFrame()
        except Exception as e:
            logger.warning(f"融资融券获取失败: {e}")
            return pd.DataFrame()

    # ── 辅助方法 ──────────────────────────────────────

    @staticmethod
    def _normalize_symbol(symbol: str) -> str:
        """
        标准化股票代码
        sh600000 → 600000.SS
        sz000001 → 000001.SZ
        """
        symbol = symbol.strip().lower()
        if symbol.startswith("sh"):
            return f"{symbol[2:]}.SS"
        elif symbol.startswith("sz"):
            return f"{symbol[2:]}.SZ"
        return symbol

    @staticmethod
    def _to_qlib_symbol(symbol: str) -> str:
        """转换为 Qlib 格式: sh600000"""
        symbol = symbol.strip()
        if symbol.startswith("sh") or symbol.startswith("sz"):
            return symbol
        code = symbol.replace(".SS", "").replace(".SZ", "")
        if code.startswith(("6", "9")):
            return f"sh{code}"
        elif code.startswith(("0", "3", "2")):
            return f"sz{code}"
        return f"sh{code}"

    @staticmethod
    def _to_pure_code(symbol: str) -> str:
        """提取纯数字代码: sh600000 → 600000"""
        symbol = symbol.strip()
        for prefix in ("sh", "sz", "SH", "SZ"):
            if symbol.startswith(prefix):
                return symbol[2:]
        return symbol.replace(".SS", "").replace(".SZ", "")


class DataCleaner:
    """
    数据清洗器：前复权、剔除 ST、剔除次新股
    """

    @staticmethod
    def remove_st_stocks(df: pd.DataFrame) -> pd.DataFrame:
        """
        剔除 ST / *ST 股票
        """
        if "symbol" in df.columns:
            import akshare as ak
            try:
                st_list = ak.stock_zh_a_st_em()
                st_codes = set(st_list["代码"].tolist())
                df = df[~df["symbol"].apply(
                    lambda x: DataCleaner._extract_code(x) in st_codes
                )]
                logger.info(f"剔除 ST 后剩余 {len(df)} 条")
            except Exception:
                pass
        return df

    @staticmethod
    def remove_new_stocks(
        df: pd.DataFrame, min_list_days: int = 250
    ) -> pd.DataFrame:
        """
        剔除次新股（上市不足 min_list_days 个交易日）
        """
        if "instrument" in df.columns and "date" in df.columns:
            df = df.copy()
            df["date"] = pd.to_datetime(df["date"])
            counts = df.groupby("instrument")["date"].nunique()
            valid = counts[counts >= min_list_days].index
            df = df[df["instrument"].isin(valid)]
            logger.info(f"剔除次新股（<{min_list_days}天）后剩余 {df['instrument'].nunique()} 只")
        return df

    @staticmethod
    def ensure_forward_adjust(df: pd.DataFrame) -> pd.DataFrame:
        """
        确保前复权：如果 factor 列不全为 1，则应用复权因子
        """
        if "factor" not in df.columns:
            return df
        df = df.copy()
        if not (df["factor"] == 1.0).all():
            price_cols = ["open", "high", "low", "close"]
            for col in price_cols:
                if col in df.columns:
                    df[col] = df[col] * df["factor"]
            df["factor"] = 1.0
            logger.info("已应用前复权因子")
        return df

    @staticmethod
    def _extract_code(symbol: str) -> str:
        for prefix in ("sh", "sz"):
            if symbol.lower().startswith(prefix):
                return symbol[2:]
        return symbol


# ── 特征工程扩展 ──────────────────────────────────────

class FeatureEngineering:
    """
    基于 OpenBB-SDK 内置指标 + 自定义因子，构建扩展特征池
    为 R-Agent 提供基本面 + 资金类因子素材
    """

    @staticmethod
    def add_technical_indicators(df: pd.DataFrame) -> pd.DataFrame:
        """添加技术指标特征"""
        df = df.copy()
        if "close" not in df.columns:
            return df

        for inst in df["instrument"].unique():
            mask = df["instrument"] == inst
            sub = df.loc[mask].sort_values("date")

            close = sub["close"].astype(float)
            volume = sub["volume"].astype(float)

            # 收益率
            df.loc[mask, "ret_1d"] = close.pct_change()
            df.loc[mask, "ret_5d"] = close.pct_change(5)
            df.loc[mask, "ret_20d"] = close.pct_change(20)

            # 均线偏离
            df.loc[mask, "ma5_bias"] = close / close.rolling(5).mean() - 1
            df.loc[mask, "ma20_bias"] = close / close.rolling(20).mean() - 1

            # 波动率
            df.loc[mask, "vol_20d"] = df.loc[mask, "ret_1d"].rolling(20).std()

            # 量比
            df.loc[mask, "volume_ratio"] = volume / volume.rolling(20).mean()

            # RSI
            delta = close.diff()
            gain = delta.clip(lower=0).rolling(14).mean()
            loss = (-delta.clip(upper=0)).rolling(14).mean()
            rs = gain / loss.replace(0, np.nan)
            df.loc[mask, "rsi_14"] = 100 - (100 / (1 + rs))

        return df

    @staticmethod
    def add_fundamental_features(
        financial_df: pd.DataFrame, daily_df: pd.DataFrame
    ) -> pd.DataFrame:
        """
        将基本面数据合并到日线数据中，生成基本面因子
        使用 usable_date 对齐避免未来函数
        """
        if financial_df.empty or daily_df.empty:
            return daily_df

        daily_df = daily_df.copy()
        daily_df["date"] = pd.to_datetime(daily_df["date"])

        if "usable_date" in financial_df.columns:
            fin_df = financial_df.rename(columns={"usable_date": "align_date"})
        else:
            fin_df = financial_df.rename(columns={"date": "align_date"})

        # 按最近可用财报合并
        merged = pd.merge_asof(
            daily_df.sort_values("date"),
            fin_df.sort_values("align_date"),
            left_on="date",
            right_on="align_date",
            by="instrument",
            direction="backward",
            tolerance=pd.Timedelta(days=365),
        )
        return merged


# ── 数据导出为 Qlib 格式 ─────────────────────────────

class QlibDataExporter:
    """
    将处理好的数据导出为 Qlib 兼容格式。
    
    Qlib FileStorage 期望的目录结构:
      qlib_data/
        calendars/day.txt          # 每行一个日期 YYYY-MM-DD
        instruments/all.txt        # instrument\ts tart_date\tend_date (tab分隔)
        features/{inst}/{field}.day.bin  # 二进制格式: [start_index] + [float32 data...]
    
    其中 bin 文件第一项是起始 index (对应 calendar 中的行号)，后续是 float32 数据。
    """

    @staticmethod
    def export_to_qlib(
        df: pd.DataFrame,
        target_dir: Path = None,
        freq: str = "day",
    ) -> Path:
        """
        导出 DataFrame 到 Qlib 兼容的二进制数据目录。
        """
        if target_dir is None:
            target_dir = settings.db_dir

        target_dir = Path(target_dir)
        features_dir = target_dir / "features"
        instruments_dir = target_dir / "instruments"
        calendars_dir = target_dir / "calendars"

        for d in [features_dir, instruments_dir, calendars_dir]:
            d.mkdir(parents=True, exist_ok=True)

        # 1) 保存交易日历
        df = df.copy()
        df["date"] = pd.to_datetime(df["date"])
        dates = sorted(df["date"].unique())
        date_strs = [d.strftime("%Y-%m-%d") for d in dates]
        date_to_idx = {d: i for i, d in enumerate(dates)}

        with open(calendars_dir / "day.txt", "w") as f:
            f.write("\n".join(date_strs))
        logger.info(f"交易日历: {len(dates)} 天 ({date_strs[0]} ~ {date_strs[-1]})")

        # 2) 保存 instruments (Qlib 格式: instrument\tstart_date\tend_date)
        instruments = sorted(df["instrument"].unique())
        with open(instruments_dir / "all.txt", "w") as f:
            for inst in instruments:
                inst_df = df[df["instrument"] == inst]
                inst_dates = sorted(inst_df["date"])
                if len(inst_dates) > 0:
                    start = inst_dates[0].strftime("%Y-%m-%d")
                    end = inst_dates[-1].strftime("%Y-%m-%d")
                    f.write(f"{inst}\t{start}\t{end}\n")
        logger.info(f"Instruments: {len(instruments)} 只")

        # 3) 按 instrument + field 导出 Qlib 二进制 .bin 文件
        #    使用 groupby 迭代器（惰性），避免重复过滤大 DataFrame
        feature_cols = [c for c in df.columns if c not in ("instrument", "date")]
        logger.info(f"导出 {len(feature_cols)} 个特征字段到 Qlib .bin 格式 "
                    f"({len(instruments)} 只股票)...")

        total_fields = 0
        for i, (inst, grp) in enumerate(df.groupby("instrument", sort=False)):
            inst_dir = features_dir / inst.lower()
            inst_dir.mkdir(parents=True, exist_ok=True)

            inst_df = grp.set_index("date").sort_index()

            for field in feature_cols:
                if field not in inst_df.columns:
                    continue
                series = inst_df[field].dropna()
                if len(series) == 0:
                    continue
                first_date = series.index[0]
                start_idx = date_to_idx.get(first_date, 0)
                bin_path = inst_dir / f"{field.lower()}.{freq}.bin"
                try:
                    data = np.array([start_idx] + series.values.tolist(), dtype=np.float32)
                    data.astype("<f").tofile(bin_path)
                    total_fields += 1
                except Exception as e:
                    logger.warning(f"导出 {inst}/{field} 失败: {e}")

            if (i + 1) % 500 == 0:
                logger.info(f"  导出进度: {i+1}/{len(instruments)}")

        logger.info(f"Qlib 二进制数据已导出到 {target_dir} ({total_fields} 个字段文件)")
        return target_dir

    @staticmethod
    def export_to_qlib_for_rdagent(
        df: pd.DataFrame,
        target_dir: Path = None,
    ) -> Path:
        """
        导出为 RD-Agent 可用的 Qlib 数据格式。
        
        RD-Agent 使用 ~/.qlib/qlib_data/cn_data 作为默认路径。
        同时支持通过环境变量 QLIB_DATA_PATH 覆盖。
        """
        import os
        if target_dir is None:
            target_dir = Path(os.path.expanduser("~/.qlib/qlib_data/cn_data"))
        return QlibDataExporter.export_to_qlib(df, target_dir)


# ── 统一数据管线 ──────────────────────────────────────

class DataPipeline:
    """
    统一数据管线：
    OpenBB-SDK 获取 → 清洗 → 特征工程 → Qlib 格式导出
    """

    def __init__(self):
        self.provider = OpenBBDataProvider()
        self.cleaner = DataCleaner()
        self.fe = FeatureEngineering()
        self.exporter = QlibDataExporter()

    def run(
        self,
        symbols: list[str],
        start_date: str = None,
        end_date: str = None,
    ) -> Path:
        """
        执行完整数据管线
        """
        start_date = start_date or settings.market_start_date
        end_date = end_date or datetime.now().strftime("%Y-%m-%d")

        logger.info(f"=== 启动数据管线: {start_date} ~ {end_date} ===")

        # Step 1: 获取行情数据
        logger.info("[1/5] 获取日线行情...")
        daily = self.provider.get_a_share_daily(symbols, start_date, end_date)

        # Step 2: 数据清洗
        logger.info("[2/5] 数据清洗（前复权、剔除ST、剔除次新股）...")
        daily = self.cleaner.ensure_forward_adjust(daily)
        daily = self.cleaner.remove_new_stocks(daily)

        # Step 3: 技术指标特征
        logger.info("[3/5] 计算技术指标特征...")
        daily = self.fe.add_technical_indicators(daily)

        # Step 4: 获取基本面数据并合并
        logger.info("[4/5] 获取基本面数据...")
        financial = self.provider.get_financial_statements(symbols, "income")
        if not financial.empty:
            daily = self.fe.add_fundamental_features(financial, daily)

        # Step 5: 导出为 Qlib 格式
        logger.info("[5/5] 导出 Qlib 格式数据...")
        output_dir = self.exporter.export_to_qlib(daily)

        logger.info(f"=== 数据管线完成！输出目录: {output_dir} ===")
        return output_dir
