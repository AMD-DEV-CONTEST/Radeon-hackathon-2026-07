"""
data_client.py — RD-Agent 数据客户端适配层

对接 env-openbb 数据微服务 (http://127.0.0.1:8001)，实现：
- 原有数据请求逻辑完全保留，仅请求地址改为 openbb_service
- 入参、返回数据格式无改动，RD-Agent 无感知双数据源切换
- 服务不可用时自动 fallback 到本地数据管线

红线：不修改 RD-Agent 内核源码，不在此文件新增数据清洗/Tushare 调用代码。
"""
import os
import sys
from pathlib import Path
from typing import Optional
import pandas as pd
import httpx
from loguru import logger

_project_root = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_project_root))


class DataClient:
    """
    统一数据客户端，优先通过 env-openbb 微服务获取数据，
    不可用时 fallback 到本地 DataPipeline。
    """

    OPENBB_SERVICE_URL = os.environ.get("OPENBB_SERVICE_URL", "http://127.0.0.1:8001")

    def __init__(self, service_url: Optional[str] = None):
        self.service_url = (service_url or self.OPENBB_SERVICE_URL).rstrip("/")
        self._http_client = httpx.Client(timeout=httpx.Timeout(60.0))
        self._service_available = None  # None = 未检测

    def check_service(self) -> bool:
        """检测 openbb_service 是否可用"""
        try:
            resp = self._http_client.get(f"{self.service_url}/health", timeout=3)
            if resp.status_code == 200:
                data = resp.json()
                if data.get("status") == "ok":
                    self._service_available = True
                    return True
        except Exception:
            pass
        self._service_available = False
        return False

    def get_qlib_standard_data(
        self,
        stock_pool: str = "000300.SH",
        start_date: str = "20200102",
        end_date: str = "20260720",
        fields: Optional[list[str]] = None,
    ) -> pd.DataFrame:
        """
        通过 openbb_service 获取标准化数据。

        参数：
        - stock_pool: 股票池标识
        - start_date / end_date: YYYYMMDD 格式
        - fields: 字段列表

        返回：Qlib 标准格式 DataFrame (date, instrument, [fields...])
        """
        if fields is None:
            fields = ["open", "close", "volume"]

        # 尝试调用 openbb_service
        if self._service_available is not False:
            try:
                resp = self._http_client.post(
                    f"{self.service_url}/get_qlib_standard_data",
                    json={
                        "stock_pool": stock_pool,
                        "start_date": start_date,
                        "end_date": end_date,
                        "fields": fields,
                    },
                    timeout=30,
                )
                if resp.status_code == 200:
                    result = resp.json()
                    if result.get("success") and result.get("data"):
                        df = pd.DataFrame(result["data"])
                        if "date" in df.columns:
                            df["date"] = pd.to_datetime(df["date"])
                        logger.info(
                            f"openbb_service 返回 {len(df)} 条数据 "
                            f"(source={result.get('source', 'unknown')})"
                        )
                        return df
                    else:
                        logger.warning(f"openbb_service 返回空数据: {result.get('message', '')}")
                else:
                    logger.warning(f"openbb_service 返回错误: {resp.status_code}")
            except httpx.ConnectError:
                logger.warning("openbb_service 连接失败，fallback 本地数据管线")
                self._service_available = False
            except Exception as e:
                logger.warning(f"openbb_service 调用异常: {e}")
                self._service_available = False
        else:
            logger.info("openbb_service 不可用，使用本地数据管线")

        # Fallback：本地数据管线
        return self._fallback_local(stock_pool, start_date, end_date, fields)

    def _fallback_local(
        self,
        stock_pool: str,
        start_date: str,
        end_date: str,
        fields: list[str],
    ) -> pd.DataFrame:
        """本地数据管线 fallback"""
        from backend.data_svc import OpenBBDataProvider, DataCleaner, FeatureEngineering

        # 解析 stock_pool → symbols
        symbols = self._resolve_stock_pool(stock_pool)

        # 规范化日期
        start = f"{start_date[:4]}-{start_date[4:6]}-{start_date[6:8]}"
        end = f"{end_date[:4]}-{end_date[4:6]}-{end_date[6:8]}"

        provider = OpenBBDataProvider()
        cleaner = DataCleaner()
        fe = FeatureEngineering()

        daily = provider.get_a_share_daily(symbols, start, end)
        daily = cleaner.ensure_forward_adjust(daily)
        daily = cleaner.remove_new_stocks(daily)
        daily = fe.add_technical_indicators(daily)

        logger.info(f"本地数据管线返回 {len(daily)} 条数据")
        return daily

    def _resolve_stock_pool(self, stock_pool: str) -> list[str]:
        """解析股票池为 Qlib 格式列表"""
        if stock_pool.lower() == "all":
            from backend.data_svc import QlibDataExporter
            features_dir = Path("db/qlib_data/features")
            if features_dir.exists():
                return [d.name for d in features_dir.iterdir() if d.is_dir()]
            return []

        if stock_pool.endswith((".SH", ".SZ")):
            # 指数 → 尝试获取成分股（简化：返回常见成分股）
            if stock_pool == "000300.SH":
                return [
                    "sh600519", "sz000858", "sh600036", "sz000001", "sh601318",
                    "sh600900", "sh601166", "sh600030", "sh600276", "sz002415",
                    "sh600000", "sz000002", "sh601398", "sh601288", "sh600050",
                    "sh600809", "sz000333", "sh600104", "sh600887", "sz002594",
                ]
            elif stock_pool == "000905.SH":
                return [
                    "sz002230", "sz300750", "sh603259", "sz002475", "sz300059",
                    "sh688981", "sz002371", "sz300124", "sh688012", "sz300274",
                ]

        if "," in stock_pool:
            return [s.strip() for s in stock_pool.split(",")]

        return [stock_pool]


# 全局单例
data_client = DataClient()
