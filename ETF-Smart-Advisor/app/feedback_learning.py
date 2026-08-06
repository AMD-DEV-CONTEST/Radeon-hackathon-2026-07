# app/feedback_learning.py
"""
用户反馈学习与自定义迭代 - 使用 Milvus 存储
"""

import json
import numpy as np
from typing import Dict, List, Any, Optional
from datetime import datetime
from collections import defaultdict
import logging

from .milvus_client import get_milvus_client

logger = logging.getLogger(__name__)


class FeedbackLearning:
    """用户反馈学习与自定义迭代 - 使用 Milvus 存储"""
    
    def __init__(self, feedback_path: str = "data/feedback.json"):
        self.feedback_path = feedback_path  # 保留作为参考
        self.learning_rate = 0.1
        self.confidence_threshold = 0.6
        
        # 策略权重 - 保留在内存中（小数据量）
        self.strategy_weights = defaultdict(lambda: 1.0)
        self._load_strategy_weights()
        
        # ✅ 使用新的 Milvus 客户端
        self._milvus = get_milvus_client()
        self._feedback_available = self._milvus.feedback is not None
        
        # 统计信息缓存
        self._stats_cache = None
        self._stats_cache_time = None
        
        logger.info(f"📚 反馈学习系统初始化完成")
        if self._feedback_available:
            stats = self._milvus.feedback.get_stats()
            logger.info(f"   📊 已收集反馈: {stats.get('row_count', 0)} 条")
        else:
            logger.info(f"   ⚠️ Milvus 不可用，使用内存模式")
    
    def _load_strategy_weights(self):
        """加载策略权重"""
        try:
            weight_path = self.feedback_path.replace('feedback', 'weights')
            with open(weight_path, 'r') as f:
                weights = json.load(f)
                self.strategy_weights.update(weights)
        except:
            pass
    
    def _save_weights(self):
        """保存策略权重"""
        try:
            weight_path = self.feedback_path.replace('feedback', 'weights')
            with open(weight_path, 'w') as f:
                json.dump(dict(self.strategy_weights), f)
        except:
            pass
    
    def record_feedback(self, symbol: str, recommendation: str, 
                       actual_result: str, user_rating: int,
                       user_comment: str = "",
                       metadata: Optional[Dict] = None):
        """记录用户反馈"""
        timestamp = datetime.now().isoformat()
        accuracy = self._calculate_accuracy(recommendation, actual_result)
        
        feedback = {
            "timestamp": timestamp,
            "symbol": symbol,
            "recommendation": recommendation,
            "actual_result": actual_result,
            "user_rating": user_rating,
            "user_comment": user_comment,
            "accuracy": accuracy,
            "metadata": metadata or {}
        }
        
        # ✅ 使用新的 FeedbackManager
        if self._feedback_available:
            self._milvus.feedback.insert_feedback(feedback)
        else:
            # 降级到内存
            self._feedback_cache.append(feedback)
        
        # 更新策略权重
        self._update_weights(feedback)
        
        # 清除缓存
        self._stats_cache = None
        
        logger.info(f"✅ 反馈已记录: {symbol} - {recommendation} - 评分: {user_rating}")
    
    def _calculate_accuracy(self, recommendation: str, actual_result: str) -> float:
        """计算准确性"""
        accuracy_map = {
            ("buy", "up"): 1.0,
            ("sell", "down"): 1.0,
            ("hold", "sideways"): 0.8,
            ("buy", "up_strong"): 1.0,
            ("sell", "down_strong"): 1.0,
        }
        
        for (rec, actual), acc in accuracy_map.items():
            if rec in recommendation and actual in actual_result:
                return acc
        
        return 0.3
    
    def _update_weights(self, feedback: Dict):
        """更新策略权重（强化学习）"""
        symbol = feedback["symbol"]
        recommendation = feedback["recommendation"]
        accuracy = feedback["accuracy"]
        rating = feedback["user_rating"]
        
        adjustment = self.learning_rate * (accuracy * rating / 5 - 0.5)
        
        key = f"{symbol}_{recommendation}"
        self.strategy_weights[key] += adjustment
        self.strategy_weights[key] = max(0.1, min(2.0, self.strategy_weights[key]))
        
        self._save_weights()
    
    def get_improved_recommendation(self, symbol: str, base_recommendation: Dict) -> Dict:
        """基于反馈改进推荐"""
        # ✅ 从 Milvus 查询该股票的反馈
        if self._feedback_available:
            symbol_feedback = self._milvus.feedback.get_by_symbol(symbol, limit=1000)
        else:
            symbol_feedback = [f for f in self._feedback_cache if f.get("symbol") == symbol]
        
        if not symbol_feedback:
            return base_recommendation
        
        # 计算准确率
        accurate = sum(1 for f in symbol_feedback if f.get("accuracy", 0) > 0.5)
        accuracy_rate = accurate / len(symbol_feedback) if symbol_feedback else 0
        
        # 获取权重
        key = f"{symbol}_{base_recommendation.get('recommendation', 'unknown')}"
        weight = self.strategy_weights.get(key, 1.0)
        
        # 调整建议
        if accuracy_rate > 0.7 and weight > 1.2:
            base_recommendation["confidence"] = min(1.0, base_recommendation.get("confidence", 0.5) * 1.2)
            base_recommendation["enhanced"] = True
            
        elif accuracy_rate < 0.4 and weight < 0.8:
            base_recommendation["confidence"] = max(0.1, base_recommendation.get("confidence", 0.5) * 0.8)
            base_recommendation["warning"] = "历史准确率较低，请谨慎参考"
        
        base_recommendation["feedback_learning"] = {
            "total_feedback": len(symbol_feedback),
            "accuracy_rate": accuracy_rate,
            "strategy_weight": weight,
        }
        
        return base_recommendation
    
    def get_accuracy_report(self) -> Dict:
        """生成准确率报告"""
        # 使用缓存
        if self._stats_cache and self._stats_cache_time:
            if (datetime.now() - self._stats_cache_time).seconds < 300:
                return self._stats_cache
        
        # ✅ 从 Milvus 查询
        if self._feedback_available:
            feedback_data = self._milvus.feedback.get_all(limit=10000)
        else:
            feedback_data = self._feedback_cache
        
        if not feedback_data:
            return {"status": "no_data", "message": "暂无反馈数据"}
        
        stats = self._calculate_stats(feedback_data)
        self._stats_cache = stats
        self._stats_cache_time = datetime.now()
        return stats
    
    def _calculate_stats(self, feedback_data: List[Dict]) -> Dict:
        """计算统计信息"""
        total = len(feedback_data)
        accurate = sum(1 for f in feedback_data if f.get("accuracy", 0) > 0.5)
        avg_rating = sum(f.get("user_rating", 3) for f in feedback_data) / total
        
        # 按股票统计
        symbol_stats = defaultdict(lambda: {"total": 0, "accurate": 0, "ratings": []})
        for f in feedback_data:
            symbol = f.get("symbol", "unknown")
            symbol_stats[symbol]["total"] += 1
            if f.get("accuracy", 0) > 0.5:
                symbol_stats[symbol]["accurate"] += 1
            symbol_stats[symbol]["ratings"].append(f.get("user_rating", 3))
        
        symbol_accuracy = {
            symbol: {
                "total": stats["total"],
                "accuracy": stats["accurate"] / stats["total"] if stats["total"] > 0 else 0,
                "avg_rating": sum(stats["ratings"]) / len(stats["ratings"]) if stats["ratings"] else 0
            }
            for symbol, stats in symbol_stats.items()
        }
        
        return {
            "total_feedback": total,
            "overall_accuracy": accurate / total if total > 0 else 0,
            "avg_rating": avg_rating,
            "symbol_accuracy": symbol_accuracy,
            "top_symbols": sorted(
                symbol_accuracy.items(),
                key=lambda x: x[1]["accuracy"],
                reverse=True
            )[:10]
        }
    
    def clear_feedback(self, symbol: Optional[str] = None):
        """清除反馈数据"""
        if self._feedback_available:
            self._milvus.feedback.clear(symbol)
        else:
            if symbol:
                self._feedback_cache = [f for f in self._feedback_cache if f.get("symbol") != symbol]
            else:
                self._feedback_cache = []
        
        self._stats_cache = None


# 全局单例
_feedback_instance = None
_feedback_cache = []  # 内存模式下的反馈缓存


def get_feedback_learning():
    """获取反馈学习实例"""
    global _feedback_instance
    if _feedback_instance is None:
        _feedback_instance = FeedbackLearning()
    return _feedback_instance