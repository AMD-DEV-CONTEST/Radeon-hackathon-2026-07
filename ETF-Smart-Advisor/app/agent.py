# app/agent.py
"""
ETF 智能投顾 Agent - 包含所有业务逻辑
"""

import json
import hashlib
from collections import defaultdict
from datetime import datetime
import logging
from pathlib import Path
from typing import Dict, Any, List, Optional
import traceback
import torch
from .llm_client import get_llm_client
from .feedback_learning import FeedbackLearning
from .config import (
    AGENT_SYSTEM_PROMPT, AGENT_SYSTEM_PROMPT_EXTENDED,
    MEMORY_CONFIG, MODELS_DIR, MILVUS_CONFIG
)
from .data_fetcher import ETFDataFetcher
from .advisor import InvestmentAdvisor
from .advisor_v2 import InvestmentAdvisorV2
from .predictor import ETFPricePredictor
from .milvus_client import get_milvus_client
from .privacy.privacy_manager import PrivacyManager
from .utils import format_exception

logger = logging.getLogger(__name__)


class MemoryManager:
    """本地多轮记忆管理"""
    
    def __init__(self, memory_path: str = None):
        if memory_path is None:
            memory_path = MEMORY_CONFIG.get("memory_path", "data/memory.json")
        self.memory_path = memory_path
        self.memories = defaultdict(list)
        self._load_memories()
    
    def _load_memories(self):
        try:
            with open(self.memory_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
                self.memories.update(data)
        except (FileNotFoundError, json.JSONDecodeError):
            pass
    
    def _save_memories(self):
        try:
            with open(self.memory_path, 'w', encoding='utf-8') as f:
                json.dump(dict(self.memories), f, ensure_ascii=False, indent=2)
        except:
            pass
    
    def add(self, session_id: str, query: str, response: str):
        memory = {
            "timestamp": datetime.now().isoformat(),
            "query": query,
            "response": response[:500],
            "hash": hashlib.md5(query.encode()).hexdigest()
        }
        self.memories[session_id].append(memory)
        self._save_memories()
    
    def get_context(self, session_id: str, limit: int = None) -> str:
        if limit is None:
            limit = MEMORY_CONFIG.get("max_history", 10)
        memories = self.memories.get(session_id, [])[-limit:]
        if not memories:
            return ""
        context = ""
        for m in memories:
            context += f"用户: {m['query']}\n助手: {m['response']}\n"
        return context
    
    def get_stats(self) -> Dict:
        """获取记忆统计"""
        total = sum(len(v) for v in self.memories.values())
        return {
            "total_sessions": len(self.memories),
            "total_memories": total,
            "avg_per_session": total / len(self.memories) if self.memories else 0,
        }


class TaskPlanner:
    """多步骤任务规划器"""
    
    def __init__(self):
        self.step_templates = {
            "quick": [
                {"name": "get_quote", "params": {"symbol": "{symbol}"}, "desc": "获取实时行情"},
                {"name": "get_recommendation", "params": {"symbol": "{symbol}"}, "desc": "获取投资建议"},
            ],
            "full": [
                {"name": "get_quote", "params": {"symbol": "{symbol}"}, "desc": "获取实时行情"},
                {"name": "get_history", "params": {"symbol": "{symbol}", "period": "6mo"}, "desc": "获取历史数据"},
                {"name": "analyze_technical", "params": {"symbol": "{symbol}"}, "desc": "技术分析"},
                {"name": "predict_price", "params": {"symbol": "{symbol}"}, "desc": "价格预测"},
                {"name": "get_recommendation", "params": {"symbol": "{symbol}"}, "desc": "投资建议"},
                {"name": "generate_report", "params": {"symbol": "{symbol}"}, "desc": "生成报告"},
            ],
        }
    
    def plan(self, symbol: str, depth: str = "full") -> List[Dict]:
        steps = self.step_templates.get(depth, self.step_templates["full"])
        result = []
        for step in steps:
            params = {}
            for k, v in step["params"].items():
                if isinstance(v, str):
                    params[k] = v.format(symbol=symbol)
                else:
                    params[k] = v
            result.append({"name": step["name"], "params": params, "desc": step["desc"]})
        return result


class ETFAdvisorAgent:
    """
    ETF 智能投顾 Agent - 包含所有业务逻辑
    
    核心能力：
    1. 工具调用 - 获取 ETF 数据、分析、预测
    2. RAG 检索 - 使用 Milvus 知识库
    3. 多轮记忆 - 对话上下文管理
    4. 任务规划 - 多步骤任务分解
    5. 隐私保护 - 数据脱敏和审计
    """
    
    def __init__(self):
        self.logger = logger
        
        # ============================================================
        # 初始化所有服务
        # ============================================================
        
        # 统一 LLM 客户端（支持 vLLM + Transformers）
        self.llm = get_llm_client()
        try:
            # 测试 LLM 是否可用
            status = self.llm.get_model_status()
            logger.info(f"✅ LLM 客户端初始化成功")
            logger.info(f"   vLLM 可用: {status.get('vllm_available', False)}")
            logger.info(f"   Transformers 已加载: {status.get('transformers_loaded', False)}")
        except Exception as e:
            logger.warning(f"⚠️ LLM 客户端初始化警告: {e}")
        
        # 反馈学习
        self.feedback_learning = FeedbackLearning()
        
        # 数据获取
        self.fetcher = ETFDataFetcher()
        
        # 投资顾问
        self.advisor = InvestmentAdvisor()
        
        self.advisor2 = InvestmentAdvisorV2()
        # 价格预测
        self.predictor = ETFPricePredictor()
        
        
        # Milvus（知识库）
        try:
            self.milvus = get_milvus_client()
            stats = self.milvus.get_stats()
            self.logger.info(f"✅ Milvus 已初始化")
            self.logger.info(f"   Collection: {stats.get('collection', 'N/A')}")
            self.logger.info(f"   知识条目: {stats.get('total_knowledge', 0)}")
        except Exception as e:
            self.logger.warning(f"⚠️ ETFAdvisorAgent - __init__, Milvus 初始化失败: {e}")
            self.milvus = None
        
        # 隐私管理器
        self.privacy = PrivacyManager()
        
        # 记忆管理
        self.memory = MemoryManager() if MEMORY_CONFIG.get("enabled", True) else None
        
        # 任务规划
        self.planner = TaskPlanner()
        
        # 系统提示
        self.system_prompt = AGENT_SYSTEM_PROMPT + "\n" + AGENT_SYSTEM_PROMPT_EXTENDED
        
        logger.info("✅ ETFAdvisorAgent 初始化完成")
    
    # ============================================================
    # 核心 Chat 方法（异步）
    # ============================================================
    
    async def chat(
        self,
        message: str,
        symbol: Optional[str] = None,
        session_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        处理用户消息 - 包含所有业务逻辑
        
        Args:
            message: 用户消息
            symbol: 可选，ETF 代码
            session_id: 可选，会话 ID
        
        Returns:
            {
                "success": bool,
                "response": str,
                "session_id": str,
                "intent": str
            }
        """
        # 1. 隐私保护 - 记录访问
        if self.privacy:
            self.privacy.log_access(
                session_id or "anonymous",
                "chat",
                symbol or "general",
                {"message_length": len(message)}
            )
        

        
        # 3. 意图识别
        message_lower = message.lower()
        
        # 检测是否请求知识检索
        if any(kw in message_lower for kw in ['什么是', '解释', '介绍', '知识', '说明', '科普']):
            rag_result = await self._search_knowledge(message)
            return {
                "response": rag_result,
                "success": True,
                "session_id": session_id,
                "intent": "rag_search"
            }
        
        # 检测是否请求 Top 推荐
        if any(kw in message_lower for kw in ['推荐', 'top', '排名', '最好', '最佳', '涨幅榜']):
            top_results = await self._get_top_recommendations()
            return {
                "response": top_results,
                "success": True,
                "session_id": session_id,
                "intent": "top_recommendations"
            }
        
        # 检测是否请求预测
        if any(kw in message_lower for kw in ['预测', '未来', '走势', '涨跌', '预估']):
            if symbol:
                pred_result = await self._get_prediction(symbol)
                return {
                    "response": pred_result,
                    "success": True,
                    "session_id": session_id,
                    "intent": "prediction"
                }
        
        # 检测是否请求分析
        if any(kw in message_lower for kw in ['分析', '评估', '怎么看', '建议', '诊断']):
            if symbol:
                tech_analysis = await self._analyze_technical(symbol)
                rec_result = await self._get_recommendation(symbol)
                combined = f"{tech_analysis}\n\n{rec_result}"
                return {
                    "response": combined,
                    "success": True,
                    "session_id": session_id,
                    "intent": "analysis"
                }
        
        # 检测是否请求对比
        if any(kw in message_lower for kw in ['对比', '比较', '区别']):
            if symbol:
                # 提取要对比的多个代码
                import re
                symbols = re.findall(r'[0-9]{6}', message)
                if len(symbols) >= 2:
                    compare_result = await self._compare_etfs_str(','.join(symbols[:5]))
                    return {
                        "response": compare_result,
                        "success": True,
                        "session_id": session_id,
                        "intent": "compare"
                    }
        
        # 4. 使用 LLM 处理一般对话
        context = ""
        if self.memory and session_id:
            context = self.memory.get_context(session_id)
        
        # 构建完整消息
        if context:
            full_message = f"历史上下文:\n{context}\n\n用户问题:\n{message}"
        else:
            full_message = message
        
        if symbol:
            full_message = f"当前分析标的: {symbol}\n{full_message}"
        
        try:
            result = self.llm.chat(
                user_message=full_message,
                system_prompt=self.system_prompt,
                max_new_tokens=512,
                temperature=0.7
            )
            
            if result.get('success', False):
                response = result['response']
                if self.memory and session_id:
                    self.memory.add(session_id, message, response)
                
                return {
                    "response": response,
                    "success": True,
                    "session_id": session_id,
                    "intent": "general"
                }
            else:
                return {
                    "response": result.get('response', '处理失败'),
                    "success": False,
                    "session_id": session_id
                }
                
        except Exception as e:
            logger.error(f"Chat error: {e}")
            return {
                "response": f"处理失败: {str(e)}",
                "success": False,
                "session_id": session_id
            }
    
    # ============================================================
    # 同步接口（供 main.py 调用）
    # ============================================================
    
    def get_recommendation_sync(self, symbol: str, period: str = "1y") -> Dict:
        """同步获取投资建议"""
        try:
            df = self.fetcher.get_history(symbol, period)
            if df.empty:
                return {"success": False, "error": f"无法获取 {symbol} 的数据"}
            
            advice = self.advisor.get_recommendation(symbol, df)
            return {"success": True, "data": advice}
        except Exception as e:
            print(f"get_recommendation_sync error. Exception:{e}\nTrackback:{format_exception(e)}")
            return {"success": False, "error": str(e)}
    
    def get_top_recommendations_v2(self,force_update: bool = False):
        """获取Top推荐 - Skill-based版本"""
        try:
            result = self.advisor2.get_top_recommendations(force_update=force_update)

            return result
            # return {
            #     "status": "success",
            #     "data": result,
            #     "timestamp": datetime.now().isoformat()
            # }
        except Exception as e:
            print(f"get_top_recommendations_v2 error. Exception:{e}\nTrackback:{format_exception(e)}")
            return {"success": False, "error": str(e)}
        
    def get_prediction_sync(self, symbol: str, period: str = "1y") -> Dict:
        """同步获取价格预测"""
        try:
            df = self.fetcher.get_history(symbol, period)
            if df.empty:
                return {"success": False, "error": f"无法获取 {symbol} 的数据"}
            
            pred = self.predictor.predict(df, use_ensemble=True)
            if not pred.get('success', False):
                return {"success": False, "error": pred.get('error', '预测失败')}
            return {"success": True, "data": pred}
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    def get_quote_sync(self, symbol: str) -> Dict:
        """同步获取实时行情"""
        try:
            quote = self.fetcher.get_etf_quote(symbol)
            if not quote:
                return {"success": False, "error": f"未找到 {symbol}"}
            return {"success": True, "data": quote}
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    def get_top_recommendations_sync(self) -> Dict:
        """同步获取 Top 推荐"""
        try:
            etfs = self.fetcher.get_etf_list()
            top_results = self.advisor.get_top_recommendations(etfs)
            return {"success": True, "data": top_results}
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    def search_knowledge_sync(self, query: str, top_k: int = 5) -> Dict:
        """同步搜索知识库"""
        try:
            if self.milvus is None:
                return {"success": False, "error": "知识库服务不可用"}
            
            # ✅ 使用 knowledge.search
            results = self.milvus.knowledge.search(query=query, top_k=top_k)
            return {"success": True, "results": results, "count": len(results)}
        except Exception as e:
            return {"success": False, "error": str(e)}    
    async def _search_knowledge(self, query: str, category: Optional[str] = None) -> str:
        """搜索知识库 - 使用 Milvus 向量检索"""
        if self.privacy:
            self.privacy.log_access(
                "user",
                "search_knowledge",
                "rag",
                {"query": query[:50], "category": category}
            )
        
        if self.milvus is None:
            return "⚠️ 知识库服务不可用，请检查 Milvus 连接"
        
        try:
            # ✅ 使用 knowledge.search
            results = self.milvus.knowledge.search(query=query, top_k=5, category=category)
            
            if not results:
                try:
                    llm_response = await self._generate_knowledge_response(query)
                    if llm_response:
                        return f"📚 知识检索结果\n{'='*40}\n\n未在知识库中找到相关内容，但根据我的理解：\n\n{llm_response}"
                except:
                    pass
                return "📚 知识检索结果\n{'='*40}\n\n未找到相关知识，请尝试其他关键词。"
            
            # 格式化结果（保持不变）
            output = f"📚 知识检索结果 (找到 {len(results)} 条)\n"
            output += "="*40 + "\n\n"
            
            for i, item in enumerate(results, 1):
                output += f"{i}. 📖 {item['title']}\n"
                output += f"   {item['content']}\n"
                
                if item.get('category'):
                    output += f"   🏷️  类别: {item['category']}\n"
                
                if 'score' in item:
                    score_pct = item['score'] * 100
                    if score_pct > 80:
                        score_bar = "██████████"
                    elif score_pct > 60:
                        score_bar = "████████░░"
                    elif score_pct > 40:
                        score_bar = "██████░░░░"
                    else:
                        score_bar = "████░░░░░░"
                    output += f"   📊 相关度: {score_bar} {score_pct:.1f}%\n"
                
                output += "\n"
            
            # RAG 增强
            if len(results) > 0:
                try:
                    top_content = results[0]['content']
                    enhanced = await self._enhance_with_llm(query, top_content)
                    if enhanced:
                        output += f"\n🤖 LLM 补充分析:\n{enhanced}\n"
                except:
                    pass
            
            return output
            
        except Exception as e:
            logger.error(f"RAG 搜索失败: {e}")
            return f"⚠️ 搜索失败: {e}"

    # ============================================================
    # 修改 get_status 方法
    # ============================================================

    def get_status(self) -> Dict:
        """获取系统状态"""
        llm_status = self.llm.get_model_status()
        
        # ✅ 使用新的 stats 方法
        milvus_stats = self.milvus.get_stats() if self.milvus else {"available": False}
        
        memory_stats = self.memory.get_stats() if self.memory else {"enabled": False}
        
        return {
            "llm": llm_status,
            "milvus": milvus_stats,
            "memory": memory_stats,
            "device": "cuda" if torch.cuda.is_available() else "cpu",
            "privacy": {
                "enabled": self.privacy.enabled if self.privacy else False,
            }
        }
    
    async def _generate_knowledge_response(self, query: str) -> Optional[str]:
        """使用 LLM 生成知识回答（RAG 无结果时降级）"""
        try:
            prompt = f"""请基于你的知识回答以下问题。如果问题涉及ETF投资，请提供专业、准确的信息。

问题: {query}

回答:"""
            
            response = self.llm.generate_response(
                messages=[{"role": "user", "content": prompt}],
                max_new_tokens=300,
                temperature=0.7,
                enable_thinking=False
            )
            
            return response
        except Exception as e:
            logger.error(f"LLM 生成失败: {e}")
            return None
    
    async def _enhance_with_llm(self, query: str, context: str) -> Optional[str]:
        """使用 LLM 增强 RAG 结果"""
        try:
            prompt = f"""基于以下知识，对用户问题进行补充分析：

知识: {context}

用户问题: {query}

请用简洁专业的语言（50字以内）补充回答。"""

            response = self.llm.generate_response(
                messages=[{"role": "user", "content": prompt}],
                max_new_tokens=100,
                temperature=0.5,
                enable_thinking=False
            )
            
            return response
        except Exception as e:
            logger.error(f"LLM 增强失败: {e}")
            return None
    
    async def _get_quote(self, symbol: str) -> str:
        """获取ETF实时行情"""
        quote = self.fetcher.get_etf_quote(symbol)
        if not quote:
            return f"未找到ETF: {symbol}"
        
        return (
            f"📊 {quote['name']} ({symbol})\n"
            f"价格: {quote['price']:.3f}\n"
            f"涨跌幅: {quote['change']:+.2f}%\n"
            f"成交量: {quote['volume']:,.0f}\n"
            f"最高: {quote['high']:.3f}\n"
            f"最低: {quote['low']:.3f}\n"
            f"今开: {quote['open']:.3f}"
        )
    
    async def _get_recommendation(self, symbol: str) -> str:
        """获取投资建议"""
        df = self.fetcher.get_history(symbol)
        if df.empty:
            return f"无法获取 {symbol} 的数据"
        
        advice = self.advisor.get_recommendation(symbol, df)
        
        emoji = {'buy': '🟢', 'hold': '🟡', 'sell': '🔴', 'neutral': '⚪'}
        risk_emoji = {'low': '🟢', 'medium': '🟡', 'high': '🔴'}
        
        report = f"📈 {symbol} 投资建议\n"
        report += "="*50 + "\n\n"
        report += f"{emoji.get(advice['recommendation'], '⚪')} 建议: {advice['signal']}\n"
        report += f"评分: {advice['score']:.1f} (满分8分)\n"
        report += f"置信度: {advice['confidence']:.0%}\n"
        report += f"风险等级: {risk_emoji.get(advice['risk_level'], '⚪')} {advice['risk_level']}\n\n"
        
        report += "📊 分析依据:\n"
        for reason in advice['reasons']:
            report += f"  {reason}\n"
        
        if advice.get('target_price'):
            report += f"\n🎯 目标价: {advice['target_price']:.3f}\n"
        if advice.get('stop_loss'):
            report += f"🛑 止损价: {advice['stop_loss']:.3f}\n"
        
        report += f"\n⚠️ 风险提示: 投资有风险，决策需谨慎。"
        return report
    
    async def _get_prediction(self, symbol: str) -> str:
        """获取价格预测 - 使用LLM预测"""
        df = self.fetcher.get_history(symbol)
        if df.empty:
            return f"无法获取 {symbol} 的数据"
        
        # ✅ 使用 advisor.predict_with_llm（整合后的方法）
        pred = self.advisor.predict_with_llm(symbol, df)
        
        if pred.get('success', False):
            report = f"🔮 {symbol} 价格预测\n"
            report += "="*50 + "\n\n"
            report += f"预测变化: {pred.get('predicted_change', 0):.2%}\n"
            report += f"置信度: ±{pred.get('confidence', 0):.2%}\n"
            if pred.get('analysis'):
                report += f"\n📝 分析: {pred['analysis']}\n"
            report += "\n📅 预测价格 (前10天):\n"
            dates = pred.get('dates', [])[:10]
            closes = pred.get('close', [])[:10]
            for d, c in zip(dates, closes):
                report += f"  {d}: {c:.3f}\n"
            return report
        else:
            return f"预测失败: {pred.get('error', '未知错误')}"
    
    async def _analyze_technical(self, symbol: str) -> str:
        """技术分析"""
        df = self.fetcher.get_history(symbol, "6mo")
        if df.empty:
            return f"无法获取 {symbol} 的数据"
        
        advice = self.advisor.get_recommendation(symbol, df)
        tech = advice['technical']
        
        report = f"📊 {symbol} 技术分析\n"
        report += "="*40 + "\n"
        report += f"当前价格: {tech['price']:.3f}\n"
        report += f"趋势: {tech['trend']}\n"
        report += f"RSI: {tech['rsi']:.1f}\n"
        report += f"MACD: {tech['macd']:.4f}\n"
        report += f"MACD信号: {tech['macd_signal']:.4f}\n"
        report += f"MACD柱: {tech['macd_hist']:.4f}\n"
        report += f"MA5: {tech['ma5']:.3f}\n"
        report += f"MA20: {tech['ma20']:.3f}\n"
        report += f"MA60: {tech['ma60']:.3f}\n"
        report += f"布林上轨: {tech['bb_upper']:.3f}\n"
        report += f"布林中轨: {tech['bb_middle']:.3f}\n"
        report += f"布林下轨: {tech['bb_lower']:.3f}\n"
        
        return report
    
    async def _get_top_recommendations(self) -> str:
        """获取 Top 3 推荐"""
        etfs = self.fetcher.get_etf_list()
        top_results = self.advisor.get_top_recommendations(etfs)
        
        report = "📊 今日 Top 3 ETF 推荐\n"
        report += "="*60 + "\n\n"
        
        # 买入推荐
        if top_results['buy']:
            report += "🟢 Top 3 买入推荐\n"
            report += "-"*40 + "\n"
            for i, rec in enumerate(top_results['buy'], 1):
                report += f"{i}. {rec['symbol']}\n"
                report += f"   价格: {rec['current_price']:.3f} | 目标: {rec['target_price']:.3f}\n"
                report += f"   评分: {rec['score']:.1f}/8 | 风险: {rec['risk_level']}\n"
                report += f"   {rec['reasons'][0] if rec['reasons'] else ''}\n\n"
        
        # 持有推荐
        if top_results['hold']:
            report += "🟡 Top 3 持有推荐\n"
            report += "-"*40 + "\n"
            for i, rec in enumerate(top_results['hold'], 1):
                report += f"{i}. {rec['symbol']}\n"
                report += f"   价格: {rec['current_price']:.3f} | 目标: {rec['target_price']:.3f}\n"
                report += f"   评分: {rec['score']:.1f}/8 | 风险: {rec['risk_level']}\n\n"
        
        # 卖出推荐
        if top_results['sell']:
            report += "🔴 Top 3 卖出推荐\n"
            report += "-"*40 + "\n"
            for i, rec in enumerate(top_results['sell'], 1):
                report += f"{i}. {rec['symbol']}\n"
                report += f"   价格: {rec['current_price']:.3f} | 目标: {rec['target_price']:.3f}\n"
                report += f"   评分: {rec['score']:.1f}/8 | 风险: {rec['risk_level']}\n\n"
        
        report += "⚠️ 风险提示: 投资有风险，决策需谨慎。"
        return report
    
    async def _compare_etfs_str(self, symbols_str: str) -> str:
        """比较多个 ETF（字符串输入）"""
        symbol_list = [s.strip() for s in symbols_str.split(',')]
        
        report = "📊 ETF对比\n"
        report += "="*50 + "\n\n"
        report += "代码\t名称\t价格\t涨跌幅\t建议\n"
        
        for symbol in symbol_list[:5]:
            quote = self.fetcher.get_etf_quote(symbol)
            if quote:
                df = self.fetcher.get_history(symbol)
                if not df.empty:
                    advice = self.advisor.get_recommendation(symbol, df)
                    adv_emoji = {
                        'buy': '🟢买入',
                        'hold': '🟡持有',
                        'sell': '🔴卖出'
                    }.get(advice['recommendation'], '⚪观望')
                    report += f"{symbol}\t{quote['name'][:8]}\t{quote['price']:.3f}\t{quote['change']:+.2f}%\t{adv_emoji}\n"
        
        if report == "📊 ETF对比\n" + "="*50 + "\n\n" + "代码\t名称\t价格\t涨跌幅\t建议\n":
            return "无法获取任何 ETF 数据"
        
        return report
    
    async def _generate_report(self, symbol: str) -> str:
        """生成完整分析报告"""
        df = self.fetcher.get_history(symbol, "1y")
        if df.empty:
            return f"无法获取 {symbol} 的数据"
        
        quote = self.fetcher.get_etf_quote(symbol)
        advice = self.advisor.get_recommendation(symbol, df)
        pred = self.predictor.predict(df, use_ensemble=True)
        
        report = (
            f"📊 {symbol} 完整分析报告\n"
            f"{'='*50}\n\n"
            f"📈 行情信息\n"
            f"  名称: {quote['name'] if quote else symbol}\n"
            f"  价格: {quote['price']:.3f}\n"
            f"  涨跌幅: {quote['change']:+.2f}%\n\n"
            f"📊 技术指标\n"
            f"  趋势: {advice['technical']['trend']}\n"
            f"  RSI: {advice['technical']['rsi']:.1f}\n"
            f"  MACD柱: {advice['technical']['macd_hist']:.4f}\n\n"
            f"🎯 投资建议\n"
            f"  建议: {advice['signal']}\n"
            f"  评分: {advice['score']:.1f}/8\n"
            f"  风险: {advice['risk_level']}\n\n"
            f"🔮 价格预测\n"
            f"  预测变化: {pred.get('predicted_change', 0):.2%}\n"
            f"  目标价: {advice.get('target_price', 0):.3f}\n\n"
            f"⚠️ 风险提示: 投资有风险，决策需谨慎。"
        )
        return report
    
    async def _analyze_complete(self, symbol: str) -> str:
        """完整分析 - 多步骤任务规划"""
        steps = self.planner.plan(symbol, "full")
        results = []
        
        for step in steps:
            if step["name"] == "get_quote":
                result = await self._get_quote(symbol)
            elif step["name"] == "get_history":
                result = await self._get_history(symbol, "6mo")
            elif step["name"] == "analyze_technical":
                result = await self._analyze_technical(symbol)
            elif step["name"] == "predict_price":
                result = await self._get_prediction(symbol)
            elif step["name"] == "get_recommendation":
                # ✅ 使用 advisor.get_recommendation（内部已整合LLM）
                df = self.fetcher.get_history(symbol)
                if not df.empty:
                    advice = self.advisor.get_recommendation(symbol, df)
                    result = self._format_advice(advice)
                else:
                    result = "无法获取数据"
            elif step["name"] == "generate_report":
                result = await self._generate_report(symbol)
            else:
                result = f"未知步骤: {step['name']}"
            
            results.append(f"**{step['desc']}**\n{result}")
        
        report = f"📊 {symbol} 综合分析报告\n{'='*60}\n\n" + "\n\n".join(results)
        report += f"\n\n⚠️ 风险提示: 投资有风险，决策需谨慎。"
        return report
    
    def _format_advice(self, advice: Dict) -> str:
        """格式化投资建议"""
        if not advice:
            return "无法获取建议"
        
        emoji = {'buy': '🟢', 'hold': '🟡', 'sell': '🔴', 'neutral': '⚪'}
        risk_emoji = {'low': '🟢', 'medium': '🟡', 'high': '🔴'}
        
        report = f"{emoji.get(advice.get('recommendation', 'neutral'), '⚪')} 建议: {advice.get('signal', 'N/A')}\n"
        report += f"评分: {advice.get('score', 0):.1f}/8\n"
        report += f"置信度: {advice.get('confidence', 0):.0%}\n"
        report += f"风险等级: {risk_emoji.get(advice.get('risk_level', 'medium'), '⚪')} {advice.get('risk_level', 'N/A')}\n"
        report += f"目标价: {advice.get('target_price', 0):.3f}\n"
        report += f"止损价: {advice.get('stop_loss', 0):.3f}\n\n"
        report += "📊 分析依据:\n"
        for reason in advice.get('reasons', []):
            report += f"  {reason}\n"
        
        return report

    async def _get_history(self, symbol: str, period: str = "6mo") -> str:
        """获取历史数据"""
        df = self.fetcher.get_history(symbol, period)
        if df.empty:
            return f"无法获取 {symbol} 的历史数据"
        
        return (
            f"📈 {symbol} 历史数据 ({period})\n"
            f"交易日: {len(df)} 天\n"
            f"最新价: {df['close'].iloc[-1]:.3f}\n"
            f"最高价: {df['high'].max():.3f}\n"
            f"最低价: {df['low'].min():.3f}\n"
            f"均价: {df['close'].mean():.3f}"
        )
    
    async def _record_feedback(self, symbol: str, recommendation: str, actual_result: str, rating: int) -> str:
        """记录反馈"""
        self.feedback_learning.record_feedback(symbol, recommendation, actual_result, rating)
        return f"✅ 反馈已记录，感谢您的反馈！"