"""数据驱动路由注册表（绞杀者模式核心）。

新路由经注册表精确匹配 / 前缀匹配优先分发；未迁移路由由调用方兜底（legacy 分支），
保证服务器永不被破坏。路由处理器统一签名：fn(handler)，handler 即 XAIHandler 实例。
"""
from __future__ import annotations


class Router:
    def __init__(self) -> None:
        # (method, path) -> callable
        self._exact: dict[tuple[str, str], object] = {}
        # list of (method, prefix, callable)
        self._prefix: list[tuple[str, str, object]] = []

    def add(self, method: str, path: str, handler) -> None:
        """注册精确匹配路由（method, path 二元组）。"""
        self._exact[(method, path)] = handler

    def add_prefix(self, method: str, prefix: str, handler) -> None:
        """注册前缀匹配路由（如 /api/sessions/ 下的动态子路径）。"""
        self._prefix.append((method, prefix, handler))

    def dispatch(self, method: str, path: str, handler) -> bool:
        """命中则返回 True 并已处理请求；未命中返回 False（交由调用方兜底）。"""
        fn = self._exact.get((method, path))
        if fn is not None:
            fn(handler)
            return True
        for m, prefix, fn in self._prefix:
            if m == method and path.startswith(prefix):
                fn(handler)
                return True
        return False
