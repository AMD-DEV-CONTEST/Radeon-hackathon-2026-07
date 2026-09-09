"""
会话持久化管理 —— 类似微信的聊天记录存储。
"""
import json
import uuid
import time
from pathlib import Path
from dataclasses import dataclass, field
from loguru import logger


DATA_DIR = Path(__file__).parent.parent / "data" / "conversations"
MAX_MESSAGES_PER_CONV = 500  # 单次会话消息上限，防止文件无限增长


@dataclass
class Conversation:
    """一次对话会话。"""
    id: str
    title: str = "新对话"
    messages: list[dict] = field(default_factory=list)  # [{"role","content","time"}, ...]
    created_at: float = 0.0
    updated_at: float = 0.0
    pinned: bool = False
    last_message: dict | None = None   # H5 修复：索引中的最后一条消息预览（懒加载时用于侧边栏）

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "title": self.title,
            "messages": self.messages,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "pinned": self.pinned,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Conversation":
        return cls(**d)

    def add_message(self, role: str, content: str):
        # 消息数达到上限时，自动裁剪最早的消息对（保留最近 400 条）
        if len(self.messages) >= MAX_MESSAGES_PER_CONV:
            # 裁剪：保留最近的消息，但尽量成对裁剪（user+assistant）
            # L3 修复：excess 必须为偶数，否则奇数裁剪会从 assistant 半对开始
            excess = (len(self.messages) - 400)
            if excess % 2:
                excess += 1
            self.messages = self.messages[excess:]
            logger.info(f"会话 {self.id[:8]} 消息数达到上限，已裁剪到 {len(self.messages)} 条")
        # 防御：清洗代理字符（surrogate），避免 json.dump(ensure_ascii=False) 写入崩溃
        content = str(content).encode("utf-8", errors="replace").decode("utf-8")
        self.messages.append({
            "role": role,
            "content": content,
            "time": time.time(),
        })
        self.updated_at = time.time()
        # 用第一条用户消息作为标题
        if self.title == "新对话" and role == "user":
            self.title = content[:30] + ("..." if len(content) > 30 else "")


class ConversationStore:
    """会话存储管理器。"""

    def __init__(self):
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        self._index_path = DATA_DIR / "index.json"
        self._convs: dict[str, Conversation] = {}
        # 并发写保护（Gradio 多请求/线程时防读改写竞态）
        self._lock = threading.RLock()
        self._load_index()

    def _load_index(self):
        """加载会话索引（仅元数据，消息体从独立文件懒加载）。

        索引损坏时会自动从独立会话文件恢复元数据。
        """
        if self._index_path.exists():
            try:
                with open(self._index_path, "r", encoding="utf-8") as f:
                    raw = json.load(f)
                for item in raw:
                    conv_data = {
                        "id": item["id"],
                        "title": item.get("title", "新对话"),
                        "messages": [],  # 懒加载
                        "created_at": item.get("created_at", 0),
                        "updated_at": item.get("updated_at", 0),
                        "pinned": item.get("pinned", False),
                        "last_message": item.get("last_message"),  # H5 修复：恢复预览
                    }
                    conv = Conversation.from_dict(conv_data)
                    self._convs[conv.id] = conv
            except Exception as e:
                logger.warning(f"加载会话索引失败: {e}，将尝试从独立文件恢复")

        # 扫描磁盘上的独立会话文件，恢复索引中缺失的会话
        try:
            for conv_file in DATA_DIR.glob("*.json"):
                if conv_file.name == "index.json":
                    continue
                conv_id = conv_file.stem
                if conv_id not in self._convs:
                    try:
                        with open(conv_file, "r", encoding="utf-8") as f:
                            data = json.load(f)
                        conv = Conversation.from_dict(data)
                        self._convs[conv.id] = conv
                        logger.info(f"从文件恢复会话: {conv.id[:8]} ({conv.title})")
                    except Exception as e:
                        logger.warning(f"恢复会话文件失败 {conv_file}: {e}")

        except Exception as e:
            logger.warning(f"扫描会话文件失败: {e}")

        logger.info(f"已加载 {len(self._convs)} 个历史会话")

    def _save_index(self):
        """保存会话索引（原子写入，失败不丢失消息——消息才是数据源）。"""
        summary = []
        for c in self._convs.values():
            item = {
                "id": c.id,
                "title": c.title,
                "created_at": c.created_at,
                "updated_at": c.updated_at,
                "pinned": c.pinned,
            }
            # 存储最后一条消息的摘要，用于侧边栏预览
            if c.messages:
                last = c.messages[-1]
                item["last_message"] = {
                    "role": last.get("role", ""),
                    "preview": str(last.get("content", ""))[:50],
                }
            summary.append(item)
        # 排序：置顶 > 最新更新
        summary.sort(key=lambda c: (not c["pinned"], -c["updated_at"]))
        # 原子写入：先写临时文件，再 rename
        try:
            tmp_path = self._index_path.with_suffix(".tmp.json")
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(summary, f, ensure_ascii=False, indent=2)
            tmp_path.replace(self._index_path)
        except Exception as e:
            logger.warning(f"保存会话索引失败（消息数据不受影响）: {e}")

    def _conv_path(self, conv_id: str) -> Path:
        return DATA_DIR / f"{conv_id}.json"

    def create(self, title: str = "新对话") -> Conversation:
        conv = Conversation(
            id=uuid.uuid4().hex[:12],
            title=title,
            created_at=time.time(),
            updated_at=time.time(),
        )
        with self._lock:
            self._convs[conv.id] = conv
            self._save_index()
            self._save_conv(conv)
        return conv

    def get(self, conv_id: str) -> Conversation | None:
        """获取会话，自动从独立文件懒加载完整消息。"""
        conv = self._convs.get(conv_id)
        if conv is None:
            return None
        # 始终尝试加载（索引不存储消息体）
        if not conv.messages:
            self._load_conv_messages(conv)
        return conv

    def _load_conv_messages(self, conv: Conversation):
        path = self._conv_path(conv.id)
        if path.exists():
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                conv.messages = data.get("messages", [])
                # H5 修复：消息加载后同步预览（索引里的预览可能过期）
                if conv.messages:
                    conv.last_message = {
                        "role": conv.messages[-1].get("role", ""),
                        "preview": str(conv.messages[-1].get("content", ""))[:50],
                    }
            except Exception as e:
                logger.warning(f"加载会话 {conv.id} 失败: {e}")

    def _save_conv(self, conv: Conversation):
        """原子写入会话文件，防止写一半崩溃导致数据损坏。"""
        import tempfile
        path = self._conv_path(conv.id)
        tmp_path = path.with_suffix(".tmp.json")
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(conv.to_dict(), f, ensure_ascii=False, indent=2)
        tmp_path.replace(path)

    def add_message(self, conv_id: str, role: str, content: str):
        with self._lock:
            conv = self._convs.get(conv_id)
            if conv is None:
                return
            conv.add_message(role, content)
            self._save_conv(conv)
            self._save_index()

    def delete(self, conv_id: str):
        with self._lock:
            conv = self._convs.pop(conv_id, None)
            if conv:
                path = self._conv_path(conv_id)
                if path.exists():
                    path.unlink()
                self._save_index()
                logger.info(f"已删除会话: {conv.title}")

    def clear_messages(self, conv_id: str):
        """清空会话消息但保留会话本身。"""
        with self._lock:
            conv = self._convs.get(conv_id)
            if conv:
                conv.messages.clear()
                conv.title = "新对话"
                conv.updated_at = time.time()
                self._save_conv(conv)
                self._save_index()

    def pin(self, conv_id: str, pinned: bool = True):
        with self._lock:
            conv = self._convs.get(conv_id)
            if conv:
                conv.pinned = pinned
                self._save_index()

    def rename(self, conv_id: str, title: str):
        with self._lock:
            conv = self._convs.get(conv_id)
            if conv:
                conv.title = title
                self._save_index()

    def list_all(self) -> list[Conversation]:
        """列出所有会话（置顶优先、按更新时间倒序）。"""
        convs = list(self._convs.values())
        convs.sort(key=lambda c: (not c.pinned, -c.updated_at))
        return convs

    def get_chat_history(self, conv_id: str) -> list[dict]:
        """获取 Gradio Chatbot 兼容的消息列表。"""
        conv = self.get(conv_id)
        if conv is None:
            return []
        return [{"role": m["role"], "content": m["content"]} for m in conv.messages]


# 全局单例
import threading

_store: ConversationStore | None = None
_store_lock = threading.Lock()


def get_store() -> ConversationStore:
    global _store
    if _store is None:
        with _store_lock:
            if _store is None:
                _store = ConversationStore()
    return _store
