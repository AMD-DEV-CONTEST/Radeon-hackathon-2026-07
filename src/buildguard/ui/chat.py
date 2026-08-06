"""Chat-first Streamlit experience for BuildGuard-Radeon."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import streamlit as st

from buildguard.ui.api_client import LocalApiClient
from buildguard.ui.chat_state import (
    append_message,
    initialize_chat_state,
    record_result,
    reset_chat,
    select_session,
)
from buildguard.ui.view_models import (
    ChatResultView,
    normalize_agent_result,
    normalize_message,
    risk_summary,
)

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png"}
VIDEO_EXTENSIONS = {".mp4", ".avi", ".mov", ".mkv"}
CHAT_ATTACHMENT_TYPES = ["jpg", "jpeg", "png", "mp4", "avi", "mov", "mkv"]


def _safe_get(
    client: LocalApiClient,
    path: str,
    *,
    params: dict[str, Any] | None = None,
) -> Any:
    try:
        return client.get(path, params=params)
    except Exception:
        return None


def render_system_status(health: dict[str, Any]) -> None:
    """Render only status already supplied by the health API."""
    semantic = health.get("semantic_router", {})
    semantic = semantic if isinstance(semantic, dict) else {}
    columns = st.columns(4)
    columns[0].metric("API", "在线" if health.get("status") == "ok" else "降级")
    columns[1].metric("LLM", "正常" if health.get("llm_healthy") else "降级")
    columns[2].metric("视觉路由", "已驻留" if semantic.get("loaded") else "按需加载")
    columns[3].metric("摄像头", int(health.get("cameras_configured") or 0))


def render_session_sidebar(client: LocalApiClient) -> None:
    initialize_chat_state(st.session_state)
    st.sidebar.divider()
    st.sidebar.markdown("#### 对话记录")
    if st.sidebar.button("＋ 新建对话", use_container_width=True, type="primary"):
        reset_chat(st.session_state)
        st.rerun()
    query = (
        st.sidebar.text_input(
            "搜索会话",
            placeholder="搜索最近会话",
            key="session_search",
            label_visibility="collapsed",
        )
        .strip()
        .casefold()
    )
    sessions = _safe_get(client, "/sessions", params={"limit": 100}) or []
    if not isinstance(sessions, list):
        sessions = []
    st.sidebar.caption("最近会话")
    visible = 0
    for item in sessions:
        if not isinstance(item, dict) or not item.get("id"):
            continue
        title = str(item.get("title") or item["id"])
        if query and query not in title.casefold() and query not in str(item["id"]).casefold():
            continue
        session_id = str(item["id"])
        active = session_id == st.session_state.get("active_session_id")
        label = f"{'● ' if active else ''}{title[:30]}"
        if st.sidebar.button(label, key=f"session-{session_id}", use_container_width=True):
            select_session(st.session_state, session_id)
            st.rerun()
        visible += 1
        if visible >= 20:
            break
    if not visible:
        st.sidebar.caption("暂无匹配会话")


def _task_result(task: dict[str, Any]) -> dict[str, Any]:
    stored = task.get("result")
    result = dict(stored) if isinstance(stored, dict) else {}
    agent_state = result.get("agent_state")
    if isinstance(agent_state, dict):
        result = dict(agent_state)
    result.setdefault("session_id", task.get("session_id"))
    result.setdefault("task_id", task.get("id"))
    result.setdefault("status", task.get("status"))
    return result


def _load_active_session(client: LocalApiClient) -> None:
    initialize_chat_state(st.session_state)
    session_id = st.session_state.get("active_session_id")
    if not session_id or st.session_state.get("loaded_session_id") == session_id:
        return
    messages = client.get(f"/sessions/{session_id}/messages", params={"limit": 500})
    tasks = client.get("/tasks", params={"session_id": session_id, "limit": 100})
    task_map = {
        str(item["id"]): _task_result(item)
        for item in tasks
        if isinstance(item, dict) and item.get("id")
    }
    normalized = []
    for raw_message in messages:
        message = normalize_message(raw_message)
        task_id = message["metadata"].get("task_id")
        if task_id and str(task_id) in task_map:
            message["metadata"]["result"] = task_map[str(task_id)]
        normalized.append(message)
    st.session_state["chat_messages"] = normalized
    st.session_state["chat_results"] = list(task_map.values())
    waiting = next(
        (item for item in task_map.values() if item.get("status") == "WAIT_FOR_CONFIRMATION"),
        None,
    )
    st.session_state["pending_confirmation"] = waiting
    st.session_state["loaded_session_id"] = session_id


def _render_risks(view: ChatResultView) -> None:
    if not view.risks:
        return
    summary = risk_summary(view.risks)
    st.markdown("**风险概览**")
    columns = st.columns(max(1, min(4, len(summary))))
    for column, (severity, count) in zip(columns, sorted(summary.items()), strict=False):
        column.metric(severity.upper(), count)
    with st.expander("查看风险明细"):
        st.dataframe(view.risks, use_container_width=True)


def _render_visuals(view: ChatResultView) -> None:
    if not view.visual_evidence:
        return
    st.markdown("**视觉证据**")
    for index, item in enumerate(view.visual_evidence):
        label = str(item.get("label") or item.get("metadata", {}).get("label") or "检测结果")
        confidence = item.get("confidence")
        caption = f"{label} · {float(confidence):.1%}" if confidence is not None else label
        visualization = item.get("visualization_path") or item.get("source_path")
        if visualization and Path(str(visualization)).is_file():
            st.image(str(visualization), caption=caption)
        mask = item.get("mask_path")
        if mask and Path(str(mask)).is_file():
            st.image(str(mask), caption=f"{label} · 分割掩码 {index + 1}")


def _render_citations(view: ChatResultView) -> None:
    if not view.citations:
        return
    with st.expander(f"法规与知识依据（{len(view.citations)}）"):
        for item in view.citations[:20]:
            source = item.get("source") or item.get("source_path") or "本地知识库"
            article = item.get("article")
            page = item.get("page")
            location = " · ".join(str(value) for value in (article, page) if value is not None)
            st.markdown(f"- `{item.get('chunk_id', 'unknown')}` — {source} {location}")
            if item.get("content"):
                st.caption(str(item["content"])[:500])


def _render_report_downloads(
    client: LocalApiClient,
    view: ChatResultView,
    *,
    key_prefix: str,
) -> None:
    if not view.report_paths:
        return
    st.markdown("**报告文件**")
    report_id = view.raw.get("report_id")
    for label, path in view.report_paths:
        suffix = {"Markdown": "md", "HTML": "html", "PDF": "pdf"}[label]
        columns = st.columns([3, 1])
        columns[0].code(path)
        if report_id and columns[1].button(
            f"准备下载 {label}",
            key=f"{key_prefix}-prepare-{suffix}",
        ):
            content, filename = client.get_bytes(
                f"/reports/{report_id}/download",
                params={"format": suffix},
            )
            st.download_button(
                f"下载 {label}",
                content,
                file_name=filename,
                key=f"{key_prefix}-download-{suffix}",
            )


def _confirm_task(
    client: LocalApiClient,
    view: ChatResultView,
    *,
    approved: bool,
) -> None:
    if not view.task_id:
        st.error("确认任务缺少 task_id。")
        return
    result = client.post(
        "/agent/confirm",
        {"task_id": view.task_id, "approved": approved},
    )
    record_result(st.session_state, result)
    st.rerun()


def _render_result(
    client: LocalApiClient,
    result: dict[str, Any],
    *,
    key_prefix: str,
) -> None:
    view = normalize_agent_result(result)
    if view.status == "WAIT_FOR_CONFIRMATION":
        st.warning("此任务需要人工确认后才能继续写入或执行。")
    elif view.status in {"failed", "safe_failure"}:
        st.error("任务安全终止。")
    else:
        st.caption(f"状态：{view.status} · 任务：{view.task_id or '未记录'}")
    st.markdown(view.content)
    if view.errors:
        with st.expander("错误与诊断", expanded=True):
            for error in view.errors:
                st.error(error)
    if view.plan is not None:
        with st.expander("执行计划"):
            st.json(view.plan)
    if view.tool_results:
        with st.expander("工具执行状态"):
            st.dataframe(view.tool_results, use_container_width=True)
    _render_risks(view)
    _render_visuals(view)
    _render_citations(view)
    _render_report_downloads(client, view, key_prefix=key_prefix)
    if view.status == "WAIT_FOR_CONFIRMATION":
        if view.pending_confirmation:
            with st.expander("待确认参数", expanded=True):
                st.json(view.pending_confirmation)
        approve, reject = st.columns(2)
        if approve.button("确认执行", type="primary", key=f"{key_prefix}-approve"):
            _confirm_task(client, view, approved=True)
        if reject.button("拒绝执行", key=f"{key_prefix}-reject"):
            _confirm_task(client, view, approved=False)
    with st.expander("开发信息"):
        st.json(view.raw)


def _render_timeline(client: LocalApiClient) -> None:
    messages = st.session_state.get("chat_messages", [])
    if not messages:
        with st.chat_message("assistant"):
            st.markdown(
                "你好，我是 BuildGuard。点击输入框左侧的＋可以上传施工现场图片或视频，"
                "也可以直接询问风险、法规依据和历史巡检结果。"
            )
        return
    for index, message in enumerate(messages):
        role = str(message.get("role") or "assistant")
        with st.chat_message(role):
            result = message.get("metadata", {}).get("result")
            if role == "assistant" and isinstance(result, dict):
                _render_result(client, result, key_prefix=f"result-{index}")
            else:
                st.markdown(str(message.get("content") or ""))
            attachments = message.get("metadata", {}).get("attachments", [])
            if isinstance(attachments, list) and attachments:
                st.caption("附件：" + "、".join(str(item) for item in attachments))


def _recover_stream_task(
    client: LocalApiClient,
    session_id: str | None,
    task_id: str | None,
) -> dict[str, Any] | None:
    if not task_id:
        return None
    task = _safe_get(client, f"/agent/tasks/{task_id}")
    if not isinstance(task, dict):
        return None
    task.setdefault("session_id", session_id)
    task.setdefault("task_id", task_id)
    return task


def _run_chat_request(client: LocalApiClient, payload: dict[str, Any]) -> None:
    st.session_state["chat_busy"] = True
    accepted_session: str | None = None
    accepted_task: str | None = None
    result: dict[str, Any] | None = None
    with st.status("正在提交任务…", expanded=True) as status:
        try:
            for event in client.stream_chat(payload):
                event_name = event["event"]
                data = event["data"]
                if event_name == "accepted":
                    accepted_session = str(data.get("session_id") or "") or None
                    accepted_task = str(data.get("task_id") or "") or None
                    st.session_state["active_stream_task"] = accepted_task
                    status.write(f"任务已接收：{accepted_task}")
                elif event_name == "phase":
                    phase_message = str(
                        data.get("message") or data.get("phase") or "正在处理任务…"
                    )
                    status.update(
                        label=phase_message,
                        state="running",
                        expanded=True,
                    )
                elif event_name == "confirmation_required":
                    status.update(
                        label="任务等待人工确认",
                        state="running",
                        expanded=True,
                    )
                elif event_name == "complete":
                    result = data
                elif event_name == "error":
                    result = {
                        **data,
                        "status": "safe_failure",
                        "final_response": str(data.get("message") or "任务执行失败。"),
                    }
            if result is None:
                raise RuntimeError("流式接口未返回完成事件")
        except Exception as exc:
            recovered = _recover_stream_task(client, accepted_session, accepted_task)
            if recovered is not None and recovered.get("status") != "running":
                result = recovered
                status.write("流式连接中断，已从任务存储恢复结果。")
            elif accepted_task is None:
                status.write("流式接口不可用，正在回退到同步接口。")
                result = client.post("/agent/chat", payload)
            else:
                result = {
                    "session_id": accepted_session,
                    "task_id": accepted_task,
                    "status": "safe_failure",
                    "final_response": (
                        "界面流式连接中断。任务可能仍在服务器执行，请从历史任务恢复。"
                    ),
                    "errors": [str(exc)],
                }
        status.update(
            label="等待人工确认" if result.get("status") == "WAIT_FOR_CONFIRMATION" else "任务完成",
            state="complete" if result.get("status") not in {"failed", "safe_failure"} else "error",
            expanded=False,
        )
    st.session_state["last_chat_request"] = dict(payload)
    record_result(st.session_state, result)
    st.session_state["attachment_generation"] = (
        int(st.session_state["attachment_generation"]) + 1
    )
    st.session_state["chat_busy"] = False
    st.session_state["active_stream_task"] = None
    st.rerun()


def split_chat_attachments(uploads: list[Any]) -> tuple[list[Any], list[Any]]:
    """Classify native chat-input attachments and reject ambiguous batches."""
    images: list[Any] = []
    videos: list[Any] = []
    unsupported: list[str] = []
    for upload in uploads:
        name = str(getattr(upload, "name", ""))
        suffix = Path(name).suffix.casefold()
        if suffix in IMAGE_EXTENSIONS:
            images.append(upload)
        elif suffix in VIDEO_EXTENSIONS:
            videos.append(upload)
        else:
            unsupported.append(name or "未命名文件")
    if unsupported:
        raise ValueError(f"不支持的附件：{'、'.join(unsupported)}")
    if videos and images:
        raise ValueError("一次消息不能混合上传图片和视频，请分开发送。")
    if len(videos) > 1:
        raise ValueError("当前视频巡检每次只支持一个视频。")
    return images, videos


def _upload_chat_attachments(
    client: LocalApiClient,
    uploads: list[Any],
) -> tuple[list[str], list[str]]:
    images, videos = split_chat_attachments(uploads)
    response: dict[str, Any] = {}
    if images:
        response = client.upload_images(images)
    elif videos:
        response = client.upload_videos(videos)
    failures = response.get("failures", []) if response else []
    if failures:
        messages = [
            f"{item.get('original_name', '附件')}：{item.get('error', '上传失败')}"
            for item in failures
            if isinstance(item, dict)
        ]
        raise ValueError("；".join(messages) or "附件上传失败")
    paths = [
        str(item["storage_path"])
        for item in response.get("uploaded", [])
        if isinstance(item, dict) and item.get("storage_path")
    ]
    if uploads and len(paths) != len(uploads):
        raise ValueError("部分附件没有返回可用的存储路径")
    return paths, [str(getattr(item, "name", "附件")) for item in uploads]


def _chat_submission(value: Any) -> tuple[str, list[Any]]:
    if isinstance(value, str):
        return value.strip(), []
    return str(getattr(value, "text", "")).strip(), list(
        getattr(value, "files", []) or []
    )


def render_chat_page(client: LocalApiClient, health: dict[str, Any]) -> None:
    initialize_chat_state(st.session_state)
    _load_active_session(client)
    st.title("BuildGuard-Radeon")
    st.caption("本地 AMD/ROCm 施工安全巡检智能体")
    render_system_status(health)
    st.divider()
    _render_timeline(client)
    submission = st.chat_input(
        "询问施工安全问题，或点击左侧＋上传图片/视频…",
        key=f"agent-chat-{st.session_state.get('attachment_generation', 0)}",
        accept_file="multiple",
        file_type=CHAT_ATTACHMENT_TYPES,
        max_upload_size=512,
        disabled=bool(st.session_state.get("chat_busy")),
    )
    if submission is not None:
        prompt, uploads = _chat_submission(submission)
        if not prompt and not uploads:
            return
        try:
            attachment_paths, attachment_names = _upload_chat_attachments(client, uploads)
        except ValueError as exc:
            st.error(str(exc))
            return
        if not prompt:
            prompt = (
                "请检查这个视频中的施工安全隐患。"
                if uploads and Path(str(uploads[0].name)).suffix.casefold() in VIDEO_EXTENSIONS
                else "请检查这些图片中的施工安全隐患。"
            )
        append_message(
            st.session_state,
            "user",
            prompt,
            metadata={"attachments": attachment_names},
        )
        payload = {
            "message": prompt,
            "session_id": st.session_state.get("active_session_id"),
            "action": "inspect" if attachment_paths else None,
            # The current Agent contract intentionally uses image_paths for all
            # visual attachments; Planner routes a single video by extension.
            "image_paths": attachment_paths,
        }
        _run_chat_request(client, payload)
