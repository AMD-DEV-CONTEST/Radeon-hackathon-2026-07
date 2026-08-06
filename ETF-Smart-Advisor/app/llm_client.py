# app/llm_client.py
"""
统一 LLM 客户端 - 支持 vLLM（优先）和 Transformers（降级）
合并了 qwen_model.py 和 vllm_client.py 的所有功能

设计原则：
1. 单一入口：所有 LLM 调用统一通过 LLMClient
2. 自动降级：vLLM 不可用时自动切换到 Transformers
3. 接口兼容：完全兼容 qwen_model.py 的接口
4. 单例模式：全局共享一个实例
5. 配置驱动：所有配置从 config.py 读取
"""

import asyncio
import httpx
import torch
import logging
from typing import Optional, List, Dict, Any, Union
from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig, AutoConfig
import bitsandbytes
import requests
from .utils import format_exception


from .config import LLM_API_CONFIG

logger = logging.getLogger(__name__)


class LLMClient:
    """
    统一 LLM 客户端
    
    功能：
    - 优先使用 vLLM（高性能推理）
    - 降级使用 Transformers（直接加载）
    - 完全兼容 qwen_model.py 的接口
    """
    
    _instance = None
    _model = None
    _tokenizer = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance
    
    def __init__(self):
        if hasattr(self, '_initialized'):
            return
        
        self._initialized = True
        
        # ✅ 从配置读取 max_model_len
        self.max_model_len = LLM_API_CONFIG.get("max_model_len", 65536)
        
        # vLLM 配置
        vllm_config = LLM_API_CONFIG.get("vllm", {})
        self.model_path = LLM_API_CONFIG.get("model_path")
        self.enable_thinking = LLM_API_CONFIG.get("enable_thinking", False)
        
        # vLLM 配置
        self.use_vllm = vllm_config.get("enabled", True)
        self.vllm_host = vllm_config.get("host", "localhost")
        self.vllm_port = vllm_config.get("port", 8000)
        self.vllm_base_url = f"http://{self.vllm_host}:{self.vllm_port}"
        self.vllm_model_name = vllm_config.get("served_model_name", "qwen-model")
        self.vllm_timeout = 120.0  # ✅ 增加超时时间
        
        self.device = "cuda:0" if torch.cuda.is_available() else "cpu"

        # 状态
        self._vllm_available = None
        self._transformers_loaded = False
        self._max_seq_length = self.max_model_len
        
        logger.info(f"✅ LLM 客户端初始化完成")
        logger.info(f"   vLLM: {'启用' if self.use_vllm else '禁用'}")
        logger.info(f"   vLLM 端点: {self.vllm_base_url}")
        logger.info(f"   模型路径: {self.model_path}")
        logger.info(f"   最大上下文长度: {self.max_model_len}")
        logger.info(f"   目标设备: {self.device}")
        logger.info(f"   思考模式: {'开启' if self.enable_thinking else '关闭'}")
    
    # ============================================================
    # vLLM 相关方法
    # ============================================================
    
    async def check_vllm_health(self) -> bool:
        """检查 vLLM 服务是否可用"""
        if self._vllm_available is not None:
            return self._vllm_available
        
        if not self.use_vllm:
            self._vllm_available = False
            return False
        
        try:
            async with httpx.AsyncClient(timeout=3.0) as client:
                response = await client.get(f"{self.vllm_base_url}/health")
                self._vllm_available = response.status_code == 200
                if self._vllm_available:
                    logger.debug("vLLM 服务健康检查通过")
                else:
                    logger.warning(f"vLLM 服务返回异常状态码: {response.status_code}")
                return self._vllm_available
        except httpx.ConnectError:
            logger.warning(f"vLLM 服务连接失败: {self.vllm_base_url}")
            self._vllm_available = False
            return False
        except Exception as e:
            logger.warning(f"vLLM 健康检查异常: {e}\nTrackback:{format_exception(e)}")
            self._vllm_available = False
            return False
    
    async def _vllm_generate(
        self,
        messages: List[Dict[str, str]],
        max_tokens: int = 512,
        temperature: float = 0.7,
        top_p: float = 0.9,
        **kwargs
    ) -> Dict[str, Any]:
        """使用 vLLM 生成响应（异步）"""
        try:
            async with httpx.AsyncClient(timeout=self.vllm_timeout) as client:
                response = await client.post(
                    f"{self.vllm_base_url}/v1/chat/completions",
                    json={
                        "model": self.vllm_model_name,
                        "messages": messages,
                        "max_tokens": min(max_tokens, self.max_model_len // 10),  # ✅ 确保不超限
                        "temperature": temperature,
                        "top_p": top_p,
                        "stream": False,
                        **kwargs
                    }
                )
                
                if response.status_code == 200:
                    data = response.json()
                    return {
                        "success": True,
                        "response": data.get("choices", [{}])[0].get("message", {}).get("content", ""),
                        "usage": data.get("usage", {}),
                        "model": data.get("model", "vllm"),
                        "backend": "vllm"
                    }
                else:
                    error_msg = f"HTTP {response.status_code}: {response.text}"
                    logger.error(f"vLLM [{self.vllm_model_name}]请求失败: {error_msg}")
                    return {
                        "success": False,
                        "error": error_msg,
                        "response": "",
                        "backend": "vllm"
                    }
                    
        except httpx.TimeoutException:
            logger.error(f"vLLM 请求超时 ({self.vllm_timeout}s)")
            return {
                "success": False,
                "error": f"请求超时 ({self.vllm_timeout}s)",
                "response": "",
                "backend": "vllm"
            }
        except Exception as e:
            logger.error(f"vLLM 请求异常: {e}\nTrackback:{format_exception(e)}")
            return {
                "success": False,
                "error": str(e),
                "response": "",
                "backend": "vllm"
            }
    
    def _get_model_max_length(self) -> int:
        """获取模型最大序列长度"""
        try:
            # 从配置读取
            config_max_len = self.max_model_len
            
            # 尝试从模型配置获取
            try:
                config = AutoConfig.from_pretrained(self.model_path, trust_remote_code=True)
                
                # 检查各种可能的配置字段
                max_len = getattr(config, 'max_position_embeddings', None)
                if max_len is None:
                    max_len = getattr(config, 'max_sequence_length', None)
                if max_len is None:
                    max_len = getattr(config, 'n_positions', None)
                if max_len is None:
                    max_len = config_max_len
                
                # 取较小值，避免超出模型限制
                result = min(max_len, config_max_len)
                logger.info(f"   模型最大序列长度: {result}")
                return result
            except Exception as e:
                logger.warning(f"   无法从模型配置获取最大长度: {e}\nTrackback:{format_exception(e)}")
                return config_max_len
                
        except Exception as e:
            logger.warning(f"   获取模型最大长度失败: {e}\nTrackback:{format_exception(e)}")
            return self.max_model_len
    
    # ============================================================
    # Transformers 相关方法（降级方案）
    # ============================================================
    
    def _load_transformers_model(self):
        """加载 Transformers 模型（单例）"""
        if self._model is not None:
            return self._model, self._tokenizer
        
        logger.info(f"📥 加载 Transformers 模型: {self.model_path}")
        
        try:
            # 加载分词器
            self._tokenizer = AutoTokenizer.from_pretrained(
                self.model_path,
                trust_remote_code=True,
                use_fast=True
            )
            
            # 设置 padding token
            if self._tokenizer.pad_token is None:
                self._tokenizer.pad_token = self._tokenizer.eos_token
            
            self._max_seq_length = self._get_model_max_length()
            
            bnb_config = BitsAndBytesConfig(
                load_in_4bit=True,
                bnb_4bit_compute_dtype=torch.bfloat16,
                bnb_4bit_use_double_quant=True,
                bnb_4bit_quant_type="nf4"
            )
                        
            self._model = AutoModelForCausalLM.from_pretrained(
                self.model_path,
                trust_remote_code=True,
                dtype=torch.bfloat16,
                device_map="cuda:0",
                quantization_config=bnb_config,
                low_cpu_mem_usage=True,
            )
            
            self._transformers_loaded = True
            logger.info("✅ Transformers 模型加载完成")
            
            if hasattr(self._model, 'device'):
                logger.info(f"   模型主设备: {self._model.device}")
            
            total_params = sum(p.numel() for p in self._model.parameters())
            logger.info(f"   总参数: {total_params:,}")
            
            return self._model, self._tokenizer
            
        except Exception as e:
            logger.error(f"❌ Transformers 模型加载失败: {e}\nTrackback:{format_exception(e)}")
            raise
    
    def _transformers_generate(
        self,
        messages: List[Dict[str, str]],
        max_new_tokens: int = 512,
        temperature: float = 0.7,
        top_p: float = 0.9,
        **kwargs
    ) -> Dict[str, Any]:
        """使用 Transformers 生成（降级方案）"""
        try:
            model, tokenizer = self._load_transformers_model()
            
            # 应用 chat template
            text = tokenizer.apply_chat_template(
                messages,
                tokenize=False,
                add_generation_prompt=True,
                enable_thinking=self.enable_thinking
            )
            
            max_total_length = getattr(self, '_max_seq_length', self.max_model_len)
            
            # ✅ 确保不超过最大长度
            safe_max_tokens = min(max_new_tokens, max_total_length // 4)
            
            # Tokenize
            inputs = tokenizer(
                text, 
                return_tensors="pt",
                truncation=True,
                max_length=max_total_length - safe_max_tokens
            ).to(model.device)
                        
            # 生成
            with torch.no_grad():
                outputs = model.generate(
                    **inputs,
                    max_new_tokens=safe_max_tokens,
                    temperature=temperature,
                    top_p=top_p,
                    do_sample=temperature > 0,
                    pad_token_id=tokenizer.pad_token_id,
                    eos_token_id=tokenizer.eos_token_id,
                    use_cache=True,
                    num_beams=1,
                    **kwargs
                )
            
            # 解码
            response = tokenizer.decode(
                outputs[0][inputs['input_ids'].shape[1]:],
                skip_special_tokens=True
            )
            
            return {
                "success": True,
                "response": response,
                "backend": "transformers",
                "tokens_generated": outputs.shape[1] - inputs['input_ids'].shape[1]
            }
            
        except Exception as e:
            logger.error(f"Transformers 推理失败: {e}\nTrackback:{format_exception(e)}")
            return {
                "success": False,
                "error": str(e),
                "response": "",
                "backend": "transformers"
            }
    
    # ============================================================
    # 统一公共接口
    # ============================================================
    
    def generate_response(
        self,
        messages: List[Dict[str, str]],
        max_new_tokens: int = 512,
        temperature: float = 0.7,
        top_p: float = 0.9,
        enable_thinking: Optional[bool] = None,
        **kwargs
    ) -> str:
        """
        生成回复 - 统一接口
        
        优先使用 vLLM，失败时降级到 Transformers
        """
        # 覆盖思考模式设置
        if enable_thinking is not None:
            original_thinking = self.enable_thinking
            self.enable_thinking = enable_thinking
        
        try:
            # ✅ 确保不超过最大长度
            safe_max_tokens = min(max_new_tokens, self.max_model_len // 4)
            
            # 尝试 vLLM
            if self.use_vllm:
                try:
                    loop = asyncio.get_event_loop()
                    if loop.is_running():
                        import concurrent.futures
                        with concurrent.futures.ThreadPoolExecutor() as executor:
                            future = executor.submit(
                                asyncio.run,
                                self._vllm_generate(
                                    messages=messages,
                                    max_tokens=safe_max_tokens,
                                    temperature=temperature,
                                    top_p=top_p,
                                    **kwargs
                                )
                            )
                            result = future.result(timeout=self.vllm_timeout + 5)
                    else:
                        result = asyncio.run(self._vllm_generate(
                            messages=messages,
                            max_tokens=safe_max_tokens,
                            temperature=temperature,
                            top_p=top_p,
                            **kwargs
                        ))
                except RuntimeError:
                    result = asyncio.run(self._vllm_generate(
                        messages=messages,
                        max_tokens=safe_max_tokens,
                        temperature=temperature,
                        top_p=top_p,
                        **kwargs
                    ))
                except Exception as e:
                    logger.warning(f"vLLM 调用异常: {e}\nTrackback:{format_exception(e)}")
                    result = {"success": False, "error": str(e)}
                
                if result.get('success'):
                    return result.get('response', '')
                
                logger.warning(f"vLLM 失败，降级到 Transformers: {result.get('error')}")
            
            # ✅ 降级到 Transformers（已启用）
            logger.info("Starting Transformers")
            result = self._transformers_generate(
                messages=messages,
                max_new_tokens=safe_max_tokens,
                temperature=temperature,
                top_p=top_p,
                **kwargs
            )
            
            if result.get('success'):
                return result.get('response', '')
            else:
                return f"生成失败: {result.get('error', '未知错误')}"
                
        finally:
            if enable_thinking is not None:
                self.enable_thinking = original_thinking
    
    def chat(
        self,
        user_message: str,
        system_prompt: Optional[str] = None,
        history: Optional[List[Dict[str, str]]] = None,
        max_new_tokens: int = 512,
        temperature: float = 0.7,
        top_p: float = 0.9,
        **kwargs
    ) -> Dict[str, Any]:
        """聊天接口"""
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        if history:
            messages.extend(history)
        messages.append({"role": "user", "content": user_message})
        
        try:
            response = self.generate_response(
                messages=messages,
                max_new_tokens=max_new_tokens,
                temperature=temperature,
                top_p=top_p,
                **kwargs
            )
            
            return {
                "success": True,
                "response": response,
                "messages": messages
            }
        except Exception as e:
            logger.error(f"Chat 失败: {e}\nTrackback:{format_exception(e)}")
            return {
                "success": False,
                "error": str(e),
                "response": f"生成失败: {e}\nTrackback:{format_exception(e)}",
                "messages": messages
            }
    
    def generate_with_system_prompt(
        self,
        user_message: str,
        system_prompt: Optional[str] = None,
        max_new_tokens: int = 512,
        temperature: float = 0.7,
        top_p: float = 0.9,
        **kwargs
    ) -> str:
        """带系统提示的生成"""
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": user_message})
        
        return self.generate_response(
            messages=messages,
            max_new_tokens=max_new_tokens,
            temperature=temperature,
            top_p=top_p,
            **kwargs
        )
    
    # ============================================================
    # 模型状态方法
    # ============================================================
    
    def get_model_status(self) -> Dict[str, Any]:
        """获取模型状态"""
        vllm_available = False
        if self.use_vllm:
            try:
                response = requests.get(f"{self.vllm_base_url}/health", timeout=2)
                print(f"[get_model_status] vLLM 状态: {response.status_code}")
                vllm_available = response.status_code == 200
            except:
                vllm_available = False
        
        status = {
            "vllm_available": vllm_available,
            "transformers_loaded": self._transformers_loaded,
            "use_vllm": self.use_vllm,
            "model_path": self.model_path,
            "max_model_len": self.max_model_len,
            "enable_thinking": self.enable_thinking,
            "vllm_endpoint": self.vllm_base_url if self.use_vllm else None,
        }
        
        if self._model is not None:
            status["device"] = str(self._model.device)
            status["device_type"] = "cuda" if torch.cuda.is_available() else "cpu"
        
        return status
    
    def is_available(self) -> bool:
        """检查 LLM 是否可用"""
        if self.use_vllm:
            try:
                vllm_ok = asyncio.run(self.check_vllm_health())
                if vllm_ok:
                    return True
            except:
                pass
        
        try:
            self._load_transformers_model()
            return True
        except:
            return False
    
    # ============================================================
    # 配置管理
    # ============================================================
    
    def set_vllm_enabled(self, enabled: bool):
        self.use_vllm = enabled
        self._vllm_available = None
        logger.info(f"vLLM 已{'启用' if enabled else '禁用'}")
    
    def set_vllm_endpoint(self, host: str, port: int):
        self.vllm_host = host
        self.vllm_port = port
        self.vllm_base_url = f"http://{host}:{port}"
        self._vllm_available = None
        logger.info(f"vLLM 端点已更新: {self.vllm_base_url}")
    
    # ============================================================
    # 便捷方法
    # ============================================================
    
    def generate(
        self,
        prompt: str,
        max_new_tokens: int = 512,
        temperature: float = 0.7,
        top_p: float = 0.9,
        **kwargs
    ) -> str:
        """简化的生成方法"""
        return self.generate_response(
            messages=[{"role": "user", "content": prompt}],
            max_new_tokens=max_new_tokens,
            temperature=temperature,
            top_p=top_p,
            **kwargs
        )
    
    def generate_with_context(
        self,
        context: str,
        question: str,
        max_new_tokens: int = 512,
        **kwargs
    ) -> str:
        """带上下文的生成"""
        prompt = f"""基于以下信息回答问题：

上下文:
{context}

问题: {question}

回答:"""
        
        return self.generate(prompt, max_new_tokens, **kwargs)


# ============================================================
# 全局单例获取函数
# ============================================================

def get_llm_client() -> LLMClient:
    """获取 LLM 客户端单例"""
    return LLMClient()


# 兼容旧代码
get_qwen_model = get_llm_client
QwenModel = LLMClient
get_vllm_client = get_llm_client
VLLMClient = LLMClient


__all__ = [
    'LLMClient',
    'get_llm_client',
    'QwenModel',
    'get_qwen_model',
    'VLLMClient',
    'get_vllm_client',
]