# -*- coding: utf-8 -*-
"""记忆管理：多轮对话历史 + 长期偏好记忆（本地 JSON 持久化）。

设计：短期记忆（本次会话轮次）注入 system；长期记忆（用户偏好/重要事实）
跨会话保留，启动时加载。全部本地存储，符合"全离线私有"定位。
"""
import json
import os
import time
from typing import List

import yaml

with open("config.yaml", "r", encoding="utf-8") as f:
    CFG = yaml.safe_load(f)

MEMORY = CFG.get("memory", {})
MAX_HISTORY = MEMORY.get("max_history", 10)
LONG_TERM = MEMORY.get("long_term", "./data/memory_long.json")


class Memory:
    def __init__(self):
        self.short: List[dict] = []          # [{role, content}]
        self.long: dict = self._load_long()  # {key: {fact, ts}}

    def _load_long(self) -> dict:
        if os.path.exists(LONG_TERM):
            try:
                with open(LONG_TERM, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                return {}
        return {}

    def _save_long(self):
        os.makedirs(os.path.dirname(LONG_TERM), exist_ok=True)
        with open(LONG_TERM, "w", encoding="utf-8") as f:
            json.dump(self.long, f, ensure_ascii=False, indent=2)

    def add_short(self, role: str, content: str):
        self.short.append({"role": role, "content": content})
        if len(self.short) > MAX_HISTORY * 2:
            self.short = self.short[-MAX_HISTORY * 2:]

    def remember(self, key: str, fact: str):
        """长期记忆：记录用户明确要求的偏好/事实。"""
        self.long[key] = {"fact": fact, "ts": time.strftime("%Y-%m-%d %H:%M")}
        self._save_long()

    def recall(self) -> str:
        """返回长期记忆文本，注入 system prompt。"""
        if not self.long:
            return ""
        parts = [f"- {k}: {v['fact']} ({v['ts']})" for k, v in self.long.items()]
        return "用户已知偏好/事实：\n" + "\n".join(parts)

    def short_messages(self) -> List[dict]:
        return list(self.short)

    def clear_short(self):
        self.short = []


if __name__ == "__main__":
    m = Memory()
    m.add_short("user", "你好")
    m.remember("称呼", "叫我小张")
    print(m.recall())
    print(m.short_messages())
