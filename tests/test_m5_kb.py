#!/usr/bin/env python3
"""M5 知识库功能测试 — 验证 DB schema / FTS 检索 / runbook CRUD / write_runbook

不依赖 LLM 和集群, 纯本地测试 DB + KB 逻辑。
运行: python -m tests.test_m5_kb
"""
import os
import sys
import tempfile

# 添加项目根目录到 path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))


def test_m5_kb():
    """测试 M5 知识库功能"""
    from src.db import Store
    from src.tools import set_store, execute_tool

    # 用临时 DB
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name

    try:
        store = Store(db_path)
        set_store(store)

        print("=" * 60)
        print("M5 知识库功能测试")
        print("=" * 60)

        # 1. 验证种子数据
        rbs = store.get_runbooks()
        assert len(rbs) >= 6, f"种子数据应>=6条, 实际 {len(rbs)}"
        print(f"[PASS] 种子数据: {len(rbs)} 条 runbook")
        for rb in rbs:
            print(f"       - {rb['id']}: {rb['title']} [{rb['status']}]")

        # 2. 验证 stats
        all_rbs = store.get_runbooks()
        stats = {
            "total": len(all_rbs),
            "approved": len([r for r in all_rbs if r["status"] == "approved"]),
            "pending": len([r for r in all_rbs if r["status"] == "pending_review"]),
            "agent_generated": len([r for r in all_rbs if r["source"] == "agent_generated"]),
        }
        assert stats["approved"] >= 5, f"approved 应>=5, 实际 {stats['approved']}"
        assert stats["agent_generated"] >= 1, f"agent_generated 应>=1, 实际 {stats['agent_generated']}"
        # 种子数据全部 approved (种子是预审核的)
        assert stats["total"] == stats["approved"], f"种子应全 approved, total={stats['total']} approved={stats['approved']}"
        print(f"[PASS] 统计: total={stats['total']} approved={stats['approved']} agent_gen={stats['agent_generated']}")

        # 3. 测试 FTS5 检索
        results = store.search_runbooks_fts("DataNode OOM", limit=5)
        assert len(results) > 0, "FTS 应匹配 DataNode OOM"
        assert any("DataNode" in r["title"] for r in results), "应找到 DataNode 相关"
        print(f"[PASS] FTS5 检索 'DataNode OOM': {len(results)} 条匹配")
        for r in results:
            print(f"       - {r['title']} (score={r['score']:.4f})")

        # 4. 测试中文检索
        results = store.search_runbooks_fts("磁盘满", limit=5)
        assert len(results) > 0, "FTS 应匹配 '磁盘满'"
        print(f"[PASS] FTS5 中文检索 '磁盘满': {len(results)} 条匹配")

        # 5. 测试 runbook CRUD
        new_id = store.upsert_runbook({
            "title": "测试 Runbook",
            "content": "这是一个测试条目, 用于验证 CRUD 功能",
            "tags": "test,crud",
            "source": "manual",
            "status": "approved",
            "updated_by": "test",
        })
        rb = store.get_runbook(new_id)
        assert rb["title"] == "测试 Runbook", "创建后应能读取"
        print(f"[PASS] CRUD 创建: id={new_id}")

        # 更新
        store.upsert_runbook({
            "id": new_id, "title": "更新后的标题", "content": "更新内容",
            "tags": "test,updated", "source": "manual", "status": "approved",
            "updated_by": "test",
        })
        rb = store.get_runbook(new_id)
        assert rb["title"] == "更新后的标题", "更新后标题应变化"
        print(f"[PASS] CRUD 更新: title='{rb['title']}'")

        # 删除
        store.delete_runbook(new_id)
        rb = store.get_runbook(new_id)
        assert not rb, "删除后应不存在"
        print(f"[PASS] CRUD 删除: id={new_id}")

        # 6. 测试 write_runbook 工具 (通过 execute_tool)
        result = execute_tool("write_runbook", {
            "title": "TestNode 故障修复",
            "content": "症状: TestNode 宕机. 修复: 重启. 验证: 状态检查.",
            "tags": "test,node",
            "confidence": 0.9,
            "session_id": "test_session",
        })
        assert "id" in result, f"write_runbook 应返回 id, 实际: {result}"
        assert result["status"] == "pending_review", "agent 回写应为 pending_review"
        print(f"[PASS] write_runbook 工具: id={result['id']} status={result['status']}")

        # 7. 测试置信度门控 (低于 0.7 拒绝)
        result = execute_tool("write_runbook", {
            "title": "低置信度测试",
            "content": "不应写入",
            "confidence": 0.5,
        })
        assert result.get("rejected"), f"低置信度应被拒绝, 实际: {result}"
        print(f"[PASS] 置信度门控: confidence=0.5 被拒绝")

        # 8. 测试审核流程
        # 先写一个 pending_review
        result = execute_tool("write_runbook", {
            "title": "待审核测试",
            "content": "待审核内容",
            "confidence": 0.85,
            "session_id": "test_session",
        })
        rb_id = result["id"]
        # 审核通过
        store.review_runbook(rb_id, "approved", "test-reviewer")
        rb = store.get_runbook(rb_id)
        assert rb["status"] == "approved", "审核后应为 approved"
        assert rb["updated_by"] == "test-reviewer", "审核人应记录"
        print(f"[PASS] 审核流程: pending_review -> approved")

        # 9. 测试 search_kb 工具 (降级模式, 无 bge 时用 FTS)
        result = execute_tool("search_kb", {"query": "NameNode SIGTERM"})
        assert result["matches"] > 0, f"search_kb 应有匹配, 实际: {result}"
        assert result.get("search_mode") in ("bm25", "static_fallback", "hybrid")
        print(f"[PASS] search_kb 工具: mode={result['search_mode']} matches={result['matches']}")
        for r in result["results"]:
            print(f"       - {r['title']}")

        print("=" * 60)
        print("所有 M5 测试通过! [OK]")
        print("=" * 60)
        return True

    except AssertionError as e:
        print(f"\n[FAIL] 测试失败: {e}")
        import traceback
        traceback.print_exc()
        return False
    except Exception as e:
        print(f"\n[ERROR] 测试异常: {e}")
        import traceback
        traceback.print_exc()
        return False
    finally:
        # 清理临时 DB
        try:
            os.unlink(db_path)
        except Exception:
            pass


if __name__ == "__main__":
    success = test_m5_kb()
    sys.exit(0 if success else 1)
