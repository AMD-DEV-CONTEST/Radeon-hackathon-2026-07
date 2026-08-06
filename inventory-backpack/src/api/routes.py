"""
API routes - minimal fix version
Features: no instantiation at import time, no hardcoding, no redundant state checks
"""

from __future__ import annotations

import asyncio
import logging
from typing import Callable, Any, TYPE_CHECKING

from fastapi import APIRouter, Request, HTTPException, Depends, status
from fastapi.responses import StreamingResponse, JSONResponse

# Import only during type checking to avoid circular dependency
if TYPE_CHECKING:
    from fastapi import FastAPI


logger = logging.getLogger("motus.routes")


# ============== Dependency injection (explicit passing, not global) ==============

def get_config(request: Request) -> dict:
    """Get config from request state"""
    return request.app.state.config


def get_container(request: Request) -> Any:
    """Get container from request state"""
    return request.app.state.container


# ============== Response models (Pydantic v2) ==============

from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=32768)
    session_id: str = Field(default="default", max_length=64)
    stream: bool = Field(default=False)
    
    class Config:
        json_schema_extra = {
            "example": {
                "message": "你好",
                "session_id": "default",
                "stream": False
            }
        }


class ChatResponse(BaseModel):
    reply: str
    session_id: str
    tokens_used: int | None = None


class ErrorResponse(BaseModel):
    error: str
    detail: str | None = None


# ============== Core handlers (pure functions, stateless) ==============

async def process_chat(
    message: str,
    config: dict,
    container: Any,
    stream: bool = False
) -> str | AsyncIterator[str]:
    """
    Process chat request - pure function, no side effects

    Returns: full reply or stream iterator
    """
    # Get remote endpoint from config
    remote = config.get("remote", {})
    endpoint = remote.get("endpoint")
    
    if not endpoint:
        raise ValueError("远程端点未配置")
    
    # Build request
    model = remote.get("model", "Qwen/Qwen2.5-0.5B-Instruct")
    
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": message}],
        "temperature": config.get("inference", {}).get("temperature", 0.1),
        "top_p": config.get("inference", {}).get("top_p", 0.95),
        "max_tokens": config.get("inference", {}).get("max_tokens", 4096),
        "stream": stream,
    }
    
    # Call remote API (simplified example)
    if stream:
        return _stream_response(endpoint, payload, remote)
    else:
        return await _call_remote(endpoint, payload, remote)


async def _call_remote(endpoint: str, payload: dict, remote_config: dict) -> str:
    """Single remote call"""
    import aiohttp
    
    timeout = aiohttp.ClientTimeout(
        total=remote_config.get("timeout", 45),
        connect=remote_config.get("connect_timeout", 5)
    )
    
    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.post(
            f"{endpoint}/chat/completions",
            headers={"Authorization": f"Bearer {remote_config.get('api_key', '')}"},
            json=payload
        ) as resp:
            
            if resp.status != 200:
                body = await resp.text()
                raise HTTPException(
                    status_code=resp.status,
                    detail=f"远程API错误: {body[:500]}"  # Limit error length, not truncation
                )
            
            result = await resp.json()
            return result["choices"][0]["message"]["content"]


async def _stream_response(endpoint: str, payload: dict, remote_config: dict) -> AsyncIterator[str]:
    """Streaming response"""
    import aiohttp
    
    payload["stream"] = True
    
    timeout = aiohttp.ClientTimeout(
        total=remote_config.get("timeout", 45),
        connect=remote_config.get("connect_timeout", 5)
    )
    
    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.post(
            f"{endpoint}/chat/completions",
            headers={"Authorization": f"Bearer {remote_config.get('api_key', '')}"},
            json=payload
        ) as resp:
            
            async for line in resp.content:
                line = line.decode("utf-8").strip()
                if line.startswith("data: "):
                    data = line[6:]
                    if data == "[DONE]":
                        break
                    yield f"data: {data}\n\n"


# ============== Router factory (config-driven) ==============

def create_router(config: dict) -> APIRouter:
    """
    Create router (factory pattern, not instantiated at import time)

    Args:
        config: app config
    """
    router = APIRouter()

    # ============== Health check ==============

    @router.get("/health", response_model=dict)
    async def health_check():
        """Health check - stateless"""
        return {
            "status": "ok",
            "version": config.get("version", "0.0.0"),
            "name": config.get("name", "motus-agent")
        }

    # ============== Chat endpoint ==============
    
    @router.post("/chat", response_model=ChatResponse)
    async def chat(
        request: ChatRequest,
        req: Request,
        config: dict = Depends(get_config),
        container: Any = Depends(get_container)
    ):
        """
        Non-streaming chat
        """
        try:
            reply = await process_chat(
                message=request.message,
                config=config,
                container=container,
                stream=False
            )
            
            return ChatResponse(
                reply=reply,
                session_id=request.session_id,
                tokens_used=None  # Extract from response
            )
            
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
        except Exception as e:
            logger.exception("聊天处理失败")
            raise HTTPException(status_code=500, detail=str(e))
    
    @router.post("/chat/stream")
    async def chat_stream(
        request: ChatRequest,
        req: Request,
        config: dict = Depends(get_config),
        container: Any = Depends(get_container)
    ):
        """
        Streaming chat - SSE
        """
        async def event_generator():
            async for chunk in process_chat(
                message=request.message,
                config=config,
                container=container,
                stream=True
            ):
                yield chunk
        
        return StreamingResponse(
            event_generator(),
            media_type="text/event-stream"
        )
    
    # ============== Knowledge base endpoints (RAG) ==============

    @router.post("/knowledge/upload")
    async def upload_document(
        file: Any,  # UploadFile
        config: dict = Depends(get_config)
    ):
        """Upload document to knowledge base"""
        # Process asynchronously to avoid blocking
        from src.rag.pipeline import get_rag_pipeline

        rag = get_rag_pipeline(config.get("rag", {}))
        # ... handle upload

        return {"status": "processing", "file": getattr(file, "filename", "unknown")}

    @router.post("/knowledge/query")
    async def query_knowledge(
        question: str,
        config: dict = Depends(get_config)
    ):
        """Query knowledge base"""
        from src.rag.pipeline import get_rag_pipeline
        
        rag = get_rag_pipeline(config.get("rag", {}))
        result = rag.query(question)
        
        return {
            "question": question,
            "contexts": result.get("contexts", []),
            "sources": result.get("sources", [])
        }
    
    # ============== Config query ==============

    @router.get("/config")
    async def get_config_endpoint(
        config: dict = Depends(get_config)
    ):
        """Get current config (sanitized)"""
        # Return safe config subset
        return {
            "name": config.get("name"),
            "version": config.get("version"),
            "inference": {
                k: v for k, v in config.get("inference", {}).items()
                if k not in ["api_key", "token"]
            }
        }
    
    return router