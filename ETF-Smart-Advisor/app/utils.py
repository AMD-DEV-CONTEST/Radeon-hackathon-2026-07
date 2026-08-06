# app/utils.py
"""
工具函数
"""

import numpy as np
import pandas as pd
from typing import Any, Optional, Union, List
from datetime import datetime, timedelta
import traceback
import sys
holiday_list_cn = [
        '2026-01-01', # 元旦
        '2026-02-15', '2026-02-16', '2026-02-17', '2026-02-18', '2026-02-19', 
        '2026-02-20', '2026-02-21', '2026-02-22', '2026-02-23', # 春节连休
        '2026-04-04', '2026-04-05', '2026-04-06', # 清明
        '2026-05-01', '2026-05-02', '2026-05-03', '2026-05-04', '2026-05-05', # 五一 (当前时间附近的假期)
        '2026-06-19', '2026-06-20', '2026-06-21', # 端午
        '2026-09-25', '2026-09-26', '2026-09-27', # 中秋
        '2026-10-01', '2026-10-02', '2026-10-03', '2026-10-04', 
        '2026-10-05', '2026-10-06', '2026-10-07', # 国庆
        '2027-01-01'
    ]


def format_exception(e):
    exception_list = traceback.format_stack()
    exception_list = exception_list[:-2]
    exception_list.extend(traceback.format_tb(sys.exc_info()[2]))
    exception_list.extend(traceback.format_exception_only(sys.exc_info()[0], sys.exc_info()[1]))
    
    exception_str = "Traceback (most recent call last):\n"
    exception_str += "".join(exception_list)
    # Removing the last \n
    exception_str = exception_str[:-1]

    return exception_str
def get_last_date(df: pd.DataFrame) -> Any:
    """从 DataFrame 获取最后日期（兼容索引和列）"""
    if df is None or df.empty:
        return None
    
    # 检查索引是否为日期类型
    if isinstance(df.index, pd.DatetimeIndex):
        return df.index[-1]
    
    # 检查是否有 'date' 列
    if 'date' in df.columns:
        return df['date'].iloc[-1]
    
    return None


def generate_future_daily_dates( start_date, pred_len, end_date=None):
 
    def _to_timestamp(date_obj):
        if not isinstance(date_obj, pd.Timestamp):
            return pd.Timestamp(date_obj)
        return date_obj
    
    start_date =  _to_timestamp(start_date)
    
    if end_date is not None:
        end_date =  _to_timestamp(end_date)
        # 计算从 start_date 到 end_date 之间的交易日数量
        temp_date = start_date + timedelta(days=1)
        max_days = 0
        while temp_date <= end_date:
            if temp_date.weekday() < 5 and temp_date.strftime('%Y-%m-%d') not in holiday_list_cn:
                max_days += 1
            temp_date += timedelta(days=1)
        
        actual_len = min(pred_len, max_days)
    else:
        actual_len = pred_len
    
    future_dates = []
    current_date = start_date + timedelta(days=1)
    
    while len(future_dates) < actual_len:
        if end_date is not None and current_date > end_date:
            break
            
        if current_date.weekday() < 5 and current_date.strftime('%Y-%m-%d') not in holiday_list_cn:
            future_dates.append(pd.Timestamp(current_date))
        current_date += timedelta(days=1)
    
    return future_dates[:pred_len]
