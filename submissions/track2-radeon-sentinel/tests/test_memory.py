from radeon_sentinel.memory import CaseMemory


def test_case_memory_is_isolated() -> None:
    memory = CaseMemory(":memory:")
    try:
        memory.record_message("case-a", "user", "alpha")
        memory.record_message("case-b", "user", "beta")
        memory.record_event("case-a", "tool_result", {"status": "ok"})

        assert [item["content"] for item in memory.history("case-a")] == [
            "alpha"
        ]
        assert [item["content"] for item in memory.history("case-b")] == [
            "beta"
        ]
        assert memory.audit("case-a")[0]["payload"]["status"] == "ok"
        assert memory.audit("case-b") == []
    finally:
        memory.close()
