"""
Ollama 本地推理引擎 — 封装 Ollama HTTP API。
所有输入输出均为标准 JSON。
支持 System Prompt + Chat 消息。
"""
import os
import json
import urllib.request
from typing import Optional, Dict, Any, List


class OllamaEngine:
    """Ollama 本地推理引擎。通过 HTTP API 调用。"""

    def __init__(self, model_name: str, base_url: str = None):
        if base_url is None:
            base_url = os.environ.get("OLLAMA_HOST", "http://localhost:11434")
        # 清理引号和空白（环境变量可能带引号）
        base_url = base_url.strip().strip('"').strip("'").strip()
        # 确保有协议前缀
        if not base_url.startswith(("http://", "https://")):
            base_url = "http://" + base_url
        # 修复 0.0.0.0 和 [::] 地址（Ollama默认bind地址，客户端无法访问）
        base_url = base_url.replace("0.0.0.0", "127.0.0.1").replace("[::]", "127.0.0.1")
        # 移除尾斜杠
        base_url = base_url.rstrip("/")
        self.model = model_name
        self.base_url = base_url
        self.chat_url = f"{base_url}/api/chat"

    def chat(self, prompt: str, system_prompt: str = "",
             temperature: float = 0.3, max_tokens: int = 2048) -> str:
        """
        发送 Chat 请求，返回文本响应。
        
        Args:
            prompt: 用户消息
            system_prompt: 系统角色设定
            temperature: 温度参数 (0.0-1.0)
            max_tokens: 最大生成 token 数
        
        Returns:
            模型响应文本
        """
        messages: List[Dict[str, str]] = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        payload = json.dumps({
            "model": self.model,
            "messages": messages,
            "stream": False,
            "options": {
                "temperature": temperature,
                "num_predict": max_tokens,
            }
        }, ensure_ascii=False).encode("utf-8")

        req = urllib.request.Request(
            self.chat_url,
            data=payload,
            headers={"Content-Type": "application/json; charset=utf-8"}
        )

        try:
            print(f"[OllamaEngine] Sending request to {self.chat_url}")
            with urllib.request.urlopen(req, timeout=120) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            return data.get("message", {}).get("content", "")
        except Exception as e:
            import traceback
            print(f"[OllamaEngine] ERROR: {e}")
            traceback.print_exc()
            return json.dumps({
                "error": str(e),
                "model": self.model,
                "status": "ollama_call_failed"
            }, ensure_ascii=False)

    def chat_json(self, prompt: str, system_prompt: str = "",
                  temperature: float = 0.3, max_tokens: int = 2048) -> Optional[Dict[str, Any]]:
        """
        Chat 请求，强制解析 JSON 返回。失败返回 None。
        所有模块间通信均使用此方法。
        """
        raw = self.chat(prompt, system_prompt, temperature, max_tokens)
        # 尝试提取 JSON（模型可能在 JSON 前后输出额外文本）
        cleaned = self._extract_json(raw)
        try:
            return json.loads(cleaned)
        except json.JSONDecodeError:
            return {"_raw": raw, "_error": "json_parse_failed"}

    @staticmethod
    def _extract_json(text: str) -> str:
        """从文本中提取最长的 JSON 对象。"""
        start = text.find("{")
        end = text.rfind("}")
        if start >= 0 and end > start:
            return text[start:end + 1]
        return text

    def get_info(self) -> Dict[str, Any]:
        """获取模型信息（标准 JSON）。"""
        return {
            "model": self.model,
            "base_url": self.base_url,
            "role": "ollama_local_engine",
        }

    def to_json(self) -> str:
        """返回引擎状态的标准 JSON 字符串。"""
        return json.dumps(self.get_info(), ensure_ascii=False)
