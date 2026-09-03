from pathlib import Path

from autoflow.assistant import AppResolver, AssistantService, CommandRouter


class FakeConverter:
    def preview(self, source, destination):
        return {"source": source, "destination": destination, "files": [f"{source}/one.pdf"], "file_count": 1, "conflicts": []}

    def convert(self, source, destination):
        return {"destination": destination, "converted": 1, "skipped": 0, "needs_ocr": 0, "failed": 0, "items": []}


def test_plan_pdf_conversion_with_chinese_command():
    router = CommandRouter(converter=FakeConverter())
    plan = router.plan(r"把 D:\资料里的 PDF 转成 TXT 保存到 D:\输出")
    assert plan.intent == "pdf_to_txt"
    assert plan.requires_confirmation
    assert plan.arguments["source"] == r"D:\资料"
    assert plan.arguments["destination"] == r"D:\输出"


def test_open_known_file_and_auto_execute(tmp_path: Path):
    target = tmp_path / "说明.txt"
    target.write_text("ok", encoding="utf-8")
    opened = []
    service = AssistantService(CommandRouter(resolver=AppResolver(roots=[])), opener=lambda path, kind: opened.append((path, kind)))
    response = service.submit(f"打开 {target}")
    assert response["result"]["success"]
    assert opened == [(str(target.resolve()), "file")]


def test_unknown_command_is_not_executable():
    plan = CommandRouter().plan("给我做一杯咖啡")
    assert not plan.executable
    assert plan.status == "unsupported"


def test_confirmed_pdf_plan_runs_once():
    service = AssistantService(CommandRouter(converter=FakeConverter()))
    plan_id = service.submit(r"把 D:\资料里的 PDF 转成 TXT 保存到 D:\输出", auto_execute=False)["plan"]["id"]
    result = service.execute(plan_id)
    assert result["success"]


class FakeInterpreter:
    available = True

    def __init__(self, value=None, error=None):
        self.value = value
        self.error = error

    def interpret(self, command):
        if self.error:
            raise self.error
        return self.value

    def status(self):
        return {"provider": "DeepSeek", "model": "test", "configured": True}


def test_ai_interpretation_is_validated_then_executed(tmp_path: Path):
    target = tmp_path / "自然语言目标.txt"
    target.write_text("ok", encoding="utf-8")
    opened = []
    interpreter = FakeInterpreter({"intent": "open", "target": str(target), "source": None, "destination": None})
    service = AssistantService(CommandRouter(resolver=AppResolver(roots=[])), opener=lambda path, kind: opened.append((path, kind)), interpreter=interpreter)
    response = service.submit("劳驾把我刚才说的那个文档打开")
    assert response["ai_used"] is True
    assert response["result"]["success"] is True
    assert opened[0][0] == str(target.resolve())


def test_ai_failure_falls_back_to_local_parser(tmp_path: Path):
    target = tmp_path / "fallback.txt"
    target.write_text("ok", encoding="utf-8")
    opened = []
    service = AssistantService(CommandRouter(resolver=AppResolver(roots=[])), opener=lambda path, kind: opened.append((path, kind)), interpreter=FakeInterpreter(error=RuntimeError("offline")))
    response = service.submit(f"打开 {target}")
    assert response["ai_used"] is False
    assert "本地识别" in response["ai_warning"]
    assert response["result"]["success"] is True
