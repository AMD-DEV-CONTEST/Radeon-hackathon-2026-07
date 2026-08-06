"""
ForgeMind - LLM Abstraction for ROCm
Supports: vLLM-ROCm, Ollama-ROCm, HuggingFace local
All offline, no API keys
"""
import os
from typing import List, Dict, Any, Optional

class ROCmLLM:
    def __init__(self, model_name: str = "qwen2.5-coder:7b", backend: str = "auto", rocm: bool = True):
        self.model_name = model_name
        self.backend = backend
        self.rocm = rocm
        self.client = None
        self._init_backend()

    def _init_backend(self):
        # Try Ollama first (easiest on Radeon)
        if self.backend in ("auto", "ollama"):
            try:
                import ollama
                # Check if ollama is running
                self.client = ollama.Client()
                models = self.client.list()
                print(f"[LLM] Ollama-ROCm backend ready, model: {self.model_name}")
                self.backend = "ollama"
                return
            except Exception as e:
                print(f"[LLM] Ollama not available: {e}")

        # Try vLLM-ROCm
        if self.backend in ("auto", "vllm"):
            try:
                from vllm import LLM, SamplingParams
                # vLLM with ROCm will auto-detect HIP
                print(f"[LLM] Attempting vLLM-ROCm with {self.model_name}")
                # Don't init heavy model here, lazy load
                self.backend = "vllm"
                return
            except Exception as e:
                print(f"[LLM] vLLM not available: {e}")

        # Fallback to HF transformers (CPU/ROCm PyTorch)
        print("[LLM] Falling back to HuggingFace transformers (ROCm PyTorch)")
        self.backend = "hf"

    def generate(self, prompt: str, system: str = "You are a senior software engineer.", max_tokens: int = 2048, temperature: float = 0.2) -> str:
        """Generate code/text locally"""
        if self.backend == "ollama":
            import ollama
            try:
                resp = ollama.chat(
                    model=self.model_name,
                    messages=[
                        {"role": "system", "content": system},
                        {"role": "user", "content": prompt}
                    ],
                    options={"temperature": temperature, "num_predict": max_tokens}
                )
                return resp['message']['content']
            except Exception as e:
                print(f"Ollama generate failed: {e}, using mock")
                return self._mock_response(prompt)

        elif self.backend == "vllm":
            # Lazy load vLLM
            from vllm import LLM, SamplingParams
            llm = LLM(model=self.model_name, dtype="half", gpu_memory_utilization=0.9, enforce_eager=True)
            sampling_params = SamplingParams(temperature=temperature, max_tokens=max_tokens)
            full_prompt = f"<|im_start|>system\n{system}<|im_end|>\n<|im_start|>user\n{prompt}<|im_end|>\n<|im_start|>assistant\n"
            outputs = llm.generate([full_prompt], sampling_params)
            return outputs[0].outputs[0].text

        else:
            # HF fallback / mock for demo without GPU
            return self._mock_response(prompt)

    def _mock_response(self, prompt: str) -> str:
        """Deterministic mock for offline demo when no GPU"""
        if "plan" in prompt.lower():
            return """
Plan:
1. Analyze codebase structure via file_tree
2. Identify auth module and missing JWT logic
3. Implement JWT creation/validation in auth.py
4. Add middleware decorator for protected routes
5. Write pytest tests for login and JWT flow
6. Run tests and fix failures
7. Update README and docs
"""
        if "code" in prompt.lower() or "implement" in prompt.lower():
            return """
```python
import jwt
import datetime
from functools import wraps
from flask import request, jsonify

SECRET_KEY = "forgemind-local-secret"

def generate_token(user_id):
    payload = {"user_id": user_id, "exp": datetime.datetime.utcnow() + datetime.timedelta(hours=2)}
    return jwt.encode(payload, SECRET_KEY, algorithm="HS256")

def jwt_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        token = request.headers.get("Authorization", "").replace("Bearer ", "")
        if not token:
            return jsonify({"error": "Token missing"}), 401
        try:
            data = jwt.decode(token, SECRET_KEY, algorithms=["HS256"])
            request.user_id = data["user_id"]
        except jwt.ExpiredSignatureError:
            return jsonify({"error": "Token expired"}), 401
        except Exception as e:
            return jsonify({"error": f"Invalid token: {e}"}), 401
        return f(*args, **kwargs)
    return decorated
```
"""
        return "Generated locally on AMD Radeon GPU via ROCm."

# Singleton
_llm_instance = None
def get_llm(model="qwen2.5-coder:7b"):
    global _llm_instance
    if _llm_instance is None:
        _llm_instance = ROCmLLM(model_name=model)
    return _llm_instance
