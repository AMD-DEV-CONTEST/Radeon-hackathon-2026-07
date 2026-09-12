"""
aiquant 统一日志配置
====================
基于 loguru，提供：
- 终端：人类可读的彩色格式
- 文件：JSON 格式（.jsonl）+ 纯文本格式（.log），便于 ELK/Loki 采集和人类 grep
- 自动轮转：每 50MB 轮转，保留 10 个文件，旧文件 zip 压缩
- 上下文绑定：通过 get_logger(task_id=..., component=...) 自动注入字段
"""

import os
import sys
from pathlib import Path
from loguru import logger


_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
_LOG_DIR = _PROJECT_ROOT / "logs"
_LOG_DIR.mkdir(parents=True, exist_ok=True)


def _console_format(record):
    """终端可读格式：时间 | LEVEL | [task_id] [component] | module:func:line | message"""
    extra = record.get("extra", {})
    ctx = ""
    if extra.get("task_id"):
        ctx += f"[{extra['task_id']}] "
    if extra.get("component"):
        ctx += f"[{extra['component']}] "
    return (
        "<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> | "
        "<level>{level: <8}</level> | "
        f"{ctx}"
        "<cyan>{module}:{function}:{line}</cyan> | "
        "<level>{message}</level>\n{exception}"
    )


def setup_logging(log_level: str = "INFO"):
    """
    初始化全局日志配置。三个输出通道：
    1. stderr - 彩色人类可读
    2. logs/aiquant.jsonl - loguru 内置 serialize=True，JSON 格式，50MB 轮转，保留 10 份
    3. logs/aiquant.log - 纯文本，50MB 轮转，保留 10 份
    """
    logger.remove()

    # 1. 终端（人类可读）
    logger.add(
        sys.stderr,
        format=_console_format,
        level=log_level,
        colorize=None,
        backtrace=True,
        diagnose=True,
    )

    # 2. JSON 文件（机器可读，loguru 内置 serialize）
    #    serialize=True 会在每条日志前自动添加 JSON 格式的 record 元数据
    logger.add(
        str(_LOG_DIR / "aiquant.jsonl"),
        level=log_level,
        serialize=True,
        rotation="50 MB",
        retention=10,
        compression="zip",
        enqueue=True,
        backtrace=True,
        diagnose=False,
    )

    # 3. 纯文本文件（人类可读，便于 grep）
    logger.add(
        str(_LOG_DIR / "aiquant.log"),
        format="{time:YYYY-MM-DD HH:mm:ss.SSS} | {level: <8} | {module}:{function}:{line} | {message}",
        level=log_level,
        rotation="50 MB",
        retention=10,
        compression="zip",
        enqueue=True,
        backtrace=True,
        diagnose=False,
    )


def get_logger(task_id: str = "", component: str = ""):
    """
    获取带上下文的 logger。extra 字段自动注入到每条日志。

    Example:
        log = get_logger("TASK-123", "engine")
        log.info("因子进化开始")  # JSON 中自动带 task_id + component
    """
    extra = {}
    if task_id:
        extra["task_id"] = task_id
    if component:
        extra["component"] = component
    return logger.bind(**extra)


# 模块导入时自动初始化
setup_logging(log_level=os.environ.get("AIQUANT_LOG_LEVEL", "INFO"))
