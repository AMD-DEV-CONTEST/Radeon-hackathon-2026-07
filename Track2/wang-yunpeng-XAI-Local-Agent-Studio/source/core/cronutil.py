#!/usr/bin/env python3
"""Best-effort cron 解析与下次触发时间计算（零外部依赖）。

支持标准 5 段 cron：分 时 日 月 周
- `*` 任意
- `a-b` 区间
- `a,b,c` 列表
- `*/n` 或 `a-b/n` 步长
- 周日可用 0 或 7
dom 与 dow 为标准的「OR」关系：两者都非 `*` 时，命中任一即触发；
任一为 `*` 时由另一字段单独决定。

时区：优先使用 zoneinfo（系统自带 tzdata）；失败时退化为服务器本地时区，
仍可正确计算相对时间，仅绝对时刻按本地解释。
"""
from __future__ import annotations
from datetime import datetime, timedelta
from typing import Optional, Set


def _parse_field(field: str, min_val: int, max_val: int) -> Set[int]:
    vals: Set[int] = set()
    for part in field.split(","):
        part = part.strip()
        if not part:
            continue
        step = 1
        if "/" in part:
            base, step_s = part.split("/", 1)
            step = int(step_s)
        else:
            base = part
        if base == "*":
            a, b = min_val, max_val
        elif "-" in base:
            a_s, b_s = base.split("-", 1)
            a, b = int(a_s), int(b_s)
        else:
            a = b = int(base)
        for v in range(a, b + 1, step):
            if min_val <= v <= max_val:
                vals.add(v)
    return vals


def _dow_normalize(value: int) -> int:
    """cron dow: 0=周日..6=周六（7 也表周日）→ 归一到 0..6。"""
    return value % 7


def next_run(cron_expr: str, tz_name: Optional[str] = None,
             after: Optional[datetime] = None) -> Optional[datetime]:
    parts = (cron_expr or "").strip().split()
    if len(parts) != 5:
        return None
    try:
        mins = _parse_field(parts[0], 0, 59)
        hrs = _parse_field(parts[1], 0, 23)
        doms = _parse_field(parts[2], 1, 31)
        mons = _parse_field(parts[3], 1, 12)
        dows = {_dow_normalize(int(x)) for x in _parse_field(parts[4], 0, 7)}
    except Exception:
        return None

    tz = None
    if tz_name:
        try:
            from zoneinfo import ZoneInfo
            tz = ZoneInfo(tz_name)
        except Exception:
            tz = None

    if after is None:
        after = datetime.now(tz) if tz else datetime.now()
    elif tz and after.tzinfo is None:
        after = after.replace(tzinfo=tz)

    dom_star = parts[2].strip() == "*"
    dow_star = parts[4].strip() == "*"

    start = after + timedelta(minutes=1)
    start = start.replace(second=0, microsecond=0)
    limit = start + timedelta(days=366 * 4)

    cur = start
    while cur <= limit:
        if cur.month in mons:
            if dom_star and dow_star:
                day_ok = True
            elif dom_star:
                py_dow = (cur.weekday() + 1) % 7  # Mon=0..Sun=6 → Sun=0..Sat=6
                day_ok = py_dow in dows
            elif dow_star:
                day_ok = cur.day in doms
            else:
                py_dow = (cur.weekday() + 1) % 7
                day_ok = (cur.day in doms) or (py_dow in dows)
            if day_ok and cur.hour in hrs and cur.minute in mins:
                return cur
        cur += timedelta(minutes=1)
    return None


def humanize_next(cron_expr: str, tz_name: Optional[str] = None,
                  after: Optional[datetime] = None) -> str:
    """返回人类可读的 next_run 字符串；无法解析时回退展示原始 cron。"""
    dt = next_run(cron_expr, tz_name, after)
    if dt is None:
        return cron_expr or "（未设置）"
    try:
        return dt.strftime("%Y-%m-%d %H:%M")
    except Exception:
        return str(dt)
