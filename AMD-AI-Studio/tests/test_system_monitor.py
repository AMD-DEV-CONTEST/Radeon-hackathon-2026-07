"""
测试: 系统监控模块
"""

import pytest
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from modules.system_monitor import SystemMonitor, SystemInfo, global_monitor


class TestSystemInfo:
    def test_system_info_defaults(self):
        """测试 SystemInfo 默认值"""
        info = SystemInfo()
        assert info.timestamp == 0.0
        assert info.cpu_model == ""
        assert info.cpu_cores == 0
        assert info.memory_total_gb == 0.0
        assert info.gpu_count == 0
        assert info.gpu_info == []
        assert info.cuda_available is False


class TestSystemMonitor:
    def setup_method(self):
        self.monitor = SystemMonitor()

    def test_get_system_info_basic(self):
        """测试获取系统基本信息"""
        info = self.monitor.get_system_info()
        assert info.timestamp > 0
        assert isinstance(info.hostname, str)
        assert isinstance(info.os_name, str)
        assert isinstance(info.kernel, str)
        assert info.uptime_hours > 0

    def test_cpu_info(self):
        """测试 CPU 信息"""
        info = self.monitor.get_system_info()
        assert info.cpu_cores > 0
        assert isinstance(info.cpu_model, str)
        # CPU 使用率应在合理范围内
        assert 0 <= info.cpu_usage_percent <= 100

    def test_memory_info(self):
        """测试内存信息"""
        info = self.monitor.get_system_info()
        assert info.memory_total_gb > 0
        assert info.memory_available_gb > 0
        assert info.memory_percent > 0

    def test_disk_info(self):
        """测试磁盘信息"""
        info = self.monitor.get_system_info()
        assert info.disk_total_gb > 0
        assert info.disk_free_gb > 0

    def test_python_version(self):
        """测试 Python 版本信息"""
        info = self.monitor.get_system_info()
        assert len(info.python_version) > 0
        assert info.python_version.startswith("3.")

    def test_torch_version(self):
        """测试 PyTorch 版本信息"""
        info = self.monitor.get_system_info()
        # 可能为 "未安装" 或具体版本号
        assert isinstance(info.torch_version, str)

    def test_gpu_info(self):
        """测试 GPU 信息"""
        info = self.monitor.get_system_info()
        assert isinstance(info.gpu_count, int)
        assert isinstance(info.gpu_info, list)
        if info.gpu_info:
            gpu = info.gpu_info[0]
            assert "name" in gpu
            assert "index" in gpu

    def test_format_html(self):
        """测试 HTML 格式化输出"""
        html = self.monitor.format_html()
        assert isinstance(html, str)
        assert len(html) > 0
        # 应包含关键 section 标题
        assert "系统信息" in html or "System" in html
        assert "CPU" in html
        assert "GPU" in html or "内存" in html

    def test_cache_mechanism(self):
        """测试缓存机制（get_system_info 每次调用更新，不缓存）"""
        import time
        # 第一次调用
        info1 = self.monitor.get_system_info()
        # 稍等片刻再调用
        time.sleep(0.01)
        info2 = self.monitor.get_system_info()
        # 每次调用获取新数据，timestamp 应不同
        assert info1.timestamp < info2.timestamp

    def test_global_monitor_singleton(self):
        """测试全局监控器单例"""
        assert global_monitor is not None
        assert isinstance(global_monitor, SystemMonitor)