import os
import glob

import akshare as ak
import yfinance as yf
import pandas as pd
import numpy as np
from pathlib import Path
from datetime import datetime, timedelta
from typing import Dict, List, Optional
from .config import CACHE_DIR
from .utils import format_exception, get_last_date, generate_future_daily_dates

script_path = os.path.dirname(os.path.abspath(__file__))
raw_data_path=f'{script_path}/../data/1D'
parquet_path=f'{script_path}/../data/history/1D'
# raw_data_path=f'{script_path}/../../datatemp/raw_data/1D'


class ETFDataFetcher:
    """ETF数据获取器"""
    
    def __init__(self):
        self.cache_dir = CACHE_DIR
    
    def get_etf_quote(self, symbol: str) -> Optional[Dict]:
        """获取实时行情"""
        try:
            code = symbol[-6:] if symbol.startswith(('SH', 'SZ')) else symbol
            print('calling ak.stock_zh_a_spot_em to get stock quote')
            df = ak.stock_zh_a_spot_em()
            df['代码'] = df['代码'].astype(str)
            row = df[df['代码']== code]
            if  row.empty:    
                print('calling ak.fund_etf_spot_em to get etf quote')
                df = ak.fund_etf_spot_em()
                df['代码'] = df['代码'].astype(str)
                row = df[df['代码']== code]
            if not row.empty:
                print(f'get_etf_quote:{symbol}\n{row}')
                return row.to_dict(orient='records')[0]
                
        except Exception as e:
            print(f"get_etf_quote error. Exception:{e}\nTrackback:{format_exception(e)}")
            
        return None
    
    def get_history(self, symbol: str, period: str = "1y") -> pd.DataFrame:
        """获取历史数据"""
        
        # 查找文件
        files = glob.glob(os.path.join(parquet_path, "**", f"*{symbol}*.parquet"), recursive=True)
        if not files:
            return pd.DataFrame()
        
        # 读取最新文件
        df = pd.read_parquet(max(files, key=os.path.getmtime))
        
        # 设置日期索引
        if 'date' in df.columns:
            df['date'] = pd.to_datetime(df['date'])
            df = df.set_index('date').sort_index()
        if 'money' in df.columns:
            df.rename(columns={
                "money": "amount"
            }, inplace=True)
        # print(f'get_history:{symbol}\n{df}')
        return df
    def get_etf_list(self) -> List[str]:
        return self._get_file_list()
    
    def get_stock_list(self) -> List[str]:
        return self._get_file_list('stock')
    def _get_file_list(self,sub_folder='etf')-> List[str]:
        data_path = Path(parquet_path+'/'+sub_folder)
        if not data_path.exists():
            return []
        
        return [
            p.stem 
            for p in data_path.rglob("*") 
            if p.is_file() and p.suffix in ['.txt', '.csv', '.parquet']
        ]
        
