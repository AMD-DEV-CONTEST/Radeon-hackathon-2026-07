# app/skills/__init__.py
"""
技能模块 - 封装ETF分析的核心能力
"""

from .base_skill import BaseSkill
from .etf_skills import (
    ETFDataSkill,
    ETFAnalyzeSkill,
    ETFRankingSkill,
    ETFDeepAnalyzeSkill
)

__all__ = [
    'BaseSkill',
    'ETFDataSkill',
    'ETFAnalyzeSkill',
    'ETFRankingSkill',
    'ETFDeepAnalyzeSkill'
]