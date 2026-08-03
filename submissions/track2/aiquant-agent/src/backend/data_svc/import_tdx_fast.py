"""
快速批量导入通达信日线数据到 Qlib 格式（两阶段版）

Phase 1: 多进程解析CSV → 返回 (instrument, records) 元组
Phase 2: 多进程写入 Qlib .bin 文件（含正确 start_index header）

用法:
  python backend/data_svc/import_tdx_fast.py
  python backend/data_svc/import_tdx_fast.py --target rdagent
"""
import os
import sys
import json
from pathlib import Path
import argparse
import numpy as np
import pandas as pd
from datetime import datetime
from multiprocessing import Pool, cpu_count
from loguru import logger

_project_root = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_project_root))

DATA_SOURCE = Path("/Users/gaochangcheng/Desktop/股票数据/沪深京个股日线历史数据(前复权)")


def _code_to_qlib_instrument(code: str) -> str:
    code = code.strip()
    if code.startswith(("sh", "sz", "SH", "SZ")):
        return code.lower()
    if code.startswith(("6", "9")):
        return f"sh{code}"
    elif code.startswith(("0", "3", "2", "4", "8")):
        return f"sz{code}"
    return f"sh{code}"


# ── Phase 1: 解析 CSV ──────────────────────────────────

def parse_one_file(args):
    """返回 (instrument, records_dict) 或 None。records_dict: {date: [open,high,low,close,volume,amount]}"""
    csv_path, start_date = args
    try:
        with open(csv_path, "rb") as f:
            raw = f.read(100)
        encoding = "gbk"
        try:
            raw.decode("gbk")
        except UnicodeDecodeError:
            encoding = "utf-8"

        with open(csv_path, "r", encoding=encoding) as f:
            lines = f.readlines()

        lines = [l.rstrip("\n").rstrip("\r") for l in lines]
        lines = [l for l in lines if l.strip() and not l.startswith("#")]
        if len(lines) < 3:
            return None

        header_parts = lines[0].split()
        if not header_parts:
            return None
        code = header_parts[0]
        instrument = _code_to_qlib_instrument(code)

        records = {}  # date_str -> [open, high, low, close, volume, amount]
        for line in lines[2:]:
            parts = line.split(",")
            if len(parts) < 7:
                continue
            try:
                date_str = parts[0].strip()
                if len(date_str) != 8:
                    continue
                date = f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:8]}"
                if start_date and date < start_date:
                    continue
                close = float(parts[4])
                high = float(parts[2])
                if close <= 0 or high <= 0:
                    continue
                records[date] = [
                    float(parts[1]), high, float(parts[3]), close,
                    float(parts[5]), float(parts[6]),
                ]
            except (ValueError, IndexError):
                continue
        if not records:
            return None
        return (instrument, records)
    except Exception:
        return None


# ── Phase 2: 写入 Qlib .bin ─────────────────────────────

def write_qlib_bin(args):
    """写入单只股票的 Qlib .bin 文件。args = (instrument, records, date_to_idx, features_dir, freq)"""
    instrument, records, date_to_idx, features_dir, freq = args
    try:
        inst_dir = features_dir / instrument.lower()
        inst_dir.mkdir(parents=True, exist_ok=True)

        # 按日期排序
        sorted_dates = sorted(records.keys())
        n = len(sorted_dates)

        # 构建各字段数组
        fields = {
            "open": np.zeros(n, dtype=np.float32),
            "high": np.zeros(n, dtype=np.float32),
            "low": np.zeros(n, dtype=np.float32),
            "close": np.zeros(n, dtype=np.float32),
            "volume": np.zeros(n, dtype=np.float32),
            "amount": np.zeros(n, dtype=np.float32),
            "factor": np.ones(n, dtype=np.float32),
        }

        for i, d in enumerate(sorted_dates):
            vals = records[d]
            fields["open"][i] = vals[0]
            fields["high"][i] = vals[1]
            fields["low"][i] = vals[2]
            fields["close"][i] = vals[3]
            fields["volume"][i] = vals[4]
            fields["amount"][i] = vals[5]

        # 写入 .bin 文件
        first_date = sorted_dates[0]
        start_idx = date_to_idx.get(first_date, 0)

        for field_name, arr in fields.items():
            bin_path = inst_dir / f"{field_name}.{freq}.bin"
            data = np.concatenate([[np.float32(start_idx)], arr]).astype("<f")
            data.tofile(bin_path)

        return (instrument, sorted_dates[0], sorted_dates[-1], n)
    except Exception as e:
        logger.warning(f"写入 {instrument} 失败: {e}")
        return None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--target", choices=["project", "rdagent"], default="project")
    parser.add_argument("--start-date", default="2020-01-01")
    parser.add_argument("--workers", type=int, default=None)
    args = parser.parse_args()

    # 目标目录
    if args.target == "rdagent":
        target_dir = Path(os.path.expanduser("~/.qlib/qlib_data/cn_data"))
    else:
        from backend.shared.config import settings
        target_dir = settings.db_dir

    target_dir = Path(target_dir)
    features_dir = target_dir / "features"
    instruments_dir = target_dir / "instruments"
    calendars_dir = target_dir / "calendars"

    import shutil
    for d in [features_dir, instruments_dir, calendars_dir]:
        if d.exists():
            shutil.rmtree(d)
        d.mkdir(parents=True, exist_ok=True)

    csv_files = sorted(DATA_SOURCE.glob("*.csv"))
    workers = args.workers or min(cpu_count(), 8)
    freq = "day"

    # ═══ Phase 1: 多进程解析 CSV ═══
    logger.info(f"Phase 1: 解析 {len(csv_files)} 个 CSV ({workers} 进程)...")
    work_items = [(f, args.start_date) for f in csv_files]

    parsed = []  # list of (instrument, records_dict)
    with Pool(workers) as pool:
        for i, r in enumerate(pool.imap_unordered(parse_one_file, work_items, chunksize=50)):
            if r is not None:
                parsed.append(r)
            if (i + 1) % 500 == 0:
                logger.info(f"  解析进度: {i+1}/{len(csv_files)} (有效: {len(parsed)})")

    logger.info(f"Phase 1 完成: {len(parsed)} 只有效股票")

    if not parsed:
        logger.error("没有解析到任何有效数据！")
        sys.exit(1)

    # ═══ 构建全局 Calendar ═══
    logger.info("构建交易日历...")
    all_dates = set()
    inst_info = []  # (instrument, min_date, max_date, n_records)
    for instrument, records in parsed:
        dates = sorted(records.keys())
        all_dates.update(dates)
        inst_info.append((instrument, dates[0], dates[-1], len(dates)))

    sorted_dates = sorted(all_dates)
    date_to_idx = {d: i for i, d in enumerate(sorted_dates)}
    logger.info(f"交易日历: {len(sorted_dates)} 天 ({sorted_dates[0]} ~ {sorted_dates[-1]})")

    # 写入 calendars/day.txt
    with open(calendars_dir / "day.txt", "w") as f:
        f.write("\n".join(sorted_dates))

    # 写入 instruments/all.txt
    with open(instruments_dir / "all.txt", "w") as f:
        for inst, min_d, max_d, n in inst_info:
            f.write(f"{inst}\t{min_d}\t{max_d}\n")
    logger.info(f"Instruments: {len(inst_info)} 只")

    # ═══ Phase 2: 多进程写入 Qlib .bin ═══
    logger.info(f"Phase 2: 写入 Qlib .bin 文件 ({workers} 进程)...")
    write_items = [(inst, records, date_to_idx, features_dir, freq) 
                   for inst, records in parsed]

    results = []
    with Pool(workers) as pool:
        for i, r in enumerate(pool.imap_unordered(write_qlib_bin, write_items, chunksize=50)):
            if r is not None:
                results.append(r)
            if (i + 1) % 500 == 0:
                logger.info(f"  写入进度: {i+1}/{len(write_items)} (成功: {len(results)})")

    logger.info(f"Phase 2 完成: {len(results)} 只股票写入成功")

    # ═══ 保存快照 ═══
    snap_dir = target_dir.parent / "snapshots"
    snap_dir.mkdir(exist_ok=True)
    snap_df = pd.DataFrame(results, columns=["instrument", "start_date", "end_date", "records"])
    snap_path = snap_dir / f"instruments_{datetime.now().strftime('%Y%m%d')}.csv"
    snap_df.to_csv(snap_path, index=False)

    logger.info(f"=== 完成 === 输出: {target_dir}")
    logger.info(f"股票: {len(results)}, 交易日: {len(sorted_dates)} 天")


if __name__ == "__main__":
    main()
