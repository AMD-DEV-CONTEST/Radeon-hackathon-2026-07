"""
Memory — 跨文件一致性记忆管理。
确保两份交付物的关键数字完全一致。
"""

from pathlib import Path
from datetime import datetime
import json


class ConsistencyMemory:
    def __init__(self, config: dict):
        self.key_numbers = {}
        self.cross_references = {}
        self._memory_file = Path(__file__).parent.parent / "data" / "consistency_memory.json"
        self._load()

    def _load(self):
        if self._memory_file.exists():
            try:
                with open(self._memory_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    self.key_numbers = data.get("key_numbers", {})
                    self.cross_references = data.get("cross_references", {})
            except Exception:
                pass

    def _save(self):
        self._memory_file.parent.mkdir(parents=True, exist_ok=True)
        with open(self._memory_file, "w", encoding="utf-8") as f:
            json.dump({
                "key_numbers": self.key_numbers,
                "cross_references": self.cross_references,
                "updated_at": datetime.now().isoformat(),
            }, f, ensure_ascii=False, indent=2)

    def record_key_number(self, name: str, value, source: str):
        """记录关键数字。"""
        self.key_numbers[name] = {"value": value, "source": source}
        self._save()

    def verify_consistency(self, name: str, expected_value, actual_value) -> dict:
        """验证数字一致性。"""
        diff = abs(expected_value - actual_value) if isinstance(expected_value, (int, float)) else 0
        return {
            "name": name,
            "consistent": diff < 0.01,
            "expected": expected_value,
            "actual": actual_value,
            "difference": diff,
        }

    def get_all_key_numbers(self) -> dict:
        """获取所有已记录的关键数字。"""
        return {k: v["value"] for k, v in self.key_numbers.items()}

    def clear(self):
        """清空记忆。"""
        self.key_numbers = {}
        self.cross_references = {}
        self._save()
