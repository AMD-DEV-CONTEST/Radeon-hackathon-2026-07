"""
Memory — 多轮对话记忆管理。
支持缓冲区记忆和滑动窗口，保存本地对话历史。
"""

from pathlib import Path
from datetime import datetime
from langchain_core.messages import HumanMessage, AIMessage


class ConversationMemory:
    def __init__(self, config: dict):
        self.max_history = config["memory"]["max_history"]
        self.history: list[dict] = []
        self._load_history()

    def _history_file(self) -> Path:
        return Path(__file__).parent.parent / "data" / "chat_history.json"

    def _load_history(self):
        """从本地文件加载历史记录。"""
        import json
        history_file = self._history_file()
        if history_file.exists():
            try:
                with open(history_file, "r", encoding="utf-8") as f:
                    self.history = json.load(f)
            except Exception:
                self.history = []

    def _save_history(self):
        """保存历史记录到本地文件。"""
        import json
        history_file = self._history_file()
        history_file.parent.mkdir(parents=True, exist_ok=True)
        with open(history_file, "w", encoding="utf-8") as f:
            json.dump(self.history, f, ensure_ascii=False, indent=2)

    def get_history(self) -> list:
        """获取格式化的对话历史（供 LLM 使用）。"""
        messages = []
        for entry in self.history[-self.max_history:]:
            messages.append(HumanMessage(content=entry["human"]))
            messages.append(AIMessage(content=entry["ai"]))
        return messages

    def add(self, human_input: str, ai_response: str):
        """添加一轮对话到历史。"""
        self.history.append({
            "human": human_input,
            "ai": ai_response,
            "timestamp": datetime.now().isoformat(),
        })
        if len(self.history) > self.max_history * 2:
            self.history = self.history[-self.max_history * 2:]
        self._save_history()

    def clear(self):
        """清空历史记录。"""
        self.history = []
        self._save_history()
