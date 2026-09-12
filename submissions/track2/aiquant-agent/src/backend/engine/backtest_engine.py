"""
独立因子回测引擎 — 不依赖 Qlib/RD-Agent，纯 pandas + scipy 实现

功能:
1. 因子 IC / Rank IC / ICIR 计算
2. 分层回测 (quantile-based)
3. 行业中性化
4. 换手率 / Sharpe / 最大回撤 计算
5. 多周期回测

所有计算在单机 pandas 上完成，跨平台兼容
"""
import numpy as np
import pandas as pd
from scipy import stats
from pathlib import Path
from datetime import datetime
from typing import Optional, Literal
from dataclasses import dataclass, field
from loguru import logger


@dataclass
class BacktestConfig:
    """回测配置"""
    start_date: str = "2020-01-01"
    end_date: str = "2024-12-31"
    n_quantiles: int = 5          # 分层数量
    commission: float = 0.001     # 单边手续费
    slippage: float = 0.001       # 滑点
    weight_method: Literal["equal", "value"] = "equal"
    benchmark: str = "000300.SH"


@dataclass
class FactorResult:
    """单因子回测结果"""
    factor_name: str
    factor_expression: str
    ic_mean: float = 0.0
    ic_std: float = 0.0
    icir: float = 0.0
    rank_ic_mean: float = 0.0
    rank_icir: float = 0.0
    sharpe: float = 0.0
    annual_return: float = 0.0
    max_drawdown: float = 0.0
    turnover: float = 0.0
    hit_rate: float = 0.0         # IC>0 占比
    long_short_spread: float = 0.0  # 多空收益差（年化）
    ic_series: list = field(default_factory=list)
    quantile_returns: dict = field(default_factory=dict)
    cumulative_returns: list = field(default_factory=list)
    n_stocks_period: list = field(default_factory=list)
    n_dates: int = 0
    error: Optional[str] = None


class IndependentBacktestEngine:
    """
    独立回测引擎 — 不依赖 Qlib，纯 pandas 实现
    支持任意因子表达式（通过 pandas eval 计算因子值）
    """

    def __init__(self, config: BacktestConfig = None):
        self.config = config or BacktestConfig()

    # ── 因子值计算 ──────────────────────────────────────

    def compute_factor(
        self,
        df: pd.DataFrame,
        expression: str,
        factor_name: str = "alpha",
    ) -> pd.DataFrame:
        """
        计算因子值

        Args:
            df: 包含 columns=[date, instrument, open, high, low, close, volume, amount, ...]
            expression: 因子表达式（可用列名 + pandas 操作，如 close.pct_change() 或 close/shift(close,1)-1）
            factor_name: 因子列名

        Returns:
            添加了因子值的 DataFrame
        """
        df = df.copy()
        df["date"] = pd.to_datetime(df["date"])

        # 按 instrument 分组计算（避免跨股票数据污染）
        frames = []
        for inst in df["instrument"].unique():
            sub = df[df["instrument"] == inst].sort_values("date").copy()

            # 构建局部变量：所有列为 pandas Series（保留 .shift()/.rolling() 等方法）
            local_vars = {}
            for col in sub.columns:
                if col not in ("date", "instrument"):
                    local_vars[col] = sub[col].reset_index(drop=True)

            # 构建辅助函数（全部返回 pandas Series，保持方法链兼容）
            def _make_series(arr):
                return pd.Series(np.asarray(arr, dtype=float))

            local_vars["shift"] = lambda s, n: pd.Series(s).shift(n)
            local_vars["rolling_mean"] = lambda s, w: pd.Series(s).rolling(w, min_periods=1).mean()
            local_vars["rolling_std"] = lambda s, w: pd.Series(s).rolling(w, min_periods=1).std()
            local_vars["rolling_sum"] = lambda s, w: pd.Series(s).rolling(w, min_periods=1).sum()
            local_vars["rolling_max"] = lambda s, w: pd.Series(s).rolling(w, min_periods=1).max()
            local_vars["rolling_min"] = lambda s, w: pd.Series(s).rolling(w, min_periods=1).min()
            local_vars["rolling_corr"] = lambda s1, s2, w: pd.Series(s1).rolling(w).corr(pd.Series(s2))
            local_vars["rank"] = lambda s: pd.Series(s).rank(pct=True)
            local_vars["log"] = np.log
            local_vars["abs"] = np.abs
            local_vars["sqrt"] = np.sqrt
            local_vars["sign"] = np.sign
            local_vars["mean"] = lambda s: pd.Series(s).mean()

            try:
                # 对每列做滚动特征准备（如 ret_5d_lag 等）
                for col_name in list(sub.columns):
                    parts = col_name.split("_lag")
                    if len(parts) == 2 and parts[1].isdigit():
                        base = parts[0]
                        lag_n = int(parts[1])
                        if base in sub.columns:
                            local_vars[col_name] = sub[base].shift(lag_n).reset_index(drop=True)

                factor_vals = eval(expression, {"__builtins__": {}}, {
                    **{c: sub[c].reset_index(drop=True) for c in sub.columns},
                    **local_vars,
                    "np": np,
                    "pd": pd,
                })
                # 统一转为 numpy array 存回 DataFrame
                sub[factor_name] = np.asarray(factor_vals, dtype=float)
                frames.append(sub)
            except Exception as e:
                logger.warning(f"计算 {inst} 因子失败: {e}")
                sub[factor_name] = np.nan
                frames.append(sub)

        result = pd.concat(frames, ignore_index=True)
        result[factor_name] = pd.to_numeric(result[factor_name], errors="coerce")
        return result

    # ── IC 计算 ─────────────────────────────────────────

    def compute_ic(
        self,
        df: pd.DataFrame,
        factor_col: str = "alpha",
        forward_period: int = 1,
        min_stocks_per_day: int = 3,
    ) -> pd.DataFrame:
        """
        计算每期的 Rank IC

        Returns DataFrame with columns: date, ic, rank_ic, n_stocks
        """
        df = df.copy()
        df["date"] = pd.to_datetime(df["date"])

        # 计算未来收益：按 instrument 分组，计算 forward return
        fwd_rets = []
        for inst in df["instrument"].unique():
            mask = df["instrument"] == inst
            sub = df.loc[mask].sort_values("date")
            # 在排序后的子集上计算，保留原始 index
            sub_fwd = sub["close"].pct_change(forward_period).shift(-forward_period)
            fwd_rets.append(sub_fwd)
        df["fwd_ret"] = pd.concat(fwd_rets)

        ic_records = []
        for date in sorted(df["date"].unique()):
            sub = df[df["date"] == date].dropna(subset=[factor_col, "fwd_ret"])
            if len(sub) < min_stocks_per_day:
                continue

            # Pearson IC
            ic, _ = stats.pearsonr(sub[factor_col], sub["fwd_ret"])

            # Rank IC (Spearman)
            rank_ic, _ = stats.spearmanr(sub[factor_col], sub["fwd_ret"])

            ic_records.append({
                "date": date,
                "ic": ic if not np.isnan(ic) else 0,
                "rank_ic": rank_ic if not np.isnan(rank_ic) else 0,
                "n_stocks": len(sub),
            })

        return pd.DataFrame(ic_records)

    # ── 分层回测 ────────────────────────────────────────

    def compute_quantile_returns(
        self,
        df: pd.DataFrame,
        factor_col: str = "alpha",
        n_quantiles: int = 5,
        forward_period: int = 1,
    ) -> pd.DataFrame:
        """
        分层回测：按因子值分 n 组，计算每组未来收益

        Returns DataFrame: date, quantile_1, ..., quantile_n, spread
        """
        df = df.copy()
        df["date"] = pd.to_datetime(df["date"])

        # 计算未来收益（按 instrument 分组，保留原始 index 对齐）
        fwd_rets = []
        for inst in df["instrument"].unique():
            mask = df["instrument"] == inst
            sub = df.loc[mask].sort_values("date")
            sub_fwd = sub["close"].pct_change(forward_period).shift(-forward_period)
            fwd_rets.append(sub_fwd)
        df["fwd_ret"] = pd.concat(fwd_rets)

        quantile_records = []
        for date in sorted(df["date"].unique()):
            sub = df[df["date"] == date].dropna(subset=[factor_col, "fwd_ret"])
            if len(sub) < n_quantiles * 3:
                continue

            sub["quantile"] = pd.qcut(
                sub[factor_col], n_quantiles, labels=False, duplicates="drop"
            ) + 1

            record = {"date": date, "n_stocks": len(sub)}
            for q in range(1, n_quantiles + 1):
                q_ret = sub[sub["quantile"] == q]["fwd_ret"].mean()
                record[f"q{q}"] = q_ret if not np.isnan(q_ret) else 0

            # 多空收益差
            if f"q{n_quantiles}" in record and "q1" in record:
                record["spread"] = record[f"q{n_quantiles}"] - record["q1"]
            else:
                record["spread"] = 0

            quantile_records.append(record)

        return pd.DataFrame(quantile_records)

    # ── 完整因子回测 ────────────────────────────────────

    def run_factor_backtest(
        self,
        df: pd.DataFrame,
        factor_name: str,
        factor_expression: str,
        forward_period: int = 1,
    ) -> FactorResult:
        """
        对单个因子执行完整回测

        Args:
            df: 行情数据 DataFrame
            factor_name: 因子名称
            factor_expression: 因子表达式
            forward_period: 调仓周期（天）

        Returns:
            FactorResult
        """
        logger.info(f"开始回测因子: {factor_name}")

        try:
            # Step 1: 计算因子值
            df_with_factor = self.compute_factor(df, factor_expression, factor_name)
            valid = df_with_factor.dropna(subset=[factor_name])
            if len(valid) < 100:
                return FactorResult(
                    factor_name=factor_name,
                    factor_expression=factor_expression,
                    error=f"有效因子值太少 ({len(valid)})",
                )

            # Step 2: 计算 IC
            ic_df = self.compute_ic(df_with_factor, factor_name, forward_period)
            ic_df = ic_df.dropna(subset=["ic"])
            if len(ic_df) < 10:
                return FactorResult(
                    factor_name=factor_name,
                    factor_expression=factor_expression,
                    error=f"有效IC期数太少 ({len(ic_df)})",
                )

            ic_mean = ic_df["ic"].mean()
            ic_std = ic_df["ic"].std()
            icir = ic_mean / ic_std if ic_std > 0 else 0
            rank_ic_mean = ic_df["rank_ic"].mean()
            rank_icir = rank_ic_mean / ic_df["rank_ic"].std() if ic_df["rank_ic"].std() > 0 else 0
            hit_rate = (ic_df["ic"] > 0).mean()

            # Step 3: 分层回测
            quantile_df = self.compute_quantile_returns(
                df_with_factor, factor_name, self.config.n_quantiles, forward_period
            )

            # Step 4: 计算绩效指标
            if not quantile_df.empty and "spread" in quantile_df.columns:
                spread_series = quantile_df["spread"].dropna()

                # Sharpe (年化)
                sharpe = (
                    spread_series.mean() / spread_series.std() * np.sqrt(252 / forward_period)
                    if spread_series.std() > 0 else 0
                )

                # 年化收益
                cumulative = (1 + spread_series).cumprod()
                annual_return = (
                    cumulative.iloc[-1] ** (252 / forward_period / len(spread_series)) - 1
                    if len(spread_series) > 0 else 0
                )

                # 最大回撤
                cummax = cumulative.cummax()
                drawdown = (cumulative - cummax) / cummax
                max_drawdown = drawdown.min()

                # 多空收益差（日均 × 252）
                long_short_spread = spread_series.mean() * 252 / forward_period

                # 累计收益序列
                cum_returns = cumulative.tolist()

                # 分层收益
                quantile_returns = {}
                for q in range(1, self.config.n_quantiles + 1):
                    col = f"q{q}"
                    if col in quantile_df.columns:
                        q_series = quantile_df[col].dropna()
                        quantile_returns[col] = {
                            "mean_daily": float(q_series.mean()),
                            "annual_return": float(q_series.mean() * 252 / forward_period),
                            "sharpe": float(
                                q_series.mean() / q_series.std() * np.sqrt(252 / forward_period)
                                if q_series.std() > 0 else 0
                            ),
                        }
            else:
                sharpe = 0
                annual_return = 0
                max_drawdown = 0
                long_short_spread = 0
                cum_returns = []
                quantile_returns = {}

            # Step 5: 计算换手率
            turnover = self._estimate_turnover(df_with_factor, factor_name)

            return FactorResult(
                factor_name=factor_name,
                factor_expression=factor_expression,
                ic_mean=float(ic_mean),
                ic_std=float(ic_std),
                icir=float(icir),
                rank_ic_mean=float(rank_ic_mean),
                rank_icir=float(rank_icir),
                sharpe=float(sharpe),
                annual_return=float(annual_return),
                max_drawdown=float(max_drawdown),
                turnover=float(turnover),
                hit_rate=float(hit_rate),
                long_short_spread=float(long_short_spread),
                ic_series=ic_df["ic"].tolist(),
                quantile_returns=quantile_returns,
                cumulative_returns=cum_returns,
                n_stocks_period=ic_df["n_stocks"].tolist(),
                n_dates=len(ic_df),
            )

        except Exception as e:
            logger.error(f"因子 {factor_name} 回测失败: {e}")
            return FactorResult(
                factor_name=factor_name,
                factor_expression=factor_expression,
                error=str(e),
            )

    def _estimate_turnover(self, df: pd.DataFrame, factor_col: str) -> float:
        """估算因子换手率（基于相邻期因子排名的变化）"""
        df = df.copy()
        df["date"] = pd.to_datetime(df["date"])
        dates = sorted(df["date"].unique())

        turnovers = []
        for i in range(1, len(dates)):
            prev = df[df["date"] == dates[i - 1]].dropna(subset=[factor_col])
            curr = df[df["date"] == dates[i]].dropna(subset=[factor_col])
            common = set(prev["instrument"]) & set(curr["instrument"])
            if len(common) < 20:
                continue

            prev_rank = prev[prev["instrument"].isin(common)].set_index("instrument")[factor_col].rank(pct=True)
            curr_rank = curr[curr["instrument"].isin(common)].set_index("instrument")[factor_col].rank(pct=True)

            # 计算排名变化的均值（归一化）
            rank_change = (prev_rank - curr_rank).abs().mean()
            turnovers.append(rank_change)

        return float(np.mean(turnovers)) if turnovers else 0.5

    # ── 批量因子回测 ────────────────────────────────────

    def run_batch_backtest(
        self,
        df: pd.DataFrame,
        factors: list[dict],
        forward_period: int = 1,
    ) -> list[FactorResult]:
        """
        批量回测多个因子

        Args:
            df: 行情数据
            factors: [{"name": "...", "expression": "..."}, ...]
            forward_period: 调仓周期

        Returns:
            list of FactorResult
        """
        results = []
        for f in factors:
            result = self.run_factor_backtest(
                df=df,
                factor_name=f.get("name", f"factor_{len(results)}"),
                factor_expression=f["expression"],
                forward_period=forward_period,
            )
            results.append(result)
            logger.info(
                f"  {result.factor_name}: "
                f"IC={result.ic_mean:.4f}, ICIR={result.icir:.2f}, "
                f"Sharpe={result.sharpe:.2f}, Turnover={result.turnover:.2f}"
            )
        return results


def factor_result_to_dict(r: FactorResult) -> dict:
    """将 FactorResult 转为可序列化的 dict"""
    return {
        "factor_name": r.factor_name,
        "factor_expression": r.factor_expression,
        "ic_mean": r.ic_mean,
        "ic_std": r.ic_std,
        "icir": r.icir,
        "rank_ic_mean": r.rank_ic_mean,
        "rank_icir": r.rank_icir,
        "sharpe": r.sharpe,
        "annual_return": r.annual_return,
        "max_drawdown": r.max_drawdown,
        "turnover": r.turnover,
        "hit_rate": r.hit_rate,
        "long_short_spread": r.long_short_spread,
        "ic_series": r.ic_series[-100:],  # 最近100期
        "quantile_returns": r.quantile_returns,
        "cumulative_returns": r.cumulative_returns[-500:],  # 最近500期
        "n_stocks_period": r.n_stocks_period[-100:],
        "n_dates": r.n_dates,
        "error": r.error,
    }
