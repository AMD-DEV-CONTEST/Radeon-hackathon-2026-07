"""
工具函数 - 异步辅助
"""

import asyncio
import logging
import time
from functools import wraps
from typing import Callable, TypeVar, Any

logger = logging.getLogger(__name__)

T = TypeVar("T")


def async_timer(name: str = ""):
    """
    异步计时装饰器 - 精确测量延迟
    
    用法:
        @async_timer("inference")
        async def my_func(): ...
    """
    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        @wraps(func)
        async def wrapper(*args, **kwargs):
            start = time.perf_counter()
            try:
                return await func(*args, **kwargs)
            finally:
                latency = (time.perf_counter() - start) * 1000
                logger.debug(f"{name or func.__name__}: {latency:.2f}ms")
        return wrapper
    return decorator


async def retry_with_backoff(
    func: Callable[..., T],
    *,
    max_retries: int = 3,
    base_delay: float = 1.0,
    exceptions: tuple = (Exception,),
) -> T:
    """
    指数退避重试 - 网络抖动恢复
    
    Args:
        func: 异步函数
        max_retries: 最大重试次数
        base_delay: 基础延迟秒数
        exceptions: 捕获的异常类型
    """
    for attempt in range(max_retries):
        try:
            return await func()
            
        except exceptions as e:
            if attempt == max_retries - 1:
                raise
            
            delay = base_delay * (2 ** attempt)
            logger.warning(f"Retry {attempt + 1}/{max_retries} after {delay:.1f}s: {e}")
            await asyncio.sleep(delay)