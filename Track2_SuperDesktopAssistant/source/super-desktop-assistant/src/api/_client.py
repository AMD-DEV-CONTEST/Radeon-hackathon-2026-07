"""
统一客户端工厂 —— 为每个 (provider, model) 组合管理 OpenAI 客户端实例。
"""
from openai import OpenAI
from loguru import logger
from ..config import get_config


_client_cache: dict[str, OpenAI] = {}


def clear_client_cache():
    """清空客户端缓存（在 config 重载后调用）。"""
    _client_cache.clear()
    logger.debug("已清空 API 客户端缓存")


def provider_is_reachable(provider, timeout: float = 1.0) -> bool:
    """
    轻量 TCP 连通性检测。用于 local_first 场景下判断本地推理服务是否在线。
    只做 TCP 握手，不发送真实请求。
    """
    import socket
    from urllib.parse import urlparse

    try:
        u = urlparse(provider.base_url)
        host = u.hostname or "127.0.0.1"
        port = u.port or (443 if u.scheme == "https" else 80)
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except Exception:
        return False


def get_client_for(provider_name: str) -> OpenAI:
    """
    获取指定供应商的 OpenAI 客户端（按 provider_name 缓存）。

    自动从 ConfigManager 读取 api_key 和 base_url。
    """
    cfg = get_config()
    provider = cfg.get_provider(provider_name)
    if not provider:
        raise ValueError(f"未找到供应商: {provider_name}")
    # BUG1 修复：本地推理服务（vllm/ollama/lmstudio 等）通常不需要 API Key，
    # 否则 api_preference=local_first 永远无法工作。云端供应商仍要求非空。
    if not provider.api_key and not provider.is_local:
        raise ValueError(f"供应商 {provider_name} 未配置 API Key（请检查 .env 中的 {provider.env_api_key or provider_name.upper() + '_API_KEY'}）")

    cache_key = provider_name
    if cache_key not in _client_cache:
        # 限制缓存大小，防止长时间运行内存泄漏（每个客户端 ~sockets 占用）
        if len(_client_cache) >= 16:
            oldest = next(iter(_client_cache))
            logger.debug(f"API 客户端缓存已满，淘汰: {oldest}")
            del _client_cache[oldest]
        # H3 修复：设置请求超时（默认 120s）。此前未设 timeout，SDK 默认 600s，
        # 挂在 to_thread 里的同步调用会让节点超时无法真正中断，导致线程泄漏+费用翻倍。
        _timeout = float(getattr(cfg.settings, "timeout_per_node", 120.0) or 120.0)
        _client_cache[cache_key] = OpenAI(
            api_key=provider.api_key or "local-dev-key",  # 本地服务接受占位 key
            base_url=provider.base_url,
            timeout=_timeout,
        )
        logger.debug(f"🔌 创建客户端: [{provider_name}] → {provider.base_url} (timeout={_timeout}s)")

    return _client_cache[cache_key]
