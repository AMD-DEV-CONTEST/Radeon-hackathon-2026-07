from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Any

import gradio as gr
import httpx


DEFAULT_API_URL = os.getenv("OFFICE_AGENT_API_URL", "http://127.0.0.1:9000")

STATUS_LABEL: dict[str, str] = {
    "queued": "Queued",
    "scanning": "Scanning",
    "indexing": "Indexing",
    "retrieving": "Retrieving",
    "evaluating": "Evaluating",
    "drafting": "Drafting",
    "waiting_confirmation": "Waiting Confirmation",
    "completed": "Completed",
    "failed": "Failed",
    "cancelled": "Cancelled",
}


class ApiClient:
    def __init__(self, base_url: str) -> None:
        self.base_url = base_url.rstrip("/")

    def request(self, method: str, path: str, **kwargs: Any) -> Any:
        with httpx.Client(base_url=self.base_url, timeout=180) as client:
            response = client.request(method, path, **kwargs)
        if response.is_error:
            detail = response.text
            try:
                detail = response.json().get("detail", detail)
            except ValueError:
                pass
            raise gr.Error(f"API request failed ({response.status_code}): {detail}")
        return response.json()

    def list_projects(self) -> list[dict[str, Any]]:
        return self.request("GET", "/api/projects")

    def list_all_runs(self) -> list[dict[str, Any]]:
        return self.request("GET", "/api/runs")

    def cancel_run(self, project_id: str, run_id: str) -> dict[str, Any]:
        return self.request("DELETE", f"/api/projects/{project_id}/runs/{run_id}")


def _project_choices(client: ApiClient) -> list[str]:
    return [item["project_id"] for item in client.list_projects()]


# ---------------------------------------------------------------------------
# Stage E — Run History helpers
# ---------------------------------------------------------------------------


def _fmt_run_list(client: ApiClient) -> str:
    """Render the global run history as a Markdown table."""
    runs = client.list_all_runs()
    if not runs:
        return "No runs yet."
    lines = [
        "| Project | Run ID | Status | Step | Retries | Created |",
        "|---------|--------|--------|------|---------|---------|",
    ]
    for r in runs:
        abbrev = r["run_id"][:8]
        step = f"{r['current_step']}/{r.get('total_steps', 8)}"
        lines.append(
            f"| {r['project_id']} | {abbrev} | {STATUS_LABEL.get(r['status'], r['status'])} "
            f"| {step} | {r.get('retry_count', 0)} | {r['created_at'][:19]} |"
        )
    return "\n".join(lines)


def _fmt_run_detail(client: ApiClient, project_id: str, run_id: str) -> tuple[str, str]:
    """Return (progress_summary, timing_table) for a single run."""
    if not project_id or not run_id:
        return "No run selected.", ""
    try:
        progress = client.request("GET", f"/api/projects/{project_id}/runs/{run_id}/progress")
    except gr.Error:
        return "Run not found or inaccessible.", ""

    steps = progress.get("timing_by_step", [])
    timing_lines = [
        "| Step | Started | Elapsed (ms) | File | Error |",
        "|------|---------|-------------|------|-------|",
    ]
    for s in steps:
        err = (s.get("error") or "-")[:60]
        f = (s.get("current_file") or "-")
        elapsed = s.get("elapsed_ms", "-")
        started = s.get("started_at", "")[:19]
        timing_lines.append(
            f"| {s['step']} | {started} | {elapsed} | {f} | {err} |"
        )

    summary = (
        f"**Status:** {STATUS_LABEL.get(progress['status'], progress['status'])}  \n"
        f"**Step:** {progress['current_step']}/{progress.get('total_steps', 8)} "
        f"({progress['percentage']}%)  \n"
        f"**Current:** {progress.get('current_step_name', '')}  \n"
        f"**File:** {progress.get('current_file') or '—'}  \n"
        f"**Retries:** {progress.get('retry_count', 0)}  \n"
        f"**Error:** {progress.get('error_summary') or '—'}"
    )
    return summary, "\n".join(timing_lines) if len(steps) > 0 else "No step timing recorded yet."


def _poll_progress(client: ApiClient, project_id: str, run_id: str, max_wait: int = 180) -> tuple[str, str, str]:
    """Poll progress until run finishes, updating every 2s."""
    if not project_id or not run_id:
        return "Select a project and run_id.", "", ""
    elapsed = 0
    while elapsed < max_wait:
        progress = client.request("GET", f"/api/projects/{project_id}/runs/{run_id}/progress")
        status = progress["status"]
        summary, timing = _fmt_run_detail(client, project_id, run_id)
        if status in ("completed", "failed", "cancelled"):
            return summary, timing, _fmt_run_list(client)
        time.sleep(2)
        elapsed += 2
    summary, timing = _fmt_run_detail(client, project_id, run_id)
    return summary + "\n\n*Polling timeout — run may still be in progress.*", timing, _fmt_run_list(client)


def build_workbench(api_url: str = DEFAULT_API_URL) -> gr.Blocks:
    client = ApiClient(api_url)

    def refresh_projects() -> gr.Dropdown:
        return gr.Dropdown(choices=_project_choices(client))

    def create_project(project_id: str, name: str, description: str) -> tuple[gr.Dropdown, str]:
        project = client.request(
            "POST",
            "/api/projects",
            json={"project_id": project_id, "name": name, "description": description or None},
        )
        choices = _project_choices(client)
        return gr.Dropdown(choices=choices, value=project["project_id"]), "Project created."

    def upload_files(project_id: str, references: list[str] | None, task_file: str | None) -> str:
        if not project_id:
            raise gr.Error("Select a project first.")
        uploaded: list[str] = []
        for filename in references or []:
            with Path(filename).open("rb") as handle:
                result = client.request(
                    "POST",
                    f"/api/projects/{project_id}/files",
                    files={"file": (Path(filename).name, handle)},
                )
            uploaded.append(result["relative_path"])
        if task_file:
            with Path(task_file).open("rb") as handle:
                result = client.request(
                    "POST",
                    f"/api/projects/{project_id}/files",
                    data={"task_file": "true"},
                    files={"file": (Path(task_file).name, handle)},
                )
            uploaded.append(result["relative_path"])
        return "Uploaded:\n" + "\n".join(f"- `{path}`" for path in uploaded)

    def run_report(project_id: str) -> tuple[dict[str, Any], dict[str, Any], str, str]:
        if not project_id:
            raise gr.Error("Select a project first.")
        queued = client.request("POST", f"/api/projects/{project_id}/runs")
        run_id = queued["run_id"]
        # Trigger background execution
        client.request("POST", f"/api/projects/{project_id}/runs/{run_id}/execute")
        # A real model run can take longer than two seconds. Do not fetch its
        # artifacts until the background run reaches a terminal state.
        result: dict[str, Any] | None = None
        for _ in range(90):
            result = client.request("GET", f"/api/projects/{project_id}/runs/{run_id}")
            if result["status"] in {"completed", "failed", "cancelled"}:
                break
            time.sleep(2)
        if result is None or result["status"] not in {"completed", "failed", "cancelled"}:
            raise gr.Error("Run is still in progress; use Run history to monitor it.")
        if result["status"] != "completed":
            return result, {"evaluations": []}, "## Downloads\nNo artifacts: run did not complete.", _fmt_run_list(client)
        details = client.request("GET", f"/api/projects/{project_id}/runs/{run_id}/artifacts/result")
        links = []
        for label, artifact in (("Markdown report", "report"), ("Risk CSV", "risk_csv"), ("Next-week plan", "next_week_plan")):
            if artifact in result["artifacts"]:
                url = f"{api_url.rstrip('/')}/api/projects/{project_id}/runs/{run_id}/artifacts/{artifact}"
                links.append(f"- [{label}]({url})")
        downloads_md = "## Downloads\n" + "\n".join(links)
        history = _fmt_run_list(client)
        return result, details, downloads_md, history

    # Stage E — cancel run
    def cancel_selected(project_id: str, run_id: str) -> tuple[str, str]:
        if not project_id or not run_id:
            return "Select a project and run.", _fmt_run_list(client)
        try:
            client.cancel_run(project_id, run_id)
            return f"Cancel requested for {run_id[:8]}", _fmt_run_list(client)
        except gr.Error as exc:
            return str(exc), _fmt_run_list(client)

    # Stage E — refresh history
    def refresh_history() -> str:
        return _fmt_run_list(client)

    # Stage E — view run detail
    def view_run_detail(project_id: str, run_id: str) -> tuple[str, str]:
        return _fmt_run_detail(client, project_id, run_id)

    with gr.Blocks(title="ProjectPack Office Agent") as demo:
        gr.Markdown("# ProjectPack Office Agent\nUpload project evidence and one task list, then create an auditable report.")

        # Shared state for run history (updated from both tabs)
        history_state = gr.State("")

        # ── Project & Upload (tab) ──
        with gr.Tab("Report Generation"):
            with gr.Row():
                project_selector = gr.Dropdown(label="Project", choices=[], interactive=True)
                refresh = gr.Button("Refresh projects")
            with gr.Accordion("Create project", open=False):
                new_id = gr.Textbox(label="Project ID", placeholder="lowercase-project-id")
                new_name = gr.Textbox(label="Project name")
                new_description = gr.Textbox(label="Description")
                create = gr.Button("Create project")
                create_status = gr.Markdown()
            with gr.Accordion("Upload source files", open=True):
                references = gr.File(label="Reference files (MD/TXT/PDF/DOCX/XLSX)", file_count="multiple", type="filepath")
                task_file_upload = gr.File(label="Task list (CSV/XLSX)", file_count="single", type="filepath")
                upload = gr.Button("Upload files")
                upload_status = gr.Markdown()
            run = gr.Button("Generate project report", variant="primary")
            run_state = gr.JSON(label="Run status")
            evaluations = gr.JSON(label="Task status and source evidence")
            downloads = gr.Markdown()

            refresh.click(refresh_projects, outputs=project_selector)
            demo.load(refresh_projects, outputs=project_selector)
            create.click(create_project, inputs=[new_id, new_name, new_description], outputs=[project_selector, create_status])
            upload.click(upload_files, inputs=[project_selector, references, task_file_upload], outputs=upload_status)
            run.click(run_report, inputs=project_selector, outputs=[run_state, evaluations, downloads, history_state])

        # ── Run History (tab) ──
        with gr.Tab("Run History"):
            history_md = gr.Markdown("Loading...")
            with gr.Row():
                history_refresh_btn = gr.Button("Refresh history")
            with gr.Row():
                hist_project = gr.Dropdown(label="Project", choices=[], interactive=True, allow_custom_value=True)
                hist_run_id = gr.Textbox(label="Run ID", placeholder="e.g. abc123 (first 8 chars)")
            with gr.Row():
                view_btn = gr.Button("View detail")
                cancel_btn = gr.Button("Cancel run", variant="stop")
            detail_status = gr.Markdown("Select a run to view details.")
            timing_table = gr.Markdown("")
            cancel_result = gr.Markdown("")

            # Sync history_state changes to the history tab
            history_state.change(fn=lambda x: x, inputs=history_state, outputs=history_md)

            history_refresh_btn.click(refresh_history, outputs=history_md)
            view_btn.click(view_run_detail, inputs=[hist_project, hist_run_id], outputs=[detail_status, timing_table])
            cancel_btn.click(cancel_selected, inputs=[hist_project, hist_run_id], outputs=[cancel_result, history_md])
            # Sync project selector with main tab
            refresh.click(refresh_projects, outputs=hist_project)
            demo.load(
                lambda: (_project_choices(client), _fmt_run_list(client)),
                outputs=[hist_project, history_md],
            )

    return demo
