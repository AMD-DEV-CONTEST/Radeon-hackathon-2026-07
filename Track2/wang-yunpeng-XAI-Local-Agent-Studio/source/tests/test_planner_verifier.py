"""Phase 1A 测试: Planner + Verifier"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.cognition.planner import Planner
from core.cognition.verifier import Verifier


def test_planner_dev_task():
    p = Planner()
    plan = p.plan("开发一个电商网站", complexity=70)
    assert plan.goal == "开发一个电商网站"
    assert len(plan.steps) == 6
    assert plan.steps[0].agent == "hermes"
    assert plan.steps[2].agent == "grok"
    assert plan.steps[3].agent == "reviewer"
    print("✅ dev task: 6 steps, agents assigned correctly")

def test_planner_research_task():
    p = Planner()
    plan = p.plan("分析中国AI行业", complexity=60)
    assert len(plan.steps) == 5
    assert all(s.agent in ("hermes", "reviewer") for s in plan.steps)
    print("✅ research task: 5 steps")

def test_planner_fix_task():
    p = Planner()
    plan = p.plan("修复登录bug", complexity=50)
    assert len(plan.steps) == 4
    assert plan.steps[0].agent == "hermes"  # 诊断
    assert plan.steps[1].agent == "grok"    # 修复
    print("✅ fix task: 4 steps")

def test_planner_simple_task():
    p = Planner()
    plan = p.plan("你好", complexity=10)
    assert len(plan.steps) == 1
    print("✅ simple task: 1 step only")

def test_plan_next_pending_dependency():
    p = Planner()
    plan = p.plan("开发一个电商网站", complexity=70)
    n = plan.next_pending()
    assert n.step_id == 1  # 第一个没有依赖
    plan.steps[0].status = "done"
    n2 = plan.next_pending()
    assert n2.step_id == 2  # step 2 依赖 step 1
    print("✅ dependency chain: step 1 → step 2")

def test_verifier_pass():
    v = Verifier()
    r = v.verify("写一个hello world程序",
                 "这是一个Python hello world程序:\n```python\nprint('hello world')\n```\n\n运行结果正确。")
    assert r.passed
    assert r.score >= 0.6
    print(f"✅ verifier pass: score={r.score}")

def test_verifier_fail_empty():
    v = Verifier()
    r = v.verify("复杂任务", "")
    assert not r.passed
    print(f"✅ verifier empty: score={r.score}, issues={r.issues}")

def test_verifier_dangerous():
    v = Verifier()
    r = v.verify("清理文件", "执行命令: rm -rf /tmp/*")
    assert not r.passed   # 危险内容直接 0 分
    assert r.score == 0.0
    print(f"✅ verifier dangerous: score={r.score}")

def test_verifier_retry_limit():
    v = Verifier()
    r = v.verify("任务", "hi", retry_count=3)
    assert r.passed   # 超过重试限制，强制通过
    print(f"✅ verifier retry limit: forced pass at retry=3")


if __name__ == "__main__":
    test_planner_dev_task()
    test_planner_research_task()
    test_planner_fix_task()
    test_planner_simple_task()
    test_plan_next_pending_dependency()
    test_verifier_pass()
    test_verifier_fail_empty()
    test_verifier_dangerous()
    test_verifier_retry_limit()
    print("\n🎉 All Phase 1A tests passed!")
