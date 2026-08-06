from __future__ import annotations

from collections.abc import Iterable
import math
import re
import time
from typing import Any
from urllib.parse import urlsplit

import requests


TENCENT_SOURCE_NAME = "腾讯证券公开行情"
_A_SHARE_CODE_RE = re.compile(r"^[0-9]{6}$")


class TencentMarketDataError(RuntimeError):
    """Raised when Tencent market data is unavailable or malformed."""


class TencentMarketDataClient:
    _BOARD_URL = "https://proxy.finance.qq.com/cgi/cgi-bin/rank/hs/getBoardRankList"
    _QUOTE_URL = "https://qt.gtimg.cn/q={symbol}"
    _HISTORY_URL = "https://web.ifzq.gtimg.cn/appstock/app/fqkline/get"
    _PAGE_SIZE = 200
    _MAX_COLLECTION_PASSES = 2
    _MAX_ATTEMPTS = 3
    _REQUEST_TIMEOUT = (5, 15)
    _HEADERS = {
        "Accept": "application/json, text/plain, */*",
        "Referer": "https://stockapp.finance.qq.com/",
        "User-Agent": (
            "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
        ),
    }

    def __init__(self) -> None:
        self._session = self._new_session()
        self._retry_count = 0
        self._request_count = 0
        self._hosts_used: set[str] = set()

    def close(self) -> None:
        self._session.close()

    def __enter__(self) -> "TencentMarketDataClient":
        return self

    def __exit__(self, exc_type: Any, exc: Any, traceback: Any) -> None:
        del exc_type, exc, traceback
        self.close()

    def stock_rows(self) -> list[dict[str, Any]]:
        unique: dict[str, dict[str, Any]] = {}
        expected_total = 0
        for collection_pass in range(1, self._MAX_COLLECTION_PASSES + 1):
            first_rows, current_total = self._board_page(offset=0)
            if current_total < 1 or not first_rows:
                raise TencentMarketDataError("腾讯证券 A 股行情返回空数据")
            expected_total = max(expected_total, current_total)
            self._merge_board_rows(unique, first_rows)
            page_count = math.ceil(current_total / self._PAGE_SIZE)
            for page in range(2, page_count + 1):
                offset = (page - 1) * self._PAGE_SIZE
                rows, page_total = self._board_page(offset=offset)
                expected_total = max(expected_total, page_total)
                if not rows:
                    raise TencentMarketDataError(f"腾讯证券 A 股行情 offset={offset} 返回空数据")
                self._merge_board_rows(unique, rows)
            if len(unique) == expected_total:
                return list(unique.values())
            if collection_pass < self._MAX_COLLECTION_PASSES:
                time.sleep(0.5)
        raise TencentMarketDataError(
            f"腾讯证券行情分页不完整：接口声明 {expected_total} 条，实际获得 {len(unique)} 条"
        )

    def quote(self, code: str) -> dict[str, Any]:
        symbol = a_share_symbol(code)
        text = self._request_text(self._QUOTE_URL.format(symbol=symbol), encoding="gb18030")
        marker = f'v_{symbol}="'
        start = text.find(marker)
        if start < 0:
            raise TencentMarketDataError(f"腾讯证券未返回 {code} 行情")
        start += len(marker)
        end = text.find('"', start)
        fields = text[start:end].split("~") if end >= start else []
        if len(fields) < 46 or fields[2] != code:
            raise TencentMarketDataError(f"腾讯证券 {code} 行情字段不完整")
        name = fields[1].strip()
        if not name:
            raise TencentMarketDataError(f"腾讯证券 {code} 行情缺少证券名称")
        return {
            "code": code,
            "symbol": symbol,
            "name": name,
            "exchange": _exchange_name(symbol),
            "price": _number(fields[3]),
            "previous_close": _number(fields[4]),
            "open": _number(fields[5]),
            "volume_lots": _number(fields[6]),
            "quote_time": fields[30].strip(),
            "change": _number(fields[31]),
            "change_pct": _number(fields[32]),
            "high": _number(fields[33]),
            "low": _number(fields[34]),
            "turnover_cny": _scaled_number(fields[37], 10_000),
            "turnover_rate_pct": _number(fields[38]),
            "dynamic_pe": _number(fields[39]),
            "amplitude_pct": _number(fields[43]),
            "circulating_market_cap_cny": _scaled_number(fields[44], 100_000_000),
            "market_cap_cny": _scaled_number(fields[45], 100_000_000),
        }

    def history(self, code: str, *, count: int, adjustment: str = "qfq") -> list[dict[str, Any]]:
        if count < 1 or count > 1000:
            raise ValueError("Tencent history count must be between 1 and 1000")
        if adjustment not in {"qfq", "none"}:
            raise ValueError("Tencent history adjustment must be qfq or none")
        symbol = a_share_symbol(code)
        fq = "qfq" if adjustment == "qfq" else ""
        payload = self._request_json(
            self._HISTORY_URL,
            params={"param": f"{symbol},day,,,{count},{fq}"},
        )
        data = payload.get("data") if isinstance(payload, dict) else None
        symbol_data = data.get(symbol) if isinstance(data, dict) else None
        if not isinstance(symbol_data, dict):
            raise TencentMarketDataError(f"腾讯证券 {code} 历史行情缺少 data.{symbol}")
        raw_rows = symbol_data.get("qfqday") if adjustment == "qfq" else symbol_data.get("day")
        if not isinstance(raw_rows, list):
            raw_rows = symbol_data.get("day")
        rows: list[dict[str, Any]] = []
        for raw in raw_rows if isinstance(raw_rows, list) else []:
            if not isinstance(raw, list) or len(raw) < 6:
                continue
            close = _number(raw[2])
            if close is None:
                continue
            rows.append(
                {
                    "date": str(raw[0]),
                    "open": _number(raw[1]),
                    "close": close,
                    "high": _number(raw[3]),
                    "low": _number(raw[4]),
                    "volume": _number(raw[5]),
                }
            )
        if not rows:
            raise TencentMarketDataError(f"腾讯证券 {code} 历史行情为空")
        return rows[-count:]

    def diagnostics(self) -> dict[str, Any]:
        return {
            "provider": "tencent_finance",
            "hosts_used": sorted(self._hosts_used),
            "retry_count": self._retry_count,
            "requests_completed": self._request_count,
        }

    def _board_page(self, *, offset: int) -> tuple[list[dict[str, Any]], int]:
        payload = self._request_json(
            self._BOARD_URL,
            params={
                "_appver": "11.17.0",
                "board_code": "aStock",
                "sort_type": "price",
                "direct": "down",
                "offset": str(offset),
                "count": str(self._PAGE_SIZE),
            },
        )
        if payload.get("code") != 0:
            raise TencentMarketDataError(f"腾讯证券 offset={offset} 响应状态异常")
        data = payload.get("data")
        rows = data.get("rank_list") if isinstance(data, dict) else None
        total = int(data.get("total") or 0) if isinstance(data, dict) else 0
        if not isinstance(rows, list):
            raise TencentMarketDataError(f"腾讯证券 offset={offset} rank_list 格式异常")
        return [row for row in rows if isinstance(row, dict)], total

    def _merge_board_rows(self, target: dict[str, dict[str, Any]], rows: Iterable[dict[str, Any]]) -> None:
        for raw in rows:
            raw_code = str(raw.get("code") or "").strip()
            code = raw_code[2:] if raw_code[:2] in {"sh", "sz", "bj"} else raw_code
            if not _A_SHARE_CODE_RE.fullmatch(code):
                raise TencentMarketDataError("腾讯证券行情数据包含无效股票代码")
            turnover = _number(raw.get("turnover"))
            target[code] = {
                "code": code,
                "name": str(raw.get("name") or "").strip(),
                "price": _number(raw.get("zxj")),
                "change_pct": _number(raw.get("zdf")),
                "turnover_cny": turnover * 10_000 if turnover is not None else None,
            }

    def _request_json(self, url: str, *, params: dict[str, str]) -> dict[str, Any]:
        return self._request(url, params=params, parse_json=True)

    def _request_text(self, url: str, *, encoding: str) -> str:
        return self._request(url, params=None, parse_json=False, encoding=encoding)

    def _request(
        self,
        url: str,
        *,
        params: dict[str, str] | None,
        parse_json: bool,
        encoding: str = "utf-8",
    ) -> Any:
        failures: list[str] = []
        host = urlsplit(url).hostname or url
        for attempt in range(self._MAX_ATTEMPTS):
            try:
                response = self._session.get(url, params=params, timeout=self._REQUEST_TIMEOUT)
                response.raise_for_status()
                value = response.json() if parse_json else response.content.decode(encoding, errors="strict")
                self._retry_count += attempt
                self._request_count += 1
                self._hosts_used.add(host)
                return value
            except (requests.RequestException, UnicodeError, ValueError, TypeError) as exc:
                failures.append(type(exc).__name__)
                self._reset_session()
                if attempt + 1 < self._MAX_ATTEMPTS:
                    time.sleep(0.25 * (2**attempt))
        raise TencentMarketDataError(f"腾讯证券 {host} 请求失败（{', '.join(failures)}）")

    def _new_session(self) -> requests.Session:
        session = requests.Session()
        session.headers.update(self._HEADERS)
        return session

    def _reset_session(self) -> None:
        self._session.close()
        self._session = self._new_session()


def a_share_symbol(code: str) -> str:
    normalized = str(code or "").strip()
    if not _A_SHARE_CODE_RE.fullmatch(normalized):
        raise ValueError("code must be a six-digit A-share code")
    if normalized.startswith(("4", "8")):
        return f"bj{normalized}"
    if normalized.startswith(("5", "6", "9")):
        return f"sh{normalized}"
    return f"sz{normalized}"


def _exchange_name(symbol: str) -> str:
    return {"sh": "上海证券交易所", "sz": "深圳证券交易所", "bj": "北京证券交易所"}[symbol[:2]]


def _scaled_number(value: Any, scale: int) -> float | int | None:
    parsed = _number(value)
    return _number(parsed * scale) if parsed is not None else None


def _number(value: Any) -> float | int | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number):
        return None
    return int(number) if number.is_integer() else round(number, 4)
