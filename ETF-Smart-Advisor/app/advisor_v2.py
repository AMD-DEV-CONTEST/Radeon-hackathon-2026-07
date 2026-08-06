# app/advisor_v2.py
"""
投资顾问引擎 - Skill-based 版本
整合技能、分批处理和筛选机制
"""

import time
from typing import Dict, List, Any, Optional
from datetime import datetime

from .skills import (
    ETFDataSkill,
    ETFAnalyzeSkill,
    ETFRankingSkill,
    ETFDeepAnalyzeSkill
)


class InvestmentAdvisorV2:
    """
    投资顾问 - Skill-based版本
    """
    
    def __init__(self):
        # 注册技能
        self.skills = {
            'data': ETFDataSkill(),
            'quick_analyze': ETFAnalyzeSkill(),
            'ranking': ETFRankingSkill(),
            'deep_analyze': ETFDeepAnalyzeSkill()
        }
        
        # 配置
        self.config = {
            'stage1_keep': 700,
            'stage2_keep': 100,
            'stage3_keep': 3,
        }
        
        # 缓存
        self.cache = {}
        self.cache_time = {}
        self.cache_ttl = 3600
        
        print("✅ InvestmentAdvisorV2 initiated")
        print(f"   📋 Registered skills: {list(self.skills.keys())}")
    
    def get_top_recommendations(
        self, 
        symbols: List[str] = None,
        force_update: bool = False
    ) -> Dict[str, Any]:
        """
        获取Top推荐 - 三阶段Skill流程
        """
        start_time = time.time()
        
        if symbols is None:
            symbols = self.skills['data'].fetcher.get_etf_list()
        
        if not symbols:
            return {'error': '没有可用的ETF'}
        
        print(f"\n{'='*60}")
        print(f"📊 Skill-based ETF analysis with 3 phases (about 4 hours)")
        print(f"   ETF: {len(symbols)}")
        print(f"   {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"{'='*60}\n")
        
        # ============================================================
        # 阶段1: 快速分析Skill
        # ============================================================
        print("🔍 Phase1: Quick Analysis (Skill: ETFAnalyzeSkill)")
        print("-" * 50)
        
        stage1_start = time.time()
        
        candidates = self.skills['quick_analyze'].execute(
            symbols, 
            self.config['stage1_keep']
        )
        
        print(f"   ✅ Time used: {time.time() - stage1_start:.2f}s")
        print(f"   📊 Selected: {len(candidates)} 个\n")
        
        if len(candidates) < 10:
            return self._empty_result("阶段1候选不足")
        
        # ============================================================
        # 阶段2: 精细排名Skill
        # ============================================================
        print("🏆 Phase2: Fine Ranking (Skill: ETFRankingSkill)")
        print("-" * 50)
        
        stage2_start = time.time()
        
        ranked = self.skills['ranking'].execute(
            candidates,
            self.config['stage2_keep']
        )
        
        print(f"   ✅ Time used: {time.time() - stage2_start:.2f}s")
        print(f"   📊 Selected: {len(ranked)} 个\n")
        
        if len(ranked) < 3:
            return self._empty_result("阶段2候选不足")
        
        # ============================================================
        # 阶段3: 深度分析Skill
        # ============================================================
        print("📊 Phase3: Deep Analysis (Skill: ETFDeepAnalyzeSkill)")
        print("-" * 50)
        
        stage3_start = time.time()
        
        final_results = self.skills['deep_analyze'].execute(
            ranked,
            self.config['stage3_keep']
        )
        
        print(f"   ✅ Time used: {time.time() - stage3_start:.2f}s")
        print(f"   📊 Final Recommendations: {len(final_results)} 个\n")
        
        # ============================================================
        # 格式化结果
        # ============================================================
        result = self._format_result(final_results)
        result['summary'] = {
            'total_analyzed': len(symbols),
            'stage1_count': len(candidates),
            'stage2_count': len(ranked),
            'stage3_count': len(final_results),
            'stage1_time': f"{time.time() - stage1_start:.2f}s",
            'stage2_time': f"{time.time() - stage2_start:.2f}s",
            'stage3_time': f"{time.time() - stage3_start:.2f}s",
            'total_time': f"{time.time() - start_time:.2f}s",
            'method': 'Skill-based Multi-stage',
            'date': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        }
        
        print(f"\n{'='*60}")
        print(f"✅ Completed! Total time: {result['summary']['total_time']}")
        print(f"{'='*60}\n")
        
        return result
    
    def _format_result(self, results: List[Dict]) -> Dict:
        """格式化结果"""
        buy, sell, hold = [], [], []
        
        for item in results:
            rec = item.get('recommendation', 'hold')
            formatted = {
                'symbol': item.get('symbol', 'N/A'),
                'score': round(item.get('final_score', 0), 1),
                'price': round(item.get('current_price', 0), 3),
                'target': round(item.get('target_price', 0), 3),
                'stop_loss': round(item.get('stop_loss', 0), 3),
                'signal': item.get('signal', 'N/A'),
                'confidence': round(item.get('confidence', 0), 2),
                'risk': item.get('risk_level', 'N/A'),
                'analysis': item.get('analysis', '')[:200],
                'ma20': round(item.get('ma20', 0), 3),
                'rsi': round(item.get('rsi', 0), 1),
            }
            
            if rec == 'buy':
                buy.append(formatted)
            elif rec == 'sell':
                sell.append(formatted)
            else:
                hold.append(formatted)
        
        return {
            'buy': buy[:3],
            'sell': sell[:3],
            'hold': hold[:3]
        }
    
    def _empty_result(self, error: str) -> Dict:
        return {
            'buy': [],
            'sell': [],
            'hold': [],
            'error': error
        }