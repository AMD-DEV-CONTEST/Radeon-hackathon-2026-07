"""
从通达信导出的 CSV 日线数据导入到 Qlib 格式

数据源: /Users/gaochangcheng/Desktop/股票数据/沪深京个股日线历史数据(前复权)/
CSV 格式（通达信导出）:
  第1行: <代码> <名称> <市场> <复权方式>
  第2行: 日期\t开盘\t最高\t最低\t收盘\t成交量\t成交额 (tab分隔)
  数据行: 日期,开盘,最高,最低,收盘,成交量,成交额 (逗号分隔)
  最后行: #数据来源:通达信

用法:
  python -m backend.data_svc.import_tdx_data
  python -m backend.data_svc.import_tdx_data --target rdagent  # 导出到 RD-Agent 默认路径
"""
import os
import sys
from pathlib import Path
import argparse
import numpy as np
import pandas as pd
from datetime import datetime
from loguru import logger

# 确保项目根目录在 path
_project_root = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_project_root))

from backend.data_svc import QlibDataExporter, FeatureEngineering


DATA_SOURCE = Path("/Users/gaochangcheng/Desktop/股票数据/沪深京个股日线历史数据(前复权)")


def _detect_encoding(filepath: Path) -> str:
    """检测 CSV 编码"""
    try:
        with open(filepath, "rb") as f:
            raw = f.read(100)
        if raw[:3] == b"\xef\xbb\xbf":
            return "utf-8-sig"
        # 检测 GBK 特征
        try:
            raw.decode("gbk")
            return "gbk"
        except UnicodeDecodeError:
            pass
        return "utf-8"
    except Exception:
        return "gbk"


def _code_to_qlib_instrument(code: str) -> str:
    """
    纯数字代码 → Qlib instrument 格式
    6xxxxx / 9xxxxx → sh600000
    0xxxxx / 3xxxxx / 2xxxxx → sz000001
    4xxxxx / 8xxxxx → sz (创业板/科创板，用sz)
    其他 → sh
    """
    code = code.strip()
    if code.startswith(("sh", "sz", "SH", "SZ")):
        return code.lower()
    if code.startswith(("6", "9")):
        return f"sh{code}"
    elif code.startswith(("0", "3", "2", "4", "8")):
        return f"sz{code}"
    return f"sh{code}"


def parse_tdx_csv(filepath: Path) -> pd.DataFrame | None:
    """
    解析通达信导出的日线 CSV，返回标准化 DataFrame
    
    Returns:
        DataFrame with columns: date, instrument, open, high, low, close, volume, amount
        或 None（解析失败）
    """
    encoding = _detect_encoding(filepath)
    
    try:
        with open(filepath, "r", encoding=encoding) as f:
            lines = f.readlines()
    except Exception as e:
        logger.warning(f"读取 {filepath.name} 失败: {e}")
        return None

    # 过滤掉空行和注释行
    lines = [l.rstrip("\n").rstrip("\r") for l in lines]
    lines = [l for l in lines if l.strip() and not l.startswith("#")]
    
    if len(lines) < 3:
        return None

    # 第1行: 代码 名称 市场 复权方式
    header_parts = lines[0].split()
    if len(header_parts) < 1:
        return None
    code = header_parts[0]
    instrument = _code_to_qlib_instrument(code)

    # 数据行（从第3行开始，跳过标题和列名行）
    records = []
    for line in lines[2:]:
        parts = line.split(",")
        if len(parts) < 7:
            continue
        try:
            date_str = parts[0].strip()
            # 通达信日期格式: YYYYMMDD
            if len(date_str) == 8:
                date = f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:8]}"
            else:
                continue
            
            open_p = float(parts[1])
            high = float(parts[2])
            low = float(parts[3])
            close = float(parts[4])
            volume = float(parts[5])
            amount = float(parts[6])
            
            # 跳过明显异常的数据（价格为负或为0，可能停牌）
            if close <= 0 or high <= 0:
                continue
                
            records.append({
                "date": date,
                "instrument": instrument,
                "open": open_p,
                "high": high,
                "low": low,
                "close": close,
                "volume": volume,
                "amount": amount,
                "factor": 1.0,  # 前复权数据，factor=1
            })
        except (ValueError, IndexError):
            continue

    if not records:
        return None

    df = pd.DataFrame(records)
    df["date"] = pd.to_datetime(df["date"])
    df = df.sort_values("date")
    return df


def import_all_data(
    target: str = "project",
    start_date: str = "2015-01-01",
    max_files: int | None = None,
) -> Path:
    """
    批量导入所有通达信 CSV 数据

    Args:
        target: "project" → db/qlib_data/ ; "rdagent" → ~/.qlib/qlib_data/cn_data/
        start_date: 只保留此日期之后的数据（减少文件大小）
        max_files: 最多导入文件数（None=全部）

    Returns:
        输出目录路径
    """
    csv_files = sorted(DATA_SOURCE.glob("*.csv"))
    logger.info(f"发现 {len(csv_files)} 个 CSV 文件")

    if max_files:
        csv_files = csv_files[:max_files]
        logger.info(f"限制导入前 {max_files} 个文件")

    all_frames = []
    success_count = 0
    fail_count = 0
    skipped_no_data = 0
    skipped_date_filter = 0

    for i, csv_path in enumerate(csv_files):
        if (i + 1) % 500 == 0:
            logger.info(f"进度: {i+1}/{len(csv_files)} (成功: {success_count}, 失败: {fail_count})")

        try:
            df = parse_tdx_csv(csv_path)
            if df is None or df.empty:
                fail_count += 1
                continue

            # 日期过滤
            if start_date:
                df = df[df["date"] >= start_date]
                if df.empty:
                    skipped_date_filter += 1
                    continue

            all_frames.append(df)
            success_count += 1
        except Exception as e:
            logger.warning(f"处理 {csv_path.name} 异常: {e}")
            fail_count += 1

    logger.info(f"解析完成: 成功 {success_count}, 失败 {fail_count}, "
                f"日期过滤跳过 {skipped_date_filter}")

    if not all_frames:
        logger.error("没有解析到任何有效数据！")
        sys.exit(1)

    # 合并所有数据
    df_all = pd.concat(all_frames, ignore_index=True)
    df_all = df_all.drop_duplicates(subset=["date", "instrument"])
    logger.info(f"合并后: {len(df_all)} 条记录, {df_all['instrument'].nunique()} 只股票, "
                f"{df_all['date'].min().date()} ~ {df_all['date'].max().date()}")

    # 添加技术指标
    logger.info("计算技术指标特征...")
    df_all = FeatureEngineering.add_technical_indicators(df_all)

    # 导出 Qlib 格式
    logger.info(f"导出 Qlib 二进制格式 (target={target})...")
    if target == "rdagent":
        output_dir = QlibDataExporter.export_to_qlib_for_rdagent(df_all)
    else:
        from backend.shared.config import settings
        output_dir = QlibDataExporter.export_to_qlib(df_all, settings.db_dir)

    # 同时保存一份 CSV 快照供其他模块使用
    snap_dir = output_dir.parent / "snapshots"
    snap_dir.mkdir(exist_ok=True)
    snap_path = snap_dir / f"daily_{datetime.now().strftime('%Y%m%d')}.parquet"
    df_all.to_parquet(snap_path, index=False)
    logger.info(f"数据快照已保存: {snap_path}")

    logger.info(f"=== 导入完成！输出目录: {output_dir} ===")
    logger.info(f"股票数: {df_all['instrument'].nunique()}, 记录数: {len(df_all)}, "
                f"日期范围: {df_all['date'].min().date()} ~ {df_all['date'].max().date()}")

    return output_dir


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="导入通达信日线数据到 Qlib 格式")
    parser.add_argument(
        "--target", choices=["project", "rdagent"], default="project",
        help="导出目标: project=项目db目录, rdagent=~/.qlib/qlib_data/cn_data/"
    )
    parser.add_argument(
        "--start-date", default="2015-01-01",
        help="只保留此日期之后的数据 (默认: 2015-01-01)"
    )
    parser.add_argument(
        "--max-files", type=int, default=None,
        help="最多导入文件数 (默认: 全部)"
    )
    parser.add_argument(
        "--rdagent", action="store_true",
        help="快捷方式: 直接导出到 RD-Agent 默认路径"
    )
    args = parser.parse_args()

    target = "rdagent" if args.rdagent else args.target
    import_all_data(
        target=target,
        start_date=args.start_date,
        max_files=args.max_files,
    )
