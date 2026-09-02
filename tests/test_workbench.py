from app.ui.workbench import build_workbench


def test_workbench_builds_without_requiring_a_live_api() -> None:
    workbench = build_workbench("http://127.0.0.1:9")
    assert workbench is not None
