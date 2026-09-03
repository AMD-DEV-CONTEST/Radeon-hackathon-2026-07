"""AutoFlow desktop GUI.

The GUI is intentionally a thin presentation layer over the existing planner,
capture, compiler, registry, replay, and repair modules.  ``AutoFlowService``
contains the orchestration so it can be tested without creating a Tk window.
"""

from __future__ import annotations

import threading
import tkinter as tk
from collections.abc import Callable
from tkinter import messagebox, scrolledtext, ttk
from typing import Any

from autoflow.capture.agent import ComputerUseAgent
from autoflow.compiler import BundleCompiler
from autoflow.models import Bundle, Recording, RunResult
from autoflow.planner import create_planner
from autoflow.registry import SkillRegistry
from autoflow.repair import RepairAgent
from autoflow.replay import ReplayEngine

ProgressCallback = Callable[[str], None]


class AutoFlowService:
    """Application service shared by the GUI and its tests."""

    def create_task(
        self,
        task: str,
        *,
        task_name: str = "",
        url: str = "",
        use_mock: bool = True,
        headless: bool = True,
        params: dict[str, Any] | None = None,
        progress: ProgressCallback | None = None,
    ) -> Bundle:
        task = task.strip()
        if not task:
            raise ValueError("请输入任务描述。")

        notify = progress or (lambda _message: None)
        backend_name = "mock" if use_mock else "web"
        context = {
            "app_name": task_name.strip() or "AutoFlow Desktop",
            "backend": backend_name,
            "url": url.strip(),
        }

        notify("正在生成任务计划…")
        planner = create_planner(mock=use_mock)
        plan = planner.plan(task, context=context)
        notify(f"已生成 {len(plan.steps)} 个步骤。")

        recording = Recording(
            recording_id=f"rec_{plan.task_id}",
            app_name=context["app_name"],
            backend=backend_name,
            metadata={"url": context["url"]},
        )
        backend = self._make_backend(
            use_mock=use_mock,
            url=context["url"],
            headless=headless,
        )

        notify("正在首次执行并录制…")
        agent = ComputerUseAgent(backend=backend, recording=recording)
        plan = agent.execute(plan, params=params or {})

        notify("正在编译确定性 Bundle…")
        bundle = BundleCompiler().compile(recording, plan, version=1)
        tags = [task_name.strip()] if task_name.strip() else []
        SkillRegistry().register(bundle, tags=tags)
        notify(f"任务已注册：{bundle.task_id}")
        return bundle

    def list_tasks(self) -> list[dict[str, Any]]:
        return SkillRegistry().list_all()

    def get_task(self, task_id: str) -> Bundle:
        bundle = SkillRegistry().get(task_id)
        if bundle is None:
            raise ValueError(f"未找到任务：{task_id}")
        return bundle

    def run_task(
        self,
        task_id: str,
        *,
        params: dict[str, Any] | None = None,
        url: str = "",
        headless: bool = True,
        progress: ProgressCallback | None = None,
    ) -> RunResult:
        notify = progress or (lambda _message: None)
        registry = SkillRegistry()
        bundle = registry.get(task_id)
        if bundle is None:
            raise ValueError(f"未找到任务：{task_id}")

        backend_name = bundle.metadata.get("backend", "web")
        run_url = url.strip() or bundle.metadata.get(
            "environment_fingerprint", {}
        ).get("url", "")
        notify(f"正在运行 {bundle.goal}（v{bundle.version}）…")
        backend = self._make_backend(
            use_mock=backend_name == "mock",
            url=run_url,
            headless=headless,
        )
        result = ReplayEngine(backend=backend).replay(bundle, params=params or {})
        registry.record_run(bundle.task_id, result.status)
        notify(f"运行结束：{result.status}")
        return result

    def repair_task(
        self,
        task_id: str,
        *,
        progress: ProgressCallback | None = None,
    ) -> Bundle:
        notify = progress or (lambda _message: None)
        registry = SkillRegistry()
        bundle = registry.get(task_id)
        if bundle is None:
            raise ValueError(f"未找到任务：{task_id}")

        failed_step = next(
            (step.index for step in bundle.steps if step.risk.get("level") == "high"),
            bundle.steps[-1].index if bundle.steps else 0,
        )
        halt_report = {
            "task_id": bundle.task_id,
            "goal": bundle.goal,
            "failed_step": failed_step,
            "reason": "元素定位失败（GUI 演示诊断）",
            "evidence_used": "structural",
            "current_screen": None,
        }

        notify("正在诊断失败原因…")
        agent = RepairAgent()
        diagnosis = agent.diagnose(halt_report, bundle)
        notify(f"修复策略：{diagnosis.get('strategy', 'A')}")
        repaired = agent.apply(bundle, diagnosis)
        registry.register(repaired)
        notify(f"已生成 v{repaired.version}。")
        return repaired

    @staticmethod
    def _make_backend(*, use_mock: bool, url: str, headless: bool) -> Any:
        if use_mock:
            from autoflow.capture.mock import MockBackend

            return MockBackend()

        from autoflow.capture.web import WebBackend

        return WebBackend(url=url, headless=headless)


class AutoFlowApp:
    """Tkinter desktop shell for the AutoFlow MVP."""

    BG = "#f4f7fb"
    CARD = "#ffffff"
    TEXT = "#172033"
    MUTED = "#64748b"
    ACCENT = "#2563eb"
    SUCCESS = "#059669"

    def __init__(self, root: tk.Tk, service: AutoFlowService | None = None) -> None:
        self.root = root
        self.service = service or AutoFlowService()
        self.busy = False
        self._task_rows: dict[str, dict[str, Any]] = {}

        self.root.title("AutoFlow Desktop · 办公自动化助手")
        self.root.geometry("1180x760")
        self.root.minsize(980, 650)
        self.root.configure(bg=self.BG)

        self.task_name_var = tk.StringVar()
        self.url_var = tk.StringVar()
        self.param_var = tk.StringVar(value="示例内容")
        self.mock_var = tk.BooleanVar(value=True)
        self.headless_var = tk.BooleanVar(value=True)
        self.status_var = tk.StringVar(value="就绪")
        self.total_tasks_var = tk.StringVar(value="0")
        self.total_runs_var = tk.StringVar(value="0")
        self.success_rate_var = tk.StringVar(value="—")
        self.detail_title_var = tk.StringVar(value="请选择一个任务")
        self.detail_meta_var = tk.StringVar(value="步骤详情将在这里显示")

        self._configure_style()
        self._build_layout()
        self.refresh_tasks()

    def _configure_style(self) -> None:
        style = ttk.Style(self.root)
        if "clam" in style.theme_names():
            style.theme_use("clam")
        style.configure("App.TFrame", background=self.BG)
        style.configure("Card.TFrame", background=self.CARD)
        style.configure(
            "Title.TLabel",
            background=self.BG,
            foreground=self.TEXT,
            font=("Segoe UI", 22, "bold"),
        )
        style.configure(
            "Subtitle.TLabel",
            background=self.BG,
            foreground=self.MUTED,
            font=("Segoe UI", 10),
        )
        style.configure(
            "CardTitle.TLabel",
            background=self.CARD,
            foreground=self.TEXT,
            font=("Segoe UI", 12, "bold"),
        )
        style.configure(
            "CardText.TLabel",
            background=self.CARD,
            foreground=self.MUTED,
            font=("Segoe UI", 9),
        )
        style.configure(
            "Metric.TLabel",
            background=self.CARD,
            foreground=self.ACCENT,
            font=("Segoe UI", 20, "bold"),
        )
        style.configure(
            "Accent.TButton",
            font=("Segoe UI", 10, "bold"),
            foreground="#ffffff",
            background=self.ACCENT,
            padding=(14, 9),
        )
        style.map("Accent.TButton", background=[("active", "#1d4ed8")])
        style.configure("Soft.TButton", font=("Segoe UI", 9), padding=(10, 7))
        style.configure("Treeview", rowheight=29, font=("Segoe UI", 9))
        style.configure("Treeview.Heading", font=("Segoe UI", 9, "bold"))
        style.configure(
            "Status.TLabel",
            background="#e8eefc",
            foreground="#1e40af",
            padding=(10, 5),
        )

    def _build_layout(self) -> None:
        shell = ttk.Frame(self.root, style="App.TFrame", padding=22)
        shell.pack(fill="both", expand=True)

        header = ttk.Frame(shell, style="App.TFrame")
        header.pack(fill="x", pady=(0, 16))
        ttk.Label(header, text="AutoFlow", style="Title.TLabel").pack(side="left")
        ttk.Label(
            header,
            text="把自然语言任务编译成可重复运行的自动化流程",
            style="Subtitle.TLabel",
        ).pack(side="left", padx=(14, 0), pady=(11, 0))
        ttk.Label(header, textvariable=self.status_var, style="Status.TLabel").pack(
            side="right", pady=(7, 0)
        )

        metrics = ttk.Frame(shell, style="App.TFrame")
        metrics.pack(fill="x", pady=(0, 14))
        self._metric_card(metrics, "已注册任务", self.total_tasks_var).pack(
            side="left", fill="x", expand=True, padx=(0, 8)
        )
        self._metric_card(metrics, "累计运行", self.total_runs_var).pack(
            side="left", fill="x", expand=True, padx=8
        )
        self._metric_card(metrics, "成功率", self.success_rate_var).pack(
            side="left", fill="x", expand=True, padx=(8, 0)
        )

        body = ttk.Panedwindow(shell, orient="horizontal")
        body.pack(fill="both", expand=True)

        control = ttk.Frame(body, style="Card.TFrame", padding=18)
        workspace = ttk.Frame(body, style="Card.TFrame", padding=18)
        body.add(control, weight=2)
        body.add(workspace, weight=5)
        self._build_control_panel(control)
        self._build_workspace(workspace)

        footer = ttk.Frame(shell, style="App.TFrame")
        footer.pack(fill="x", pady=(12, 0))
        self.progress = ttk.Progressbar(footer, mode="indeterminate", length=180)
        self.progress.pack(side="right")
        ttk.Label(
            footer,
            text="默认使用 Mock 后端，可离线体验完整链路",
            style="Subtitle.TLabel",
        ).pack(side="left")

    def _metric_card(self, parent: ttk.Frame, title: str, variable: tk.StringVar) -> ttk.Frame:
        card = ttk.Frame(parent, style="Card.TFrame", padding=(16, 11))
        ttk.Label(card, text=title, style="CardText.TLabel").pack(anchor="w")
        ttk.Label(card, textvariable=variable, style="Metric.TLabel").pack(anchor="w")
        return card

    def _build_control_panel(self, parent: ttk.Frame) -> None:
        ttk.Label(parent, text="创建自动化任务", style="CardTitle.TLabel").pack(anchor="w")
        ttk.Label(
            parent,
            text="描述你希望 AutoFlow 完成的操作。",
            style="CardText.TLabel",
        ).pack(anchor="w", pady=(2, 10))

        self.task_text = tk.Text(
            parent,
            height=4,
            width=34,
            wrap="word",
            relief="solid",
            borderwidth=1,
            font=("Microsoft YaHei UI", 10),
            foreground=self.TEXT,
        )
        self.task_text.pack(fill="x", pady=(0, 10))
        self.task_text.insert("1.0", "在表单中填写内容并提交")

        self._labeled_entry(parent, "任务名称（可选）", self.task_name_var)
        self._labeled_entry(parent, "目标 URL（Web 模式）", self.url_var)
        self._labeled_entry(parent, "note_content 参数", self.param_var)

        options = ttk.Frame(parent, style="Card.TFrame")
        options.pack(fill="x", pady=(2, 12))
        ttk.Checkbutton(options, text="Mock 演示模式", variable=self.mock_var).pack(
            side="left"
        )
        ttk.Checkbutton(options, text="后台运行浏览器", variable=self.headless_var).pack(
            side="right"
        )

        self.create_button = ttk.Button(
            parent,
            text="创建并录制流程",
            style="Accent.TButton",
            command=self.create_task,
        )
        self.create_button.pack(fill="x", pady=(0, 8))

        actions = ttk.Frame(parent, style="Card.TFrame")
        actions.pack(fill="x")
        self.run_button = ttk.Button(
            actions, text="运行所选", style="Soft.TButton", command=self.run_selected
        )
        self.run_button.pack(side="left", fill="x", expand=True, padx=(0, 4))
        self.repair_button = ttk.Button(
            actions, text="修复所选", style="Soft.TButton", command=self.repair_selected
        )
        self.repair_button.pack(side="left", fill="x", expand=True, padx=(4, 0))

        ttk.Separator(parent).pack(fill="x", pady=14)
        ttk.Label(parent, text="执行日志", style="CardTitle.TLabel").pack(anchor="w")
        self.log = scrolledtext.ScrolledText(
            parent,
            height=8,
            width=34,
            wrap="word",
            state="disabled",
            relief="flat",
            background="#0f172a",
            foreground="#dbeafe",
            insertbackground="#ffffff",
            font=("Cascadia Mono", 9),
        )
        self.log.pack(fill="both", expand=True, pady=(7, 0))
        self._append_log("AutoFlow Desktop 已就绪。")

    def _labeled_entry(self, parent: ttk.Frame, title: str, variable: tk.StringVar) -> None:
        ttk.Label(parent, text=title, style="CardText.TLabel").pack(anchor="w")
        ttk.Entry(parent, textvariable=variable).pack(fill="x", pady=(3, 9))

    def _build_workspace(self, parent: ttk.Frame) -> None:
        top = ttk.Frame(parent, style="Card.TFrame")
        top.pack(fill="x")
        ttk.Label(top, text="技能库", style="CardTitle.TLabel").pack(side="left")
        ttk.Button(top, text="刷新", style="Soft.TButton", command=self.refresh_tasks).pack(
            side="right"
        )

        columns = ("goal", "version", "runs", "rate")
        self.task_tree = ttk.Treeview(parent, columns=columns, show="tree headings", height=8)
        self.task_tree.heading("#0", text="Task ID")
        self.task_tree.heading("goal", text="任务目标")
        self.task_tree.heading("version", text="版本")
        self.task_tree.heading("runs", text="运行")
        self.task_tree.heading("rate", text="成功率")
        self.task_tree.column("#0", width=120, stretch=False)
        self.task_tree.column("goal", width=330)
        self.task_tree.column("version", width=55, anchor="center", stretch=False)
        self.task_tree.column("runs", width=55, anchor="center", stretch=False)
        self.task_tree.column("rate", width=70, anchor="center", stretch=False)
        self.task_tree.pack(fill="x", pady=(10, 14))
        self.task_tree.bind("<<TreeviewSelect>>", self._on_task_selected)

        detail_header = ttk.Frame(parent, style="Card.TFrame")
        detail_header.pack(fill="x", pady=(0, 8))
        ttk.Label(
            detail_header,
            textvariable=self.detail_title_var,
            style="CardTitle.TLabel",
        ).pack(anchor="w")
        ttk.Label(
            detail_header,
            textvariable=self.detail_meta_var,
            style="CardText.TLabel",
        ).pack(anchor="w", pady=(2, 0))

        detail_columns = ("action", "description", "risk", "evidence")
        self.step_tree = ttk.Treeview(
            parent, columns=detail_columns, show="tree headings", height=9
        )
        self.step_tree.heading("#0", text="#")
        self.step_tree.heading("action", text="动作")
        self.step_tree.heading("description", text="步骤描述")
        self.step_tree.heading("risk", text="风险")
        self.step_tree.heading("evidence", text="定位证据")
        self.step_tree.column("#0", width=35, anchor="center", stretch=False)
        self.step_tree.column("action", width=75, anchor="center", stretch=False)
        self.step_tree.column("description", width=300)
        self.step_tree.column("risk", width=65, anchor="center", stretch=False)
        self.step_tree.column("evidence", width=180)
        self.step_tree.pack(fill="both", expand=True)

    def create_task(self) -> None:
        task = self.task_text.get("1.0", "end").strip()
        if not task:
            messagebox.showwarning("缺少任务", "请输入任务描述。", parent=self.root)
            return
        params = {"note_content": self.param_var.get()}
        self._append_log(f"> 创建：{task}")
        self._run_async(
            "正在创建任务…",
            lambda: self.service.create_task(
                task,
                task_name=self.task_name_var.get(),
                url=self.url_var.get(),
                use_mock=self.mock_var.get(),
                headless=self.headless_var.get(),
                params=params,
                progress=self._thread_log,
            ),
            self._created,
        )

    def run_selected(self) -> None:
        task_id = self._selected_task_id()
        if task_id is None:
            return
        self._append_log(f"> 运行：{task_id}")
        self._run_async(
            "正在运行任务…",
            lambda: self.service.run_task(
                task_id,
                params={"note_content": self.param_var.get()},
                url=self.url_var.get(),
                headless=self.headless_var.get(),
                progress=self._thread_log,
            ),
            self._ran,
        )

    def repair_selected(self) -> None:
        task_id = self._selected_task_id()
        if task_id is None:
            return
        self._append_log(f"> 修复：{task_id}")
        self._run_async(
            "正在修复任务…",
            lambda: self.service.repair_task(task_id, progress=self._thread_log),
            self._repaired,
        )

    def refresh_tasks(self) -> None:
        try:
            entries = self.service.list_tasks()
        except Exception as exc:
            self._append_log(f"读取技能库失败：{exc}")
            return

        selected = self._selected_task_id(warn=False)
        for item in self.task_tree.get_children():
            self.task_tree.delete(item)
        self._task_rows = {entry["task_id"]: entry for entry in entries}

        total_runs = 0
        total_success = 0
        for entry in entries:
            stats = entry.get("executions", {})
            runs = int(stats.get("count", 0))
            success = int(stats.get("success", 0))
            total_runs += runs
            total_success += success
            rate = f"{success / runs:.0%}" if runs else "—"
            task_id = entry["task_id"]
            self.task_tree.insert(
                "",
                "end",
                iid=task_id,
                text=task_id,
                values=(
                    entry.get("goal", ""),
                    f"v{entry.get('latest_version', 1)}",
                    runs,
                    rate,
                ),
            )

        self.total_tasks_var.set(str(len(entries)))
        self.total_runs_var.set(str(total_runs))
        self.success_rate_var.set(
            f"{total_success / total_runs:.0%}" if total_runs else "—"
        )
        if selected and self.task_tree.exists(selected):
            self.task_tree.selection_set(selected)
            self.task_tree.focus(selected)
            self._show_task(selected)

    def _on_task_selected(self, _event: tk.Event[Any]) -> None:
        task_id = self._selected_task_id(warn=False)
        if task_id:
            self._show_task(task_id)

    def _show_task(self, task_id: str) -> None:
        try:
            bundle = self.service.get_task(task_id)
        except Exception as exc:
            self._append_log(str(exc))
            return
        for item in self.step_tree.get_children():
            self.step_tree.delete(item)
        for step in bundle.steps:
            evidence = " → ".join(item.value for item in step.resolution_ladder)
            self.step_tree.insert(
                "",
                "end",
                text=str(step.index + 1),
                values=(
                    step.action.get("type", ""),
                    step.description,
                    step.risk.get("level", ""),
                    evidence,
                ),
            )
        backend = bundle.metadata.get("backend", "web")
        self.detail_title_var.set(bundle.goal)
        self.detail_meta_var.set(
            f"{bundle.task_id} · v{bundle.version} · {backend} · {len(bundle.steps)} 个步骤"
        )

    def _created(self, bundle: Bundle) -> None:
        self._append_log(f"✓ 创建完成：{bundle.task_id}")
        self.refresh_tasks()
        if self.task_tree.exists(bundle.task_id):
            self.task_tree.selection_set(bundle.task_id)
            self.task_tree.focus(bundle.task_id)
            self._show_task(bundle.task_id)

    def _ran(self, result: RunResult) -> None:
        for step in result.steps:
            evidence = step.evidence_used.value if step.evidence_used else "—"
            self._append_log(f"  步骤 {step.index + 1}: {step.status} · {evidence}")
        symbol = "✓" if result.status == "success" else "!"
        self._append_log(f"{symbol} 运行结果：{result.status}（{result.run_id}）")
        self.refresh_tasks()

    def _repaired(self, bundle: Bundle) -> None:
        self._append_log(f"✓ 已生成修复版本：v{bundle.version}")
        self.refresh_tasks()
        if self.task_tree.exists(bundle.task_id):
            self.task_tree.selection_set(bundle.task_id)
            self._show_task(bundle.task_id)

    def _selected_task_id(self, *, warn: bool = True) -> str | None:
        selected = self.task_tree.selection()
        if selected:
            return selected[0]
        if warn:
            messagebox.showinfo("请选择任务", "请先在技能库中选择一个任务。", parent=self.root)
        return None

    def _run_async(
        self,
        label: str,
        worker: Callable[[], Any],
        on_success: Callable[[Any], None],
    ) -> None:
        if self.busy:
            messagebox.showinfo("任务进行中", "请等待当前操作完成。", parent=self.root)
            return
        self.busy = True
        self.status_var.set(label)
        self.progress.start(10)
        self._set_actions_enabled(False)

        def run() -> None:
            try:
                result = worker()
            except Exception as exc:  # GUI boundary: surface actionable errors to user.
                self.root.after(0, lambda: self._operation_failed(exc))
                return
            self.root.after(0, lambda: self._operation_succeeded(result, on_success))

        threading.Thread(target=run, daemon=True).start()

    def _operation_succeeded(self, result: Any, callback: Callable[[Any], None]) -> None:
        self._finish_operation("就绪")
        callback(result)

    def _operation_failed(self, exc: Exception) -> None:
        self._finish_operation("操作失败")
        self._append_log(f"✗ {exc}")
        messagebox.showerror("AutoFlow 操作失败", str(exc), parent=self.root)

    def _finish_operation(self, status: str) -> None:
        self.busy = False
        self.status_var.set(status)
        self.progress.stop()
        self._set_actions_enabled(True)

    def _set_actions_enabled(self, enabled: bool) -> None:
        state = "normal" if enabled else "disabled"
        for button in (self.create_button, self.run_button, self.repair_button):
            button.configure(state=state)

    def _thread_log(self, message: str) -> None:
        self.root.after(0, self._append_log, message)

    def _append_log(self, message: str) -> None:
        self.log.configure(state="normal")
        self.log.insert("end", message.rstrip() + "\n")
        self.log.see("end")
        self.log.configure(state="disabled")


def main() -> None:
    root = tk.Tk()
    try:
        root.tk.call("tk", "scaling", 1.1)
    except tk.TclError:
        pass
    AutoFlowApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
