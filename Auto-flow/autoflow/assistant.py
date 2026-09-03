"""Natural-language command planning and safe local execution."""

from __future__ import annotations

import os
import re
import shutil
import threading
import uuid
import webbrowser
from dataclasses import asdict, dataclass, field
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlparse

from autoflow.pdf_tools import PDFTextConverter
from autoflow.deepseek import DeepSeekInterpreter


@dataclass(slots=True)
class CommandPlan:
    id: str
    command: str
    intent: str
    title: str
    message: str
    steps: list[str] = field(default_factory=list)
    arguments: dict[str, Any] = field(default_factory=dict)
    requires_confirmation: bool = False
    executable: bool = True
    risk: str = "low"
    status: str = "planned"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class AppResolver:
    ALIASES = {
        "酷狗音乐": ("酷狗", "kugou", "kgmusic"),
        "酷狗": ("酷狗", "kugou", "kgmusic"),
        "微信": ("微信", "wechat", "weixin"),
        "飞书": ("飞书", "feishu", "lark"),
        "谷歌浏览器": ("google chrome", "chrome"),
        "浏览器": ("microsoft edge", "edge", "google chrome", "chrome"),
        "记事本": ("notepad",),
        "计算器": ("calculator", "calc"),
    }
    SYSTEM_FOLDERS = {
        "桌面": Path.home() / "Desktop",
        "下载": Path.home() / "Downloads",
        "下载文件夹": Path.home() / "Downloads",
        "文档": Path.home() / "Documents",
        "图片": Path.home() / "Pictures",
    }

    def __init__(self, roots: list[Path] | None = None) -> None:
        self.roots = roots or self._default_roots()

    @staticmethod
    def _default_roots() -> list[Path]:
        values = [
            Path(os.environ.get("PROGRAMDATA", "C:/ProgramData")) / "Microsoft/Windows/Start Menu/Programs",
            Path(os.environ.get("APPDATA", "")) / "Microsoft/Windows/Start Menu/Programs",
            Path.home() / "Desktop",
        ]
        return [path for path in values if str(path) and path.exists()]

    def resolve(self, target: str) -> dict[str, str] | None:
        raw = target.strip().strip('"\'“”').rstrip("。！")
        if raw in self.SYSTEM_FOLDERS and self.SYSTEM_FOLDERS[raw].exists():
            return {"name": raw, "path": str(self.SYSTEM_FOLDERS[raw]), "kind": "folder"}
        possible_path = Path(os.path.expandvars(raw)).expanduser()
        if possible_path.exists():
            return {"name": possible_path.name or str(possible_path), "path": str(possible_path.resolve()), "kind": "folder" if possible_path.is_dir() else "file"}
        parsed = urlparse(raw if "://" in raw else "")
        if parsed.scheme in {"http", "https"} and parsed.netloc:
            return {"name": raw, "path": raw, "kind": "url"}

        terms = self.ALIASES.get(raw, (raw,))
        command_aliases = {"记事本": "notepad.exe", "计算器": "calc.exe"}
        if raw in command_aliases:
            found = shutil.which(command_aliases[raw]) or command_aliases[raw]
            return {"name": raw, "path": found, "kind": "application"}
        candidates: list[tuple[float, Path]] = []
        for root in self.roots:
            for item in root.rglob("*"):
                if not item.is_file() or item.suffix.lower() not in {".lnk", ".exe", ".url"}:
                    continue
                name = item.stem.casefold()
                score = max(self._score(term.casefold(), name) for term in terms)
                if score >= 0.58:
                    candidates.append((score, item))
        if not candidates:
            for term in terms:
                found = shutil.which(term)
                if found:
                    return {"name": raw, "path": found, "kind": "application"}
            return None
        _, best = max(candidates, key=lambda pair: (pair[0], -len(str(pair[1]))))
        return {"name": best.stem, "path": str(best.resolve()), "kind": "application"}

    @staticmethod
    def _score(query: str, name: str) -> float:
        if query == name:
            return 1.0
        if query in name:
            return 0.92
        if name in query:
            return 0.82
        return SequenceMatcher(None, query, name).ratio()


class CommandRouter:
    DESTINATION_MARKERS = ("并保存到", "保存到", "输出到", "存到", "放到")

    def __init__(self, resolver: AppResolver | None = None, converter: PDFTextConverter | None = None) -> None:
        self.resolver = resolver or AppResolver()
        self.converter = converter or PDFTextConverter()

    def plan(self, command: str) -> CommandPlan:
        command = command.strip()
        plan_id = uuid.uuid4().hex[:12]
        if not command:
            return CommandPlan(plan_id, command, "unknown", "还没收到指令", "请告诉我你希望电脑做什么。", executable=False, status="needs_input")
        upper = command.upper()
        if "PDF" in upper and "TXT" in upper and any(word in command for word in ("转", "转换", "提取")):
            return self._plan_pdf(plan_id, command)
        if re.search(r"(?:打开|启动|运行|帮我开)", command):
            target = re.sub(r"^.*?(?:打开|启动|运行|帮我开)(?:一下)?", "", command, count=1).strip(" ，,。！!")
            if not target:
                return CommandPlan(plan_id, command, "open", "需要打开什么？", "请补充应用、文件、文件夹或网址名称。", executable=False, status="needs_input")
            resolved = self.resolver.resolve(target)
            if resolved is None:
                return CommandPlan(plan_id, command, "open", f"没找到“{target}”", "你可以直接告诉我它的安装路径，或者先创建桌面/开始菜单快捷方式。", arguments={"target": target}, executable=False, status="needs_input")
            return CommandPlan(plan_id, command, "open", f"打开{resolved['name']}", f"已找到：{resolved['path']}", [f"打开{resolved['kind']}：{resolved['path']}"], {"resolved": resolved})
        return CommandPlan(plan_id, command, "unknown", "这条指令暂时不会", "目前可以打开应用、文件、文件夹、网页，以及把 PDF 批量转换为 TXT。", executable=False, status="unsupported")

    def plan_structured(self, command: str, interpretation: dict[str, Any]) -> CommandPlan:
        """Validate an AI interpretation through the deterministic planner."""
        intent = interpretation.get("intent")
        if intent == "open":
            target = interpretation.get("target")
            if not isinstance(target, str) or not target.strip():
                return CommandPlan(uuid.uuid4().hex[:12], command, "open", "需要打开什么？", "AI 没有识别出明确目标，请补充名称或路径。", executable=False, status="needs_input")
            return self.plan(f"打开 {target.strip()}")
        if intent == "pdf_to_txt":
            source = interpretation.get("source")
            destination = interpretation.get("destination")
            if not isinstance(source, str) or not isinstance(destination, str) or not source.strip() or not destination.strip():
                return CommandPlan(uuid.uuid4().hex[:12], command, "pdf_to_txt", "路径不完整", "请补充 PDF 来源和 TXT 保存位置。", executable=False, status="needs_input")
            canonical = f'把 "{source.strip()}"里的 PDF 转成 TXT 保存到 "{destination.strip()}"'
            return self._plan_pdf(uuid.uuid4().hex[:12], canonical)
        return CommandPlan(uuid.uuid4().hex[:12], command, "unknown", "AI 判断当前能力还做不了", "目前可以打开应用、文件、文件夹、网页，以及把 PDF 转成 TXT。", executable=False, status="unsupported")

    def _plan_pdf(self, plan_id: str, command: str) -> CommandPlan:
        marker = next((item for item in self.DESTINATION_MARKERS if item in command), None)
        if marker is None:
            return CommandPlan(plan_id, command, "pdf_to_txt", "还缺保存位置", "请在指令后补充“保存到 D:\\输出文件夹”。", executable=False, status="needs_input")
        left, destination = command.split(marker, 1)
        destination = self._clean_path(destination)
        source_text = re.sub(r"^.*?把", "", left, count=1) if "把" in left else re.sub(r"^.*?从", "", left, count=1)
        source = re.split(r"(?:里的|中的|下面的|下的|内的)?\s*(?:所有)?\s*PDF", source_text, maxsplit=1, flags=re.IGNORECASE)[0]
        source = self._clean_path(source)
        if not source or not destination:
            return CommandPlan(plan_id, command, "pdf_to_txt", "路径不完整", "请写清 PDF 所在位置和 TXT 保存位置。", executable=False, status="needs_input")
        try:
            preview = self.converter.preview(source, destination)
        except ValueError as exc:
            return CommandPlan(plan_id, command, "pdf_to_txt", "无法准备转换", str(exc), {"source": source, "destination": destination}, executable=False, status="needs_input")
        if preview["file_count"] == 0:
            return CommandPlan(plan_id, command, "pdf_to_txt", "没有找到 PDF", f"在 {source} 中没有找到 PDF 文件。", arguments=preview, executable=False, status="needs_input")
        conflict_note = f"；其中 {len(preview['conflicts'])} 个 TXT 已存在，将跳过" if preview["conflicts"] else ""
        return CommandPlan(
            plan_id, command, "pdf_to_txt", f"转换 {preview['file_count']} 个 PDF", f"将保存到 {preview['destination']}{conflict_note}",
            [f"读取 {preview['file_count']} 个 PDF", "提取每一页文字并写入 UTF-8 TXT", "重新读取输出文件进行验证"],
            preview, requires_confirmation=True, risk="medium",
        )

    @staticmethod
    def _clean_path(value: str) -> str:
        value = value.strip().strip('"\'“”').strip(" ，,。；;！!")
        value = re.sub(r"(?:文件夹|目录)$", "", value).strip()
        return value


class AssistantService:
    def __init__(self, router: CommandRouter | None = None, opener: Callable[[str, str], None] | None = None, interpreter: DeepSeekInterpreter | None = None) -> None:
        self.router = router or CommandRouter()
        self.opener = opener or self._open
        self.interpreter = interpreter or DeepSeekInterpreter()
        self._plans: dict[str, CommandPlan] = {}
        self._lock = threading.RLock()

    def submit(self, command: str, *, auto_execute: bool = True) -> dict[str, Any]:
        ai_used = False
        ai_warning = ""
        if self.interpreter.available:
            try:
                plan = self.router.plan_structured(command, self.interpreter.interpret(command))
                ai_used = True
            except (RuntimeError, OSError) as exc:
                plan = self.router.plan(command)
                ai_warning = f"AI 暂时不可用，已切换本地识别：{exc}"
        else:
            plan = self.router.plan(command)
        with self._lock:
            self._plans[plan.id] = plan
        payload: dict[str, Any] = {"plan": plan.to_dict(), "ai_used": ai_used, "ai_warning": ai_warning}
        if auto_execute and plan.executable and not plan.requires_confirmation:
            payload["result"] = self.execute(plan.id)
        return payload

    def settings(self) -> dict[str, Any]:
        return self.interpreter.status()

    def configure_deepseek(self, api_key: str) -> dict[str, Any]:
        self.interpreter.configure(api_key)
        return self.settings()

    def configure_provider(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self.interpreter.configure_provider(
            provider=str(payload.get("provider", "")),
            api_key=str(payload.get("api_key", "")),
            base_url=str(payload.get("base_url", "")),
            model=str(payload.get("model", "")),
            account_id=str(payload.get("account_id", "")),
            account_header=str(payload.get("account_header", "X-Account-ID")),
        )

    def select_model(self, model: str) -> dict[str, Any]:
        return self.interpreter.select_model(model)

    def disconnect_deepseek(self) -> dict[str, Any]:
        return self.interpreter.disconnect()

    def execute(self, plan_id: str) -> dict[str, Any]:
        with self._lock:
            plan = self._plans.get(plan_id)
            if plan is None:
                raise ValueError("这条指令已失效，请重新发送。")
            if not plan.executable:
                raise ValueError("这条指令还不能执行。")
            if plan.status == "completed":
                raise ValueError("这条指令已经执行过了。")
            plan.status = "running"
        try:
            if plan.intent == "open":
                resolved = plan.arguments["resolved"]
                self.opener(resolved["path"], resolved["kind"])
                result = {"success": True, "message": f"已经为你打开：{resolved['name']}"}
            elif plan.intent == "pdf_to_txt":
                converted = self.router.converter.convert(plan.arguments["source"], plan.arguments["destination"])
                result = {"success": converted["failed"] == 0 and converted["needs_ocr"] == 0, "message": f"转换完成：成功 {converted['converted']} 个，跳过 {converted['skipped']} 个，需要 OCR {converted['needs_ocr']} 个，失败 {converted['failed']} 个。", "details": converted}
            else:
                raise ValueError("暂不支持执行这类指令。")
            plan.status = "completed"
            return result
        except Exception:
            plan.status = "failed"
            raise

    @staticmethod
    def _open(path: str, kind: str) -> None:
        if kind == "url":
            if not webbrowser.open(path):
                raise RuntimeError("浏览器没有成功打开网址。")
        elif os.name == "nt":
            os.startfile(path)  # type: ignore[attr-defined]
        else:
            raise RuntimeError("当前系统暂不支持打开本地目标。")
