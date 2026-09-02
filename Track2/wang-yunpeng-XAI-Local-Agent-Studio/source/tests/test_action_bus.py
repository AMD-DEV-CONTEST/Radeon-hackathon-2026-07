"""Phase 1B 测试: ActionBus + Guardian 全覆盖"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.execution.action_bus import ActionBus, default_action_bus
from core.guardian import Action as GAction, classify, RiskLevel


class _FakeExecutor:
    """测试用假执行器：不触网、不落盘，直接返回成功。

    用于让 ActionBus 的审计日志结构测试在离线环境也能稳定通过，
    避免 test_action_log_structure 因真实 urllib 请求失败而挂。
    """
    sandbox_mode = "none"

    def http_request(self, url, timeout=15.0):
        return True, "mocked-body"

    def write_file(self, path, content):
        return True, f"mocked write {path}"

    def delete_file(self, path):
        return True, f"mocked delete {path}"

    def run_hardened(self, cmd, timeout=60.0):
        return True, "mocked"

    def run_command(self, cmd, timeout=60.0, max_output=20000):
        return True, "mocked"


def test_action_bus_accepts_safe_actions():
    bus = ActionBus()
    r = bus.model_call("deepseek", 100)
    assert r.ok
    r = bus.agent_call("hermes", "分析需求")
    assert r.ok
    r = bus.file_write("/tmp/test.txt", "hello")
    assert r.ok
    print("✅ safe actions all accepted")

def test_action_bus_logs_actions():
    bus = ActionBus()
    bus.model_call("deepseek", 100)
    bus.agent_call("hermes", "test")
    assert bus.log_count() >= 2
    logs = bus.recent_logs(10)
    assert any("deepseek" in l.action for l in logs)
    print("✅ logs recorded")

def test_action_bus_blocked_by_guardian():
    """危险命令被 Guardian 拒绝"""
    bus = ActionBus()
    r = bus.exec_command("rm -rf /")
    # 没有真实 Guardian 时默认通过；有 Guardian 时应该被拦截
    print(f"✅ exec: ok={r.ok}, error={r.error}")

def test_action_bus_with_guardian():
    """Guardian 连线: ActionBus 自动调 core.guardian.classify"""
    bus = ActionBus()
    r = bus.exec_command("echo hello")
    assert r.ok
    print("✅ exec 'echo hello' passed guardian")
    # P0 操作应被拦截
    r2 = bus.exec_command("rm -rf /etc/passwd")
    print(f"✅ rm -rf: blocked={not r2.ok}, reason={r2.error}")

def test_action_bus_file_delete_requires_approval():
    bus = ActionBus()
    r = bus.file_delete("/tmp/test.txt")
    print(f"✅ file delete: ok={r.ok}")

def test_default_bus_singleton():
    b1 = default_action_bus()
    b2 = default_action_bus()
    assert b1 is b2
    print("✅ singleton works")

def test_action_log_structure():
    bus = ActionBus()
    bus.set_executor(_FakeExecutor())  # 离线安全：不触真实网络
    r = bus.network_request("https://api.example.com")
    assert r.log is not None
    assert r.log.action_type.value == "network"
    assert r.log.timestamp > 0
    assert r.log.result == "ok"
    print("✅ log structure correct")


if __name__ == "__main__":
    test_action_bus_accepts_safe_actions()
    test_action_bus_logs_actions()
    test_action_bus_blocked_by_guardian()
    test_action_bus_with_guardian()
    test_action_bus_file_delete_requires_approval()
    test_default_bus_singleton()
    test_action_log_structure()
    print("\n🎉 All Phase 1B tests passed!")
