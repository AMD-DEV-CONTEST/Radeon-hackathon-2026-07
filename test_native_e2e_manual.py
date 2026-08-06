#!/usr/bin/env python3
"""
手动端到端测试：验证原生运行时模式下 Agent 的完整生命周期
使用简单的 echo 工具避免依赖复杂的 MCP 服务器
"""
import os
import sys
import time
from pathlib import Path

# 确保原生运行时模式
os.environ["AGENTFACTORY_NATIVE_RUNTIME"] = "1"

from agent_factory.factory_graph.frontend_bridge.agent_package_runtime import (
    AgentPackageRuntimeManager,
)
from agent_factory.native_runtime import NativeAgentRuntimeLauncher


def test_basic_runtime():
    """测试基本的运行时启动和关闭"""
    print("=" * 60)
    print("测试 1: 基本运行时启动")
    print("=" * 60)

    # 查找一个可用的 agent package
    packages_dir = Path(".agentfactory/packages")
    if not packages_dir.exists():
        print("✗ .agentfactory/packages/ 目录不存在")
        return False

    package_dirs = [d for d in packages_dir.iterdir() if d.is_dir() and (d / "agent_package.json").exists()]
    if not package_dirs:
        print("✗ 未找到可用的 agent package")
        return False

    package_id = package_dirs[0].name
    print(f"✓ 使用 package: {package_id}")

    # 创建运行时管理器（自动选择 NativeAgentRuntimeLauncher）
    manager = AgentPackageRuntimeManager()

    try:
        print("\n初始化运行时...")
        result = manager.initialize_package(package_id)
        session_id = result.get("session_id")
        print(f"✓ 会话创建成功: {session_id}")

        print("\n检查进程是否启动...")
        # 给进程一些时间启动
        time.sleep(2)

        # 检查是否有系统句柄（原生运行时）
        if hasattr(manager, '_system_handles'):
            handles = manager._system_handles
            print(f"✓ 活跃系统句柄数: {len(handles)}")
            if handles:
                print("✓ 原生运行时已启动")
                for key, handle in list(handles.items())[:3]:
                    print(f"  - {key}: PID {getattr(handle, 'pid', 'N/A')}")
            else:
                print("⚠ 没有活跃的系统句柄")
        else:
            print("⚠ 无法检查系统句柄")

        print("\n关闭运行时...")
        manager.shutdown_package_instance(package_id)
        print("✓ 运行时已关闭")

        time.sleep(1)

        # 检查句柄是否清理
        if hasattr(manager, '_system_handles'):
            handles_after = manager._system_handles
            if not handles_after:
                print("✓ 系统句柄已清理")
            else:
                print(f"⚠ 仍有 {len(handles_after)} 个系统句柄未清理")

        print("✓ 测试完成")
        return True

    except Exception as e:
        print(f"✗ 测试失败: {e}")
        import traceback
        traceback.print_exc()
        return False


def main():
    print("\n原生运行时端到端测试")
    print("环境变量: AGENTFACTORY_NATIVE_RUNTIME =", os.environ.get("AGENTFACTORY_NATIVE_RUNTIME"))
    print()

    results = []

    # 测试 1: 基本运行时
    results.append(("基本运行时", test_basic_runtime()))

    # 总结
    print("\n" + "=" * 60)
    print("测试总结")
    print("=" * 60)
    for name, passed in results:
        status = "✓ 通过" if passed else "✗ 失败"
        print(f"{status}: {name}")

    all_passed = all(r[1] for r in results)
    print()
    if all_passed:
        print("✓ 所有测试通过")
        return 0
    else:
        print("✗ 部分测试失败")
        return 1


if __name__ == "__main__":
    sys.exit(main())
