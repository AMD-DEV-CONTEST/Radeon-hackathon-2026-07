#!/usr/bin/env python3
"""
Motus Agent - Production-grade async client
Optimization goal: minimize latency, maximize throughput
"""

import asyncio
import aiohttp
import json
import time
import os
from dataclasses import dataclass, field
from typing import AsyncIterator, Optional, Dict, List
from contextlib import asynccontextmanager


@dataclass
class LatencyMetrics:
    """Latency metrics"""
    ttft_ms: float = 0          # Time To First Token
    tbt_ms: float = 0           # Time Between Tokens
    total_ms: float = 0         # Total latency
    queue_ms: float = 0         # Queue wait
    tokens_per_sec: float = 0


@dataclass
class StreamChunk:
    """Streaming output chunk"""
    text: str
    is_finished: bool = False
    metrics: Optional[LatencyMetrics] = None


class MotusAgent:
    """Motus Agent async client"""
    
    def __init__(
        self,
        base_url: str = "http://localhost:8000",
        api_key: Optional[str] = None,
        model: str = "Qwen/Qwen2.5-0.5B-Instruct",
        max_connections: int = 100,
        timeout: float = 120.0
    ):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.api_key = api_key or os.getenv("HF_TOKEN")
        
        # Connection pool: reuse TCP connections
        self.connector = aiohttp.TCPConnector(
            limit=max_connections,
            limit_per_host=max_connections,
            keepalive_timeout=300,
            enable_cleanup_closed=True,
            force_close=False,
        )
        
        # Timeout configuration
        self.timeout = aiohttp.ClientTimeout(
            total=timeout,
            connect=10,
            sock_read=timeout
        )
        
        self.headers = {
            "Content-Type": "application/json",
            "Accept": "text/event-stream",
            "Cache-Control": "no-cache",
        }
        if self.api_key:
            self.headers["Authorization"] = f"Bearer {self.api_key}"
        
        self._session: Optional[aiohttp.ClientSession] = None
    
    async def __aenter__(self):
        self._session = aiohttp.ClientSession(
            connector=self.connector,
            timeout=self.timeout,
            headers=self.headers
        )
        return self
    
    async def __aexit__(self, *args):
        if self._session:
            await self._session.close()
            self._session = None
    
    # ==================== Core inference entry ====================
    
    async def chat(
        self,
        messages: List[Dict[str, str]],
        max_tokens: int = 8192,
        temperature: float = 0.7,
        stream: bool = True
    ) -> AsyncIterator[StreamChunk]:
        """
        Unified inference entry - supports streaming/non-streaming

        Args:
            messages: conversation history [{"role": "user", "content": "..."}]
            max_tokens: maximum output length
            temperature: sampling temperature
            stream: whether to stream output

        Yields:
            StreamChunk: streaming output chunk
        """
        payload = {
            "model": self.model,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "stream": stream,
        }
        
        if stream:
            async for chunk in self._chat_stream(payload):
                yield chunk
        else:
            result = await self._chat_sync(payload)
            yield result
    
    async def _chat_stream(
        self,
        payload: Dict
    ) -> AsyncIterator[StreamChunk]:
        """Streaming inference - minimize TTFT"""
        
        url = f"{self.base_url}/v1/chat/completions"
        
        # Warm up connection (first time)
        if not self._session:
            raise RuntimeError("Use async with or call start() first")
        
        start_time = time.perf_counter()
        first_token_time = None
        token_count = 0
        buffer = ""
        
        try:
            async with self._session.post(
                url,
                json=payload,
                headers=self.headers
            ) as resp:
                
                if resp.status != 200:
                    text = await resp.text()
                    raise RuntimeError(f"HTTP {resp.status}: {text[:200]}")
                
                # Parse SSE stream
                async for line in resp.content:
                    line = line.decode("utf-8").strip()
                    
                    if not line.startswith("data: "):
                        continue
                    
                    data = line[6:]  # Strip "data: "
                    
                    if data == "[DONE]":
                        break
                    
                    try:
                        chunk = json.loads(data)
                        delta = chunk["choices"][0].get("delta", {})
                        text = delta.get("content", "")
                        
                        if text:
                            # Record TTFT
                            if first_token_time is None:
                                first_token_time = time.perf_counter()
                            
                            token_count += 1
                            buffer += text
                            
                            yield StreamChunk(
                                text=text,
                                is_finished=False
                            )
                    
                    except (json.JSONDecodeError, KeyError):
                        continue
                
                # Calculate metrics
                total_time = (time.perf_counter() - start_time) * 1000
                ttft = (first_token_time - start_time) * 1000 if first_token_time else 0
                
                metrics = LatencyMetrics(
                    ttft_ms=ttft,
                    total_ms=total_time,
                    tokens_per_sec=(token_count / total_time * 1000) if total_time > 0 else 0
                )
                
                yield StreamChunk(
                    text="",
                    is_finished=True,
                    metrics=metrics
                )
        
        except asyncio.TimeoutError:
            raise RuntimeError(f"Request timeout after {self.timeout.total}s")
    
    async def _chat_sync(self, payload: Dict) -> StreamChunk:
        """Non-streaming inference"""
        
        url = f"{self.base_url}/v1/chat/completions"
        start = time.perf_counter()
        
        async with self._session.post(url, json=payload) as resp:
            elapsed = (time.perf_counter() - start) * 1000
            
            if resp.status != 200:
                text = await resp.text()
                raise RuntimeError(f"HTTP {resp.status}: {text[:200]}")
            
            data = await resp.json()
            text = data["choices"][0]["message"]["content"]
            
            metrics = LatencyMetrics(total_ms=elapsed)
            
            return StreamChunk(text=text, is_finished=True, metrics=metrics)


# ==================== Benchmark Tool ====================

async def benchmark():
    """Performance test"""
    
    async with MotusAgent(
        base_url="https://radeon-global.anruicloud.com/spaces/u-14452-18f2b17f/8000",
        max_connections=100
    ) as agent:
        
        # Test 1: Single request latency (streaming)
        print("=" * 60)
        print("Test 1: Single Request Latency (Streaming)")
        print("-" * 60)
        
        messages = [{"role": "user", "content": "Explain quantum computing in simple terms"}]
        
        full_text = ""
        async for chunk in agent.chat(messages, max_tokens=100, stream=True):
            if chunk.is_finished and chunk.metrics:
                print(f"TTFT: {chunk.metrics.ttft_ms:.2f}ms")
                print(f"Total: {chunk.metrics.total_ms:.2f}ms")
                print(f"Throughput: {chunk.metrics.tokens_per_sec:.2f} tok/s")
            else:
                full_text += chunk.text
        
        print(f"Response length: {len(full_text)} chars")
        
        # Test 2: Concurrent throughput
        print("\n" + "=" * 60)
        print("Test 2: Concurrent Throughput")
        print("-" * 60)
        
        concurrency = 20
        total = 200
        latencies = []
        
        async def _single_task(idx: int):
            msgs = [{"role": "user", "content": f"Task {idx}: What is {idx} * {idx}?"}]
            start = time.perf_counter()
            
            text = ""
            async for chunk in agent.chat(msgs, max_tokens=50, stream=True):
                if not chunk.is_finished:
                    text += chunk.text
            
            elapsed = (time.perf_counter() - start) * 1000
            return elapsed
        
        # Concurrent execution
        start_all = time.perf_counter()
        tasks = [_single_task(i) for i in range(total)]
        results = await asyncio.gather(*tasks)
        total_time = time.perf_counter() - start_all
        
        latencies = results
        latencies.sort()
        
        print(f"Concurrency: {concurrency}")
        print(f"Total: {total}")
        print(f"Duration: {total_time:.2f}s")
        print(f"RPS: {total/total_time:.2f}")
        print(f"Latency P50: {latencies[len(latencies)//2]:.2f}ms")
        print(f"Latency P95: {latencies[int(len(latencies)*0.95)]:.2f}ms")
        print(f"Latency P99: {latencies[int(len(latencies)*0.99)]:.2f}ms")


if __name__ == "__main__":
    asyncio.run(benchmark())