"""Small local OpenAI-compatible Qwen server using ROCm PyTorch.

This is the compatibility server for Radeon Cloud images whose bundled vLLM
build imports a CUDA-only FlashAttention module.  It intentionally implements
only the endpoints RadeonHome needs: ``/v1/models`` and chat completions.
"""

from __future__ import annotations

import os
from contextlib import asynccontextmanager
from time import time
from uuid import uuid4

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import torch
from transformers import AutoModelForCausalLM, AutoTokenizer


MODEL_ID = os.getenv("RADEONHOME_LLM_MODEL", "Qwen/Qwen3-4B")
model = None
tokenizer = None


class ChatRequest(BaseModel):
    model: str | None = None
    messages: list[dict]
    temperature: float = 0.1
    max_tokens: int = 128


@asynccontextmanager
async def lifespan(_app: FastAPI):
    global model, tokenizer
    if not torch.cuda.is_available():
        raise RuntimeError("ROCm/HIP GPU is unavailable to PyTorch")
    tokenizer = AutoTokenizer.from_pretrained(MODEL_ID)
    # eager attention avoids CUDA-only FlashAttention dependencies.
    model = AutoModelForCausalLM.from_pretrained(
        MODEL_ID,
        torch_dtype=torch.float16,
        attn_implementation="eager",
    ).to("cuda").eval()
    yield
    model = None
    tokenizer = None
    torch.cuda.empty_cache()


app = FastAPI(title="RadeonHome local Qwen", lifespan=lifespan)


@app.get("/v1/models")
def models() -> dict:
    return {"object": "list", "data": [{"id": MODEL_ID, "object": "model", "owned_by": "local"}]}


@app.post("/v1/chat/completions")
def chat(request: ChatRequest) -> dict:
    if model is None or tokenizer is None:
        raise HTTPException(status_code=503, detail="model is loading")
    prompt = tokenizer.apply_chat_template(
        request.messages,
        tokenize=False,
        add_generation_prompt=True,
        enable_thinking=False,
    )
    inputs = tokenizer([prompt], return_tensors="pt").to("cuda")
    with torch.inference_mode():
        generated = model.generate(
            **inputs,
            max_new_tokens=min(max(request.max_tokens, 1), 256),
            do_sample=False,
            pad_token_id=tokenizer.eos_token_id,
        )
    output_ids = generated[0][inputs.input_ids.shape[1] :]
    content = tokenizer.decode(output_ids, skip_special_tokens=True).strip()
    return {
        "id": f"chatcmpl-{uuid4().hex}",
        "object": "chat.completion",
        "created": int(time()),
        "model": MODEL_ID,
        "choices": [{"index": 0, "message": {"role": "assistant", "content": content}, "finish_reason": "stop"}],
    }
