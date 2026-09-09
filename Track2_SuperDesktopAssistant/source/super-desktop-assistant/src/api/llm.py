"""
通用 LLM API —— 支持任意供应商的任意模型。
所有函数都是同步的，由上层 Agent 用 asyncio.to_thread 包装。
"""
import json as _json
import re as _re
from loguru import logger
from ._client import get_client_for
from ..config import get_config, ProviderSpec, ModelSpec


def _resolve(capability: str = "llm",
             provider: str | None = None,
             model: str | None = None) -> tuple[ProviderSpec, ModelSpec, str]:
    cfg = get_config()

    if provider and model:
        p = cfg.get_provider(provider)
        if not p:
            raise ValueError(f"供应商不存在: {provider}")
        m = p.get_model(model)
        if not m:
            raise ValueError(f"模型 {model} 不存在于供应商 {provider}")
        return p, m, model

    resolved = cfg.resolve(capability)
    if not resolved:
        raise ValueError(
            f"功能 '{capability}' 未分配供应商/模型。"
            f"请在 config.json -> assignments 中配置，或在 UI 的「模型配置」面板中选择。"
        )

    p, m = resolved
    return p, m, m.id


def chat(
    messages: list[dict],
    capability: str = "llm",
    provider: str | None = None,
    model: str | None = None,
    temperature: float | None = None,
    max_tokens: int | None = None,
    response_format: dict | None = None,
    **extra_params,
) -> str:
    """
    通用 LLM 对话（同步，由上层 asyncio.to_thread 调用）。

    Phase B：委托 ai-coin 桥统一处理多供应商/重试/超时/错误分类。

    Returns:
        LLM 回复文本
    Raises:
        ValueError: 未配置 API Key 或模型
        RuntimeError: API 调用失败
    """
    from .ai_coin_bridge import chat as _aicoin_chat

    logger.debug(f"LLM (ai-coin) [{capability}/{provider or 'auto'}] msgs={len(messages)}")
    return _aicoin_chat(
        messages, capability=capability, provider=provider, model=model,
        temperature=temperature, max_tokens=max_tokens,
    )


def chat_stream(
    messages: list[dict],
    capability: str = "llm",
    provider: str | None = None,
    model: str | None = None,
    temperature: float | None = None,
    max_tokens: int | None = None,
):
    """流式 LLM 对话。返回增量文本生成器（yield str）。

    Phase B：委托 ai-coin 的 stream_chat（SSE）。
    注意：流式不支持 tools/json_schema；gemini 供应商未实现流式，
    消费者需 try/except 捕获 NotImplementedError 回退到 chat()。
    """
    from .ai_coin_bridge import chat_stream as _aicoin_stream

    return _aicoin_stream(
        messages, capability=capability, provider=provider, model=model,
        temperature=temperature, max_tokens=max_tokens,
    )


def chat_json(
    messages: list[dict],
    capability: str = "llm",
    provider: str | None = None,
    model: str | None = None,
    temperature: float = 0.1,
    **extra_params,
) -> str:
    """强制 JSON 输出的 LLM 对话。

    Phase B：委托 ai-coin 结构化输出（JSON 提取/修复 + schema 校验 + 回喂重试）。
    可选传 json_schema 做强校验；默认任何 JSON 对象。
    返回 JSON 字符串（兼容既有调用方）。
    """
    from .ai_coin_bridge import chat_json as _aicoin_chat_json

    return _aicoin_chat_json(
        messages, capability=capability, provider=provider, model=model,
        temperature=temperature, **extra_params,
    )


# ── v3 P8: 文本式工具调用解析 ──
# mimo 等模型不遵循 OpenAI 标准 tool_calls 结构，而是把工具调用写成文本：
#   <tool_call>
#   <function=write_file>
#   <parameter=path>...path...</parameter>
#   <parameter=content>...content...</parameter>
#   </tool_call>
# 该解析器兼容「无闭合 </tool_call> / </parameter>」的不完整输出。

_ALLOWED_TEXT_TOOLS = frozenset((
    "write_file", "read_file", "list_files", "search_code",
    "generate_image", "get_shared_memory", "add_note", "add_discovery",
))


def _parse_text_tool_calls(content: str) -> list[tuple[str, dict]]:
    """解析文本式工具调用，返回 [(tool_name, args_dict), ...] 列表。

    K1 修复：
    - 收集一条回复中**全部** tool_call（原实现丢弃第一个调用之后的全部内容）
    - 参数值按第一个 `</parameter>`（或段尾）截断，而不是第一个 `<parameter=`
      （避免值内合法出现 `<parameter=` 时被截断，如 write_file 写入的 XML/HTML）
    """
    calls: list[tuple[str, dict]] = []
    pos = 0
    while True:
        m = _re.search(r"<tool_call>\s*<function=([A-Za-z_][\w]*)>", content[pos:])
        if not m:
            break
        func_name = m.group(1)
        seg_start = pos + m.end()
        # 本段边界：下一个 <tool_call>（允许同回复内多个调用）
        nxt_call = content.find("<tool_call>", seg_start)
        seg_end = nxt_call if nxt_call != -1 else len(content)
        body = content[seg_start:seg_end]

        params: dict[str, str] = {}
        i = 0
        while True:
            pm = _re.search(r"<parameter=([^>]+)>", body[i:])
            if not pm:
                break
            name = pm.group(1).strip()
            start = i + pm.end()
            end_closing = body.find("</parameter>", start)
            end_next = body.find("<parameter=", start)
            if end_closing != -1:
                end = end_closing
                next_i = end_closing + len("</parameter>")
            elif end_next != -1:
                end = end_next
                next_i = end_next
            else:
                end = len(body)
                next_i = len(body)
            params[name] = body[start:end].strip()
            i = next_i

        if params:
            calls.append((func_name, params))
        pos = seg_end
    return calls


def chat_with_tools(
    messages: list[dict],
    tools: list[dict],
    capability: str = "llm",
    provider: str | None = None,
    model: str | None = None,
    temperature: float | None = None,
    max_tokens: int | None = None,
    max_tool_rounds: int = 5,
    on_tool_call=None,
    **extra_params,
) -> str:
    """
    带 Function Calling 的 LLM 对话（同步）。

    Phase B：委托 ai-coin 自动工具循环（tool_call→执行→回传，最多 8 轮）。
    兼容原生 tool_calls 与文本式 <tool_call> 输出。
    """
    from .ai_coin_bridge import chat_with_tools as _aicoin_tools

    return _aicoin_tools(
        messages, tools, capability=capability, provider=provider, model=model,
        temperature=temperature, max_tokens=max_tokens,
        max_tool_rounds=max_tool_rounds, on_tool_call=on_tool_call,
    )
