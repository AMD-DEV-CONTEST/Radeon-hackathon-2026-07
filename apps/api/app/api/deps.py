"""
数据库会话依赖注入
"""
from app.models.database import get_db, get_timescale_db

# 直接导出，供API端点使用
__all__ = ['get_db', 'get_timescale_db']
