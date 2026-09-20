"""AutoQuant router — unified OpenAI-compatible endpoint.

Quantitative questions  -> local vLLM (127.0.0.1:8000, qwen-trader-merged, DSL pipeline)
General questions      -> AMD developer API (DeepSeek-V4-Flash, personal assistant)

Open WebUI sees a single model id `autoquant-assistant`; routing is invisible to the user.

Env (from /workspace/public_site/.router.env via serve_router.sh):
  DS_API_KEY / DS_BASE_URL / DS_MODEL
  ROUTER_DISABLED=1  -> always route to local (rollback)
  ROUTER_QUANT_KEYWORDS (optional JSON list override)
"""
import json
import os

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, StreamingResponse

app = FastAPI()

LOCAL_BASE = "http://127.0.0.1:8000/v1"
LOCAL_MODEL = "models/qwen-trader-merged"
DS_BASE = os.environ.get("DS_BASE_URL", "")
DS_KEY = os.environ.get("DS_API_KEY", "")
DS_MODEL = os.environ.get("DS_MODEL", "DeepSeek-V4-Flash")
ROUTER_DISABLED = os.environ.get("ROUTER_DISABLED", "0") == "1"
UNIFIED_MODEL = "autoquant-assistant"

ASSISTANT_SYSTEM = (
    "你是 AutoQuant 个人助理。对非量化问题请直接、完整、自然地回答，"
    "不要输出 step 指令式/模板化内容，不要默认用户在量化场景。"
)

DEFAULT_QUANT_KEYWORDS = [
    "策略", "回测", "止损", "止盈", "仓位", "金叉", "死叉", "均线", "MA", "EMA", "RSI", "MACD",
    "布林", "BOLL", "ETF", "股票", "个股", "行情", "大盘", "指数", "K线", "量化", "因子",
    "阿尔法", "alpha", "beta", "夏普", "sharpe", "回撤", "drawdown", "指标", "交易",
    "买入", "卖出", "抄底", "逃顶", "套利", "涨跌", "涨停", "跌停", "DSL", "信号", "触发",
    "网格", "收益", "持仓", "资金", "crossover", "backtest", "strategy", "indicator",
]


def _quant_keywords():
    try:
        over = json.loads(os.environ.get("ROUTER_QUANT_KEYWORDS", "[]"))
        if isinstance(over, list) and over:
            return over
    except Exception:
        pass
    return DEFAULT_QUANT_KEYWORDS


def classify(text: str) -> str:
    if ROUTER_DISABLED:
        return "local"
    t = text.lower()
    return "local" if any(k.lower() in t for k in _quant_keywords()) else "general"


def _last_user_text(messages):
    for m in reversed(messages or []):
        if m.get("role") == "user":
            c = m.get("content")
            if isinstance(c, str) and c.strip():
                return c
    return ""


async def _forward(client, url, headers, body, stream, extra_headers=None):
    req = client.build_request("POST", url, headers=headers, json=body)
    r = await client.send(req, stream=stream)
    if stream:
        async def gen():
            try:
                async for line in r.aiter_lines():
                    if line:
                        yield line + "\n"
            except Exception as e:
                # upstream stream interrupted (e.g. vLLM closed connection) —
                # emit an SSE error event so the response stays well-formed
                # chunked and clients don't see "payload not completed".
                err_payload = {"error": {"message": f"upstream stream interrupted: {e.__class__.__name__}: {str(e)[:120]}", "type": "upstream_error"}}
                yield "data: " + json.dumps(err_payload, ensure_ascii=False) + "\n\n"
                yield "data: [DONE]\n\n"
            finally:
                try:
                    await r.aclose()
                except Exception:
                    pass

        return StreamingResponse(
            gen(), media_type="text/event-stream",
            status_code=r.status_code, headers=extra_headers or {},
        )
    try:
        payload = r.json()
    except Exception:
        payload = {"error": {"message": r.text[:300]}}
    return JSONResponse(payload, status_code=r.status_code, headers=extra_headers or {})


@app.get("/v1/models")
async def models():
    return {"object": "list", "data": [{"id": UNIFIED_MODEL, "object": "model", "owned_by": "autoquant"}]}


@app.get("/health")
async def health():
    return {
        "router_enabled": not ROUTER_DISABLED,
        "model": UNIFIED_MODEL,
        "upstreams": {
            "quant_local": LOCAL_BASE,
            "general_amd": DS_BASE or "not-configured",
            "general_model": DS_MODEL,
        },
        "general_configured": bool(DS_BASE and DS_KEY),
    }


@app.post("/v1/chat/completions")
async def chat(request: Request):
    body = await request.json()
    messages = body.get("messages", [])
    stream = bool(body.get("stream", False))
    route = classify(_last_user_text(messages))

    if route == "general" and DS_BASE and DS_KEY:
        msgs = list(messages)
        msgs.insert(0, {"role": "system", "content": ASSISTANT_SYSTEM})
        body = {**body, "model": DS_MODEL, "messages": msgs}
        headers = {"Content-Type": "application/json", "Authorization": f"Bearer {DS_KEY}"}
        try:
            async with httpx.AsyncClient(timeout=45) as c:
                resp = await _forward(
                    c, f"{DS_BASE.rstrip('/')}/chat/completions", headers, body, stream,
                    extra_headers={"x-router-route": "general"},
                )
            if isinstance(resp, StreamingResponse) or resp.status_code < 500:
                return resp
        except Exception:
            pass
        # fallback to local on AMD error/timeout
        extra = {"x-router-fallback": "local", "x-router-route": "general"}
        async with httpx.AsyncClient(timeout=180) as c:
            return await _forward(
                c, f"{LOCAL_BASE}/chat/completions",
                {"Content-Type": "application/json"},
                {**body, "model": LOCAL_MODEL}, stream, extra,
            )

    # local route (quantitative, or router disabled, or AMD not configured)
    body = {**body, "model": LOCAL_MODEL}
    extra = {"x-router-route": "local"}
    async with httpx.AsyncClient(timeout=180) as c:
        return await _forward(
            c, f"{LOCAL_BASE}/chat/completions",
            {"Content-Type": "application/json"}, body, stream, extra,
        )
