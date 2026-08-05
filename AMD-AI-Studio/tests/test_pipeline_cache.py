"""
测试: Pipeline 缓存模块
"""

import pytest
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from modules.pipeline_cache import PipelineCache, global_cache


class TestPipelineCache:
    def setup_method(self):
        self.cache = PipelineCache()

    def test_initial_empty(self):
        """测试初始缓存为空"""
        assert self.cache.keys == []

    def test_set_and_get(self):
        """测试缓存设置和获取"""
        self.cache.set("test_key", {"data": 123})
        result = self.cache.get("test_key")
        assert result == {"data": 123}

    def test_get_nonexistent(self):
        """测试获取不存在的 key"""
        result = self.cache.get("nonexistent")
        assert result is None

    def test_overwrite(self):
        """测试覆盖缓存"""
        self.cache.set("key", "old_value")
        self.cache.set("key", "new_value")
        assert self.cache.get("key") == "new_value"

    def test_remove(self):
        """测试移除缓存项"""
        self.cache.set("key", "value")
        self.cache.remove("key")
        assert self.cache.get("key") is None

    def test_clear(self):
        """测试清空缓存"""
        self.cache.set("key1", "v1")
        self.cache.set("key2", "v2")
        self.cache.set("key3", "v3")
        self.cache.clear()
        assert self.cache.keys == []

    def test_keys_property(self):
        """测试 keys 属性"""
        self.cache.set("a", 1)
        self.cache.set("b", 2)
        self.cache.set("c", 3)
        assert sorted(self.cache.keys) == ["a", "b", "c"]

    def test_remove_nonexistent(self):
        """测试移除不存在的 key（不报错）"""
        try:
            self.cache.remove("nonexistent")
        except Exception as e:
            pytest.fail(f"remove 不存在的 key 抛出异常: {e}")

    def test_global_cache_singleton(self):
        """测试全局缓存单例"""
        assert global_cache is not None
        assert isinstance(global_cache, PipelineCache)

    def test_cache_with_object(self):
        """测试缓存对象"""
        class MockPipe:
            def __init__(self):
                self.data = "test"

        pipe = MockPipe()
        self.cache.set("pipe", pipe)
        cached = self.cache.get("pipe")
        assert cached is pipe
        assert cached.data == "test"

    def test_multiple_keys(self):
        """测试多 key 缓存"""
        for i in range(10):
            self.cache.set(f"key_{i}", i)
        assert len(self.cache.keys) == 10
        for i in range(10):
            assert self.cache.get(f"key_{i}") == i