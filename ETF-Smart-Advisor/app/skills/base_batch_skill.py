# app/skills/base_batch_skill.py
"""
Base Batch Skill with Milvus caching support
"""

import threading
import time
import re
import json
import gc
from typing import Dict, List, Any, Optional, Callable, Iterator, Set
from concurrent.futures import ThreadPoolExecutor, as_completed, TimeoutError
from queue import Queue, Empty
from tqdm import tqdm
from abc import abstractmethod
from datetime import datetime
import pandas as pd

from .base_skill import BaseSkill
from ..llm_client import get_llm_client
from ..config import LLM_API_CONFIG
from ..milvus_client import get_milvus_client
from pymilvus import DataType
from ..utils import format_exception


class BaseBatchSkill(BaseSkill):
    """
    Batch processing skill base class with memory optimization and Milvus caching
    """
    _execution_lock = threading.Lock()
    
    def __init__(
        self,
        name: str,
        description: str,
        batch_size: int = 15,
        max_workers: int = 4,
        timeout: int = 60,
        output_tokens: int = 400*2,
        safety_margin: float = 0.75,
        enable_cache: bool = True,
        parallel_batches: int = 2
    ):
        super().__init__(name, description)
        
        self.llm = get_llm_client()
        self.batch_size = batch_size
        self.max_workers = max_workers
        self.timeout = timeout
        self.output_tokens = output_tokens
        self.safety_margin = safety_margin
        self.enable_cache = enable_cache
        self.parallel_batches = parallel_batches
        
        # 从 config 读取 max_model_len
        self.max_model_len = LLM_API_CONFIG.get("max_model_len", 65536)
        vllm_config = LLM_API_CONFIG.get("vllm", {})
        self.vllm_max_model_len = vllm_config.get("max_model_len", self.max_model_len)
        self.max_context_tokens = min(self.max_model_len, self.vllm_max_model_len)
        
        # 计算安全可用 tokens
        self.available_tokens = int(self.max_context_tokens * self.safety_margin) - self.output_tokens
        if self.available_tokens < 1000:
            self.available_tokens = 1000
        
        # 实际限制（更保守）
        self.actual_limit = int(self.available_tokens * 0.85)
        
        print(f"   📊 Max context: {self.max_context_tokens}, Available: {self.available_tokens}")
        print(f"   📊 Actual limit: {self.actual_limit}")
        print(f"   🚀 Consumer threads: {self.parallel_batches}")
        
        # Initialize tokenizer
        self._init_token_counter()
        
        self._lock = threading.Lock()
        self._results = []
        self._progress = 0
        
        # 内存优化：数据缓存管理
        self._data_cache = {}
        self._cache_lock = threading.Lock()
        self._max_cache_size = 100
        
        # 存储所有加载的数据（用于后续过滤）
        self._all_loaded_data = {}
        self._keep_symbols = set()
        
        # Milvus 缓存
        if self.enable_cache:
            try:
                self._milvus = get_milvus_client()
                self._cache_available = self._milvus.recommendation is not None
                if self._cache_available:
                    print(f"   ✅ Milvus cache enabled")
                else:
                    print(f"   ⚠️ Milvus cache not available")
                    self.enable_cache = False
            except Exception as e:
                print(f"   ⚠️ Milvus init failed: {e}, cache disabled")
                self.enable_cache = False
                self._milvus = None

    def _init_token_counter(self):
        """初始化 token 计数器"""
        self._token_counter = None
        try:
            import tiktoken
            self._token_counter = tiktoken.get_encoding("cl100k_base")
        except ImportError:
            try:
                from transformers import AutoTokenizer
                self._token_counter = AutoTokenizer.from_pretrained("gpt2")
            except:
                pass
        except:
            pass
    
    def _count_tokens(self, text: str) -> int:
        """Count tokens in text - 使用多种方法"""
        if not text:
            return 0
        
        if self._token_counter is not None:
            try:
                if hasattr(self._token_counter, 'encode'):
                    return len(self._token_counter.encode(text))
            except:
                pass
        
        return len(text) // 4 + 1
        
    def _extract_json(self, response: str) -> Optional[Dict]:
        """从响应中提取 JSON - 支持不完整JSON"""
        if not response:
            return None
        
        # ✅ 确保 response 是字符串
        if not isinstance(response, str):
            response = str(response) if response is not None else ''
        
        try:
            return json.loads(response.strip())
        except:
            pass
        
        try:
            start = response.find('{')
            if start == -1:
                return None
            
            brace_count = 0
            last_complete_end = -1
            for i in range(start, len(response)):
                char = response[i]
                if char == '{':
                    brace_count += 1
                elif char == '}':
                    brace_count -= 1
                    if brace_count == 0:
                        last_complete_end = i
            
            if last_complete_end != -1:
                json_str = response[start:last_complete_end+1]
                try:
                    return json.loads(json_str)
                except:
                    pass
        except:
            pass
        
        try:
            start = response.find('{')
            if start == -1:
                return None
            
            partial = response[start:]
            
            if partial.startswith('{'):
                if partial.count('[') > partial.count(']'):
                    partial += ']'
                if partial.count('{') > partial.count('}'):
                    partial += '}'
                if partial.count('"') % 2 != 0:
                    partial += '"'
                
                try:
                    return json.loads(partial)
                except:
                    pass
        except:
            pass
        
        return None
    
    def _extract_json_array(self, response: str) -> Optional[List]:
        if not response:
            return None
        try:
            json_match = re.search(r'\[[\s\S]*\]', response)
            if json_match:
                return json.loads(json_match.group())
        except:
            pass
        return None
    
    def _parse_json_response(self, response: str, key: str = None) -> Optional[Any]:
        if not response:
            return None
        
        cleaned = response.strip()
        
        try:
            data = json.loads(cleaned)
            if key:
                return data.get(key)
            return data
        except:
            pass
        
        try:
            data = self._extract_json(cleaned)
            if data:
                if key:
                    return data.get(key)
                return data
        except:
            pass
        
        try:
            data = self._extract_json_array(cleaned)
            if data:
                return data
        except:
            pass
        
        return None
    
    def _is_milvus_available(self) -> bool:
        return (self.enable_cache and 
            self._milvus is not None and 
            hasattr(self._milvus, '_client') and 
            self._milvus._client is not None)
   
    def _get_cache_key(self) -> str:
        return self.name
    
    def _get_cached_result(self, symbol: str) -> Optional[Dict]:
        if not self.enable_cache or self._milvus is None:
            return None
        
        try:
            cache_type = self._get_cache_key()
            return self._milvus.recommendation.get(symbol, cache_type)
        except Exception as e:
            return None
    
    def _save_cached_result(self, symbol: str, latest_date: str, result: Dict):
        if not self.enable_cache or self._milvus is None:
            return
        
        try:
            cache_type = self._get_cache_key()
            self._milvus.recommendation.save(symbol, cache_type, latest_date, result)
        except Exception as e:
            pass
    
    def _check_cache_for_item(self, symbol: str, data: Any) -> tuple[Optional[Dict], bool]:
        if not self._is_milvus_available():
            return None, False
        
        latest_date = self._get_data_latest_date(data)
        if not latest_date:
            return None, False
        
        cached = self._get_cached_result(symbol)
        if cached and cached.get("latest_date") == latest_date:
            return cached.get("result"), True
        
        return None, False
    
    def _get_data_latest_date(self, data: Any) -> Optional[str]:
        """获取数据的最新日期"""
        if data is None:
            return None
        
        try:
            # ✅ 使用 pandas 的安全检查
            if isinstance(data, pd.DataFrame):
                if data.empty:
                    return None
                if isinstance(data.index, pd.DatetimeIndex):
                    return data.index[-1].strftime('%Y-%m-%d')
                if 'date' in data.columns:
                    # ✅ 确保取到的值不是 Series
                    date_val = data['date'].iloc[-1]
                    if hasattr(date_val, 'strftime'):
                        return date_val.strftime('%Y-%m-%d')
                    return str(date_val)
        except Exception as e:
            print(f"      ⚠️ _get_data_latest_date error: {e}\nTrackback:{format_exception(e)}")
        
        return None
    
    # ============================================================
    # 生产者-消费者模式：生成批次 + 并发处理
    # ============================================================
    
    def _streaming_process(
        self, 
        items: List[Any], 
        data_loader: Callable,
        **kwargs
    ) -> List[Dict]:
        """
        生产者-消费者模式：
        - 主线程：遍历 items，生成批次，放入队列
        - 消费者线程：从队列获取批次，调用 LLM 处理
        """
        # 结果收集
        all_results = []
        all_loaded_data = {}
        results_lock = threading.Lock()
        
        # 批次队列
        batch_queue = Queue()
        stop_event = threading.Event()  # 停止信号
        
        # 统计
        total_batches = 0
        processed_batches = 0
        cached_results = []
        
        # ============================================================
        # 消费者线程函数
        # ============================================================
        def consumer_worker():
            nonlocal processed_batches, all_results, cached_results
            
            while not stop_event.is_set():
                try:
                    # 从队列获取批次（超时 0.5 秒，以便检查停止信号）
                    batch = batch_queue.get(timeout=0.5)
                    
                    # 检查是否是停止信号
                    if batch is None:
                        batch_queue.task_done()
                        break
                    
                    # 处理批次
                    try:
                        batch_results = self._process_single_batch(batch, kwargs)
                        
                        with results_lock:
                            if batch_results:
                                all_results.extend(batch_results)
                            processed_batches += 1
                            
                    except Exception as e:
                        print(f"   ⚠️ Consumer error: {e}\nTrackback:{format_exception(e)}")
                    finally:
                        batch_queue.task_done()
                        
                except Empty:
                    # 队列为空，继续等待
                    continue
                except Exception as e:
                    print(f"   ⚠️ Consumer worker error: {e}\nTrackback:{format_exception(e)}")
                    continue
        
        # ============================================================
        # 生产者：遍历 items，生成批次
        # ============================================================
        print(f"   📝 Producer: Building batches from {len(items)} items...")
        
        base_prompt = self._get_base_prompt()
        base_tokens = self._count_tokens(base_prompt)
        
        current_symbols = []
        current_data = {}
        current_prompts = []
        current_tokens = base_tokens + self.output_tokens
        
        total_items = len(items)
        cache_hits = 0
        
        with tqdm(total=total_items, desc="Building batches", unit="items") as pbar:
            for item in items:
                symbol = self._get_symbol(item)
                if not symbol:
                    pbar.update(1)
                    continue
                
                # 加载数据
                if symbol in self._data_cache:
                    data = self._data_cache[symbol]
                else:
                    data = data_loader(symbol)
                    if data is None:
                        pbar.update(1)
                        continue
                    with self._cache_lock:
                        if len(self._data_cache) < self._max_cache_size:
                            self._data_cache[symbol] = data
                
                all_loaded_data[symbol] = data
                
                # 检查缓存
                cached_result, hit = self._check_cache_for_item(symbol, data)
                if hit and cached_result is not None:
                    cache_hits += 1
                    cached_results.append(cached_result)
                    pbar.update(1)
                    continue
                
                # 生成 prompt 片段
                prompt_piece = self._get_item_data_str_for_item(item, data, **kwargs)
                piece_tokens = self._count_tokens(prompt_piece)
                
                # 检查是否超过限制
                if current_tokens + piece_tokens > self.actual_limit and current_symbols:
                    # 将当前批次放入队列
                    batch = {
                        'symbols': current_symbols.copy(),
                        'data_map': current_data.copy(),
                        'prompts': current_prompts.copy(),
                        'tokens': current_tokens,
                        'batch_id': total_batches
                    }
                    batch_queue.put(batch)
                    total_batches += 1
                    
                    # 开始新批次
                    current_symbols = [symbol]
                    current_data = {symbol: data}
                    current_prompts = [prompt_piece]
                    current_tokens = base_tokens + self.output_tokens + piece_tokens
                else:
                    current_symbols.append(symbol)
                    current_data[symbol] = data
                    current_prompts.append(prompt_piece)
                    current_tokens += piece_tokens
                
                pbar.update(1)
            
            # 保存最后一个批次
            if current_symbols:
                batch = {
                    'symbols': current_symbols.copy(),
                    'data_map': current_data.copy(),
                    'prompts': current_prompts.copy(),
                    'tokens': current_tokens,
                    'batch_id': total_batches
                }
                batch_queue.put(batch)
                total_batches += 1
        
        print(f"   📊 Generated {total_batches} batches, cache hits: {cache_hits}")
        
        # ============================================================
        # 启动消费者线程
        # ============================================================
        print(f"   🚀 Starting {self.parallel_batches} consumer threads...")
        
        consumers = []
        for i in range(self.parallel_batches):
            t = threading.Thread(target=consumer_worker, name=f"Consumer-{i}")
            t.daemon = True
            t.start()
            consumers.append(t)
        
        # 等待所有批次处理完成
        batch_queue.join()
        
        # 发送停止信号
        stop_event.set()
        
        # 等待所有消费者线程退出
        for t in consumers:
            t.join(timeout=5)
        
        print(f"   ✅ Processed {processed_batches} batches")
        
        # 合并缓存结果
        if cached_results:
            all_results.extend(cached_results)
        
        # 更新选中的 symbols
        selected_symbols = {r.get('symbol') for r in all_results if r.get('symbol')}
        
        # 过滤保留的数据
        self._all_loaded_data = {
            symbol: data for symbol, data in all_loaded_data.items()
            if symbol in selected_symbols
        }
        self._keep_symbols = selected_symbols
        
        print(f"   📊 Selected {len(selected_symbols)} symbols, kept {len(self._all_loaded_data)} data items")
        
        gc.collect()
        
        return all_results
    
    def _process_single_batch(
        self, 
        batch: Dict[str, Any], 
        kwargs: Dict
    ) -> List[Dict]:
        """处理单个批次（线程安全）"""
        symbols = batch['symbols']
        data_map = batch['data_map']
        prompts = batch['prompts']
        batch_id = batch.get('batch_id', 0)
        
        try:
            timer0=time.time()
            prompt = self._build_batch_prompt(prompts, symbols, **kwargs)
            
            # ✅ 确保 prompt 是字符串
            if not isinstance(prompt, str):
                print(f"   ⚠️ Batch {batch_id}: Prompt is not a string")
                return []
            
            response = self.llm.generate_response(
                messages=[{"role": "user", "content": prompt}],
                max_new_tokens=self.output_tokens,
                temperature=0.3,
                enable_thinking=False
            )
            
            if response is None or len(str(response).strip()) < 20:
                print(f"   ⚠️ Batch {batch_id}: Empty or invalid response")
                return []
            
            # ✅ 确保 response 是字符串
            if not isinstance(response, str):
                response = str(response) if response is not None else ''
            
            results = self._parse_response(response, symbols)
            
            if results:
                for r in results:
                    symbol = r.get('symbol')
                    if symbol:
                        data = data_map.get(symbol)
                        if data is not None:  # ✅ 使用 is not None
                            latest_date = self._get_data_latest_date(data)
                            if latest_date:
                                self._save_cached_result(symbol, latest_date, r)
                print(f"   ✅ Batch {batch_id}: Processed {len(results)} results. time taken: {time.time()-timer0:.2f}s")
                return results
            else:
                print(f"   ✅ Batch {batch_id}: Processed 0 results. time taken: {time.time()-timer0:.2f}s")
                return []
            
        except Exception as e:
            # ✅ 捕获并打印详细的错误信息
            error_msg = str(e)
            if "DataFrame" in error_msg or "ambiguous" in error_msg:
                print(f"   ⚠️ Batch {batch_id}: DataFrame ambiguity error - check data types")
                import traceback
                traceback.print_exc()
            else:
                print(f"   ⚠️ Batch {batch_id} processing error: {e}\nTrackback:{format_exception(e)}")
            return []
    
    def _build_batch_prompt(self, prompts: List[str], symbols: List[str], **kwargs) -> str:
        """构建批次 prompt，子类可重写"""
        return f"""Analyze the following {len(prompts)} ETFs' raw OHLCV data.

Data format: Symbol|Date|O|H|L|C|V

Data:
{"\n".join(prompts)}

Output JSON ONLY (no other text):
{{
    "scores": [
        {{"symbol": "Symbol", "score": 0-100 integer, "signal": "buy/hold/sell", "reason": "short reason"}}
    ]
}}"""
    
    def _parse_response(self, response: str, batch_symbols: List[str] = None) -> List[Dict]:
        """Parse LLM response with symbol matching"""
        results = []
        
        try:
            data = self._extract_json(response)
            if data:
                # 尝试获取 scores（ETFAnalyzeSkill 格式）
                scores = data.get('scores', [])
                if scores:
                    for idx, item in enumerate(scores):
                        if not item.get('symbol') and batch_symbols and idx < len(batch_symbols):
                            item['symbol'] = batch_symbols[idx]
                        if item.get('symbol'):
                            if 'score' in item:
                                try:
                                    item['score'] = int(item['score'])
                                except (ValueError, TypeError):
                                    item['score'] = 50
                            results.append(item)
                    if results:
                        return results
                
                # 尝试获取 rankings（ETFRankingSkill 格式）
                rankings = data.get('rankings', [])
                if rankings:
                    for idx, item in enumerate(rankings):
                        if not item.get('symbol') and batch_symbols and idx < len(batch_symbols):
                            item['symbol'] = batch_symbols[idx]
                        if item.get('symbol'):
                            if 'rank_score' in item:
                                try:
                                    item['score'] = int(item['rank_score'])
                                except (ValueError, TypeError):
                                    item['score'] = 50
                            results.append(item)
                    if results:
                        return results
                
                # 如果是单个对象（ETFDeepAnalyzeSkill 格式）
                if 'symbol' in data and 'deep_score' in data:
                    data['score'] = data.get('deep_score', 50)
                    if not data.get('signal'):
                        data['signal'] = data.get('recommendation', 'hold')
                    return [data]
                
        except Exception as e:
            print(f'  ⚠️ Error parsing response: {e}\nTrackback:{format_exception(e)}')
        
        # 从 JSON 对象中提取完整条目
        try:
            object_pattern = r'\{[^{}]*"symbol"[^{}]*"score"[^{}]*\}'
            matches = re.findall(object_pattern, response)
            
            for match in matches:
                try:
                    item = json.loads(match)
                    if item.get('symbol') and 'score' in item:
                        try:
                            item['score'] = int(item['score'])
                        except (ValueError, TypeError):
                            item['score'] = 50
                        results.append(item)
                except:
                    continue
            
            if results:
                return results
        except Exception as e:
            print(f'  ⚠️ Error parsing response: {e}\nTrackback:{format_exception(e)}')
        
        # 正则提取 fallback
        if batch_symbols:
            symbol_pattern = r'"symbol"\s*:\s*"([^"]+)"'
            score_pattern = r'"score"\s*:\s*([-+]?\d+)'
            
            symbols_found = re.findall(symbol_pattern, response)
            scores_found = re.findall(score_pattern, response)
            
            if symbols_found:
                count = min(len(symbols_found), len(batch_symbols))
                for i in range(count):
                    symbol = symbols_found[i]
                    if len(symbol) >= 4:
                        try:
                            score_val = int(scores_found[i]) if i < len(scores_found) else 50
                        except (ValueError, TypeError):
                            score_val = 50
                        
                        results.append({
                            'symbol': symbol,
                            'score': score_val,
                            'signal': 'hold',
                            'reason': 'Parsed from response'
                        })
                
                if results:
                    return results
        
        return results
    
    # ============================================================
    # 内存管理方法
    # ============================================================
    
    def _update_cache_with_selected(self, batch: List[str], selected_symbols: Set[str]):
        with self._cache_lock:
            for sym in batch:
                if sym not in selected_symbols:
                    if sym in self._data_cache:
                        del self._data_cache[sym]
    
    def clear_cache(self):
        with self._cache_lock:
            self._data_cache.clear()
        self._all_loaded_data = {}
        self._keep_symbols = set()
        gc.collect()
    
    def get_loaded_data(self, symbol: str) -> Optional[Any]:
        return self._all_loaded_data.get(symbol) if hasattr(self, '_all_loaded_data') else None
    
    def get_all_loaded_data(self) -> Dict[str, Any]:
        return getattr(self, '_all_loaded_data', {})
    
    def get_keep_symbols(self) -> Set[str]:
        return getattr(self, '_keep_symbols', set())
    
    # ============================================================
    # Abstract methods
    # ============================================================
    
    @abstractmethod
    def _get_base_prompt(self) -> str:
        pass
    
    @abstractmethod
    def _get_item_data_str_for_item(self, item: Any, data: Any, **kwargs) -> str:
        pass
    
    @abstractmethod
    def _load_item_data(self, symbol: str, **kwargs) -> Optional[Any]:
        pass
    
    @abstractmethod
    def _create_item_from_data(self, symbol: str, data: Any) -> Optional[Dict]:
        pass
    
    @abstractmethod
    def _process_batch(self, batch: List[Any], **kwargs) -> List[Dict]:
        pass
    
    @abstractmethod
    def _fallback(self, batch: List[Any], **kwargs) -> List[Dict]:
        pass
    
    # ============================================================
    # Optional override methods
    # ============================================================
    
    def _preprocess(self, items: List[Any], **kwargs) -> List[Any]:
        return items
    
    def _postprocess(self, results: List[Dict], **kwargs) -> List[Dict]:
        return results
    
    def _sort_results(self, results: List[Dict]) -> List[Dict]:
        def get_score(item):
            score = item.get('score', 0)
            try:
                return int(score)
            except (ValueError, TypeError):
                return 0
        return sorted(results, key=get_score, reverse=True)
    
    def _get_symbol(self, item: Any) -> str:
        if isinstance(item, str):
            return item
        elif isinstance(item, dict):
            return item.get('symbol', '')
        return ''
    
    # ============================================================
    # Main execution method
    # ============================================================
    
    def execute(self, items: List[Any], keep_count: int = None, **kwargs) -> List[Dict]:
        if not items:
            return []
        
        print(f"   📊 Processing {len(items)} items...")
        start_time = time.time()
        
        with BaseBatchSkill._execution_lock:
            processed = self._preprocess(items, **kwargs)
            
            def data_loader(symbol: str):
                return self._load_item_data(symbol, **kwargs)
            
            results = self._streaming_process(processed, data_loader, **kwargs)
            
            results = self._postprocess(results, **kwargs)
            results = self._sort_results(results)
            
            if keep_count is not None:
                results = results[:keep_count]
            
            final_keep_symbols = {r.get('symbol') for r in results if r.get('symbol')}
            self._all_loaded_data = {
                sym: data for sym, data in self._all_loaded_data.items()
                if sym in final_keep_symbols
            }
            self._keep_symbols = final_keep_symbols
            
            elapsed = time.time() - start_time
            print(f"      ✅ Completed, time used {elapsed:.2f}s, retained {len(results)} items")
            print(f"      📊 Final data cache size: {len(self._all_loaded_data)} items")
            
            return results
    
    def _load_item_data(self, symbol: str, **kwargs) -> Optional[Any]:
        return None
    
    async def execute_async(self, items: List[Any], keep_count: int = None, **kwargs) -> List[Dict]:
        import asyncio
        if not items:
            return []
        
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None, self.execute, items, keep_count, **kwargs
        )