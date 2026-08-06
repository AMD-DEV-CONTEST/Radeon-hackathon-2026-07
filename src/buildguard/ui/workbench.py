"""Specialist Streamlit workbench pages backed by the local API."""

from __future__ import annotations

from typing import Any

import streamlit as st

from buildguard.ui.api_client import LocalApiClient


def _show_error(exc: Exception) -> None:
    st.error(f"本地 API 请求失败：{exc}")


def agent_page(client: LocalApiClient) -> None:
    st.header("Agent 对话")
    session_id = st.text_input("Session ID（留空自动创建）", key="agent_session")
    message = st.text_area("指令", "分析所选施工图片")
    action_label = st.selectbox(
        "任务动作",
        ["自动规划", "history", "inspect", "high_risk", "report"],
    )
    action = None if action_label == "自动规划" else action_label
    paths = st.text_area("本地图片路径（每行一个）")
    if st.button("发送", type="primary"):
        try:
            result = client.post(
                "/agent/chat",
                {
                    "message": message,
                    "session_id": session_id or None,
                    "action": action,
                    "image_paths": [line.strip() for line in paths.splitlines() if line.strip()],
                },
            )
            st.session_state["last_agent_result"] = result
            if result.get("plan"):
                st.subheader("当前计划")
                st.json(result["plan"])
            if result.get("tool_results"):
                st.subheader("工具执行状态")
                st.dataframe(result["tool_results"], use_container_width=True)
            st.subheader("任务结果")
            st.json(result)
        except Exception as exc:
            _show_error(exc)
    pending = st.session_state.get("last_agent_result", {})
    if pending.get("status") == "WAIT_FOR_CONFIRMATION":
        col1, col2 = st.columns(2)
        if col1.button("确认执行"):
            st.json(
                client.post(
                    "/agent/confirm",
                    {"task_id": pending["task_id"], "approved": True},
                )
            )
        if col2.button("拒绝执行"):
            st.json(
                client.post(
                    "/agent/confirm",
                    {"task_id": pending["task_id"], "approved": False},
                )
            )


def cameras_page(client: LocalApiClient) -> None:
    st.header("实时监控")
    with st.expander("注册摄像头"):
        camera_id_new = st.text_input("Camera ID")
        source_type = st.selectbox("来源类型", ["local", "usb", "rtsp"])
        location = st.text_input("视频路径 / USB 序号 / RTSP URL")
        if st.button("确认注册") and camera_id_new and location:
            camera: dict[str, Any] = {
                "camera_id": camera_id_new,
                "source_type": source_type,
                "enabled": True,
            }
            camera[{"local": "file_path", "usb": "usb_index", "rtsp": "rtsp_url"}[source_type]] = (
                int(location) if source_type == "usb" else location
            )
            try:
                st.json(
                    client.post(
                        "/cameras",
                        {"camera": camera, "policy": None},
                        params={"confirmed": True},
                    )
                )
            except Exception as exc:
                _show_error(exc)
    try:
        payload = client.get("/cameras")
        st.json(payload)
        camera_ids = [item["camera_id"] for item in payload.get("cameras", [])]
        if camera_ids:
            camera_id = st.selectbox("摄像头", camera_ids)
            col1, col2 = st.columns(2)
            if col1.button("确认启动"):
                st.json(
                    client.post(
                        f"/cameras/{camera_id}/start",
                        params={"confirmed": True},
                    )
                )
            if col2.button("确认停止"):
                st.json(
                    client.post(
                        f"/cameras/{camera_id}/stop",
                        params={"confirmed": True},
                    )
                )
            with st.expander("摄像头自适应采样策略"):
                static_fps = st.number_input(
                    "静态 FPS", 0.1, 120.0, 1.0, key=f"static-{camera_id}"
                )
                low_motion_fps = st.number_input(
                    "低运动 FPS", 0.1, 120.0, 3.0, key=f"low-{camera_id}"
                )
                active_fps = st.number_input(
                    "活动 FPS", 0.1, 120.0, 5.0, key=f"active-{camera_id}"
                )
                suspected_fps = st.number_input(
                    "疑似风险 FPS", 0.1, 10.0, 8.0, key=f"suspected-{camera_id}"
                )
                static_threshold = st.number_input(
                    "静态运动阈值", 0.0, 255.0, 2.0, key=f"static-th-{camera_id}"
                )
                active_threshold = st.number_input(
                    "活动运动阈值", 0.1, 255.0, 12.0, key=f"active-th-{camera_id}"
                )
                hysteresis = st.number_input(
                    "迟滞帧数", 1, 100, 3, key=f"hysteresis-{camera_id}"
                )
                if st.button("确认更新采样策略", key=f"policy-{camera_id}"):
                    st.json(
                        client.put(
                            f"/cameras/{camera_id}/policy",
                            {
                                "static_fps": static_fps,
                                "low_motion_fps": low_motion_fps,
                                "active_fps": active_fps,
                                "suspected_fps": suspected_fps,
                                "static_motion_threshold": static_threshold,
                                "active_motion_threshold": active_threshold,
                                "hysteresis_frames": hysteresis,
                            },
                            params={"confirmed": True},
                        )
                    )
            st.image(
                f"{client.base_url}/cameras/{camera_id}/stream.mjpg",
                caption=f"Live: {camera_id}",
            )
            if st.button("确认移除摄像头"):
                st.json(
                    client.delete(
                        f"/cameras/{camera_id}",
                        params={"confirmed": True},
                    )
                )
    except Exception as exc:
        _show_error(exc)


def events_page(client: LocalApiClient) -> None:
    st.header("风险事件")
    try:
        payload = client.get("/events")
        events = payload.get("events", [])
        if not events:
            st.info("当前没有风险事件。")
            return
        st.dataframe(events, use_container_width=True)
        event_id = st.selectbox(
            "选择事件",
            [item["id"] for item in events],
        )
        selected = next(item for item in events if item["id"] == event_id)
        event_status = str(selected.get("status") or "")
        col1, col2 = st.columns(2)
        can_acknowledge = event_status in {"pending", "active"}
        can_close = event_status in {"pending", "active", "acknowledged"}
        if col1.button("确认已处理", disabled=not can_acknowledge):
            st.json(
                client.post(
                    f"/events/{event_id}/acknowledge",
                    params={"confirmed": True},
                )
            )
        if col2.button("确认关闭事件", disabled=not can_close):
            st.json(
                client.post(
                    f"/events/{event_id}/close",
                    params={"confirmed": True},
                )
            )
        if event_status == "acknowledged":
            st.success("该事件已确认处理，可继续关闭事件或记录整改结果。")
        elif event_status in {"resolved", "dismissed"}:
            st.info("该事件已经结束，无需再次确认或关闭。")
        for key in ("max_confidence_frame_path", "start_frame_path", "end_frame_path"):
            if selected.get(key):
                st.image(selected[key], caption=key)
        if selected.get("clip_path"):
            clip_data, _ = client.get_bytes(f"/events/{event_id}/clip")
            st.video(clip_data, format="video/webm")
        st.subheader("整改闭环")
        action = st.text_input("整改措施")
        actor = st.text_input("处置人")
        status = st.selectbox(
            "整改状态",
            ["planned", "in_progress", "completed", "verified", "rejected"],
        )
        if st.button("记录整改") and action and actor:
            st.json(
                client.post(
                    f"/events/{event_id}/remediations",
                    {"action": action, "status": status, "actor": actor},
                )
            )
        st.dataframe(
            client.get(f"/events/{event_id}/remediations"),
            use_container_width=True,
        )
    except Exception as exc:
        _show_error(exc)


def knowledge_page(client: LocalApiClient) -> None:
    st.header("知识库")
    try:
        st.json(client.get("/rag/status"))
        st.dataframe(client.get("/rag/documents"), use_container_width=True)
    except Exception as exc:
        _show_error(exc)
    documents = st.file_uploader(
        "上传 PDF/DOCX/Markdown/TXT",
        type=["pdf", "docx", "md", "txt"],
        accept_multiple_files=True,
    )
    source_path = st.text_input("导入本地规范文件或目录（必须位于知识库白名单）")
    project = st.text_input("项目过滤标签（可选）")
    if documents and st.button("上传并增量索引"):
        try:
            st.json(client.upload_documents(documents, project or None))
        except Exception as exc:
            _show_error(exc)
    if st.button("导入并增量更新索引") and source_path:
        try:
            st.json(
                client.post(
                    "/rag/ingest",
                    {"source_path": source_path, "project": project or None},
                )
            )
        except Exception as exc:
            _show_error(exc)
    query = st.text_input("检索施工规范")
    if st.button("检索") and query:
        try:
            st.json(client.post("/rag/advanced-search", {"query": query, "top_k": 5}))
        except Exception as exc:
            _show_error(exc)
    if st.button("重建并验证索引"):
        try:
            st.json(client.post("/rag/rebuild"))
        except Exception as exc:
            _show_error(exc)
    try:
        preview = client.get("/rag/chunks", params={"limit": 20})
        st.subheader("分块预览")
        st.dataframe(preview.get("chunks", []), use_container_width=True)
    except Exception as exc:
        _show_error(exc)


def history_page(client: LocalApiClient) -> None:
    st.header("历史任务")
    risk = st.selectbox("风险过滤", ["全部", "low", "normal", "high", "critical"])
    params: dict[str, Any] = {} if risk == "全部" else {"risk": risk}
    try:
        sessions = client.get("/sessions")
        st.subheader("会话与可追溯事实")
        st.dataframe(sessions, use_container_width=True)
        if sessions:
            session_id = st.selectbox("会话", [item["id"] for item in sessions])
            st.dataframe(
                client.get(f"/sessions/{session_id}/messages"),
                use_container_width=True,
            )
            facts = client.get(f"/sessions/{session_id}/facts")
            st.dataframe(facts, use_container_width=True)
            if facts:
                fact_id = st.selectbox(
                    "选择要停用的已验证事实",
                    [item["id"] for item in facts],
                )
                if st.button("确认停用该事实"):
                    st.json(
                        client.delete(
                            f"/sessions/{session_id}/facts/{fact_id}",
                            params={"confirmed": True},
                        )
                    )
            if st.button("确认清空该会话"):
                st.json(
                    client.delete(
                        f"/sessions/{session_id}",
                        params={"confirmed": True},
                    )
                )
        st.dataframe(client.get("/tasks", params=params), use_container_width=True)
        st.subheader("报告")
        st.dataframe(client.get("/reports"), use_container_width=True)
    except Exception as exc:
        _show_error(exc)


def audit_page(client: LocalApiClient) -> None:
    st.header("权限审计")
    try:
        outcome = st.selectbox("结果", ["全部", "success", "failure", "denied"])
        params = {} if outcome == "全部" else {"outcome": outcome}
        st.dataframe(client.get("/audit", params=params), use_container_width=True)
        st.subheader("Agent 工具调用")
        st.dataframe(client.get("/tool-calls"), use_container_width=True)
    except Exception as exc:
        _show_error(exc)


def performance_page(client: LocalApiClient) -> None:
    st.header("GPU 性能大屏")
    st.caption("全部曲线和表格来自本地硬件、CameraManager、LLM 和 SQLite 日志。")
    try:
        data = client.get("/runtime/metrics")
        st.metric("进程 RSS (MiB)", round(data["process"]["rss_bytes"] / 1024 / 1024, 2))
        samples = data.get("samples", [])
        if samples:
            import pandas as pd  # type: ignore[import-untyped]

            latest = samples[-1]
            metric_columns = st.columns(6)
            metric_columns[0].metric(
                "当前驻留模型", len(latest.get("current_models", []))
            )
            metric_columns[1].metric("TTFT (s)", latest.get("ttft_seconds"))
            metric_columns[2].metric("生成速度 (tok/s)", latest.get("tokens_per_second"))
            metric_columns[3].metric("RAG (ms)", latest.get("rag_latency_ms"))
            metric_columns[4].metric("视觉 (ms)", latest.get("vision_latency_ms"))
            metric_columns[5].metric("端到端 (ms)", latest.get("end_to_end_ms"))
            if latest.get("current_models"):
                st.caption("驻留模型：" + "、".join(latest["current_models"]))
            timing_columns = st.columns(4)
            timing_columns[0].metric(
                "重排 (ms)", latest.get("reranker_latency_ms")
            )
            timing_columns[1].metric(
                "事件确认 (ms)", latest.get("event_confirmation_latency_ms")
            )
            timing_columns[2].metric(
                "报告生成 (ms)", latest.get("report_generation_latency_ms")
            )
            timing_columns[3].metric(
                "LLM 总耗时 (s)", latest.get("llm_total_seconds")
            )

            gpu_rows: list[dict[str, Any]] = []
            fps_rows: list[dict[str, Any]] = []
            for sample in samples:
                gpus = sample.get("hardware", {}).get("gpus", [])
                if gpus:
                    gpu = gpus[0]
                    observed = {
                        "GPU利用率": gpu.get("utilization_percent"),
                        "VRAM使用MiB": gpu.get("memory_used_mb"),
                        "温度C": gpu.get("temperature_celsius"),
                        "功耗W": gpu.get("power_watts"),
                    }
                    if any(value is not None for value in observed.values()):
                        gpu_rows.append(
                            {
                                "timestamp": sample["timestamp"],
                                "GPU名称": gpu.get("name") or "未知 GPU",
                                **observed,
                            }
                        )
                for camera_id, fps in sample.get("video_fps", {}).items():
                    fps_rows.append(
                        {
                            "timestamp": sample["timestamp"],
                            "camera_id": camera_id,
                            "fps": fps,
                        }
                    )
            if gpu_rows:
                gpu_frame = pd.DataFrame(gpu_rows)
                st.subheader("GPU / VRAM 曲线")
                st.caption(
                    "GPU 利用率和 VRAM 使用量采用独立纵轴，避免 MiB 数值掩盖利用率波动。"
                )
                gpu_column, vram_column = st.columns(2)
                with gpu_column:
                    st.line_chart(gpu_frame, x="timestamp", y="GPU利用率")
                with vram_column:
                    st.line_chart(gpu_frame, x="timestamp", y="VRAM使用MiB")
                st.dataframe(
                    gpu_frame.fillna("采集器未提供"),
                    use_container_width=True,
                )
            else:
                hardware = latest.get("hardware", {})
                source = hardware.get("source", "未知采集器")
                reason = hardware.get("error") or "采集器未返回有效 GPU 指标"
                st.info(f"当前没有可绘制的 GPU 数据（{source}：{reason}），未生成虚假曲线。")
            if fps_rows:
                st.subheader("每路视频 FPS")
                st.line_chart(
                    pd.DataFrame(fps_rows),
                    x="timestamp",
                    y="fps",
                    color="camera_id",
                )

        st.subheader("多摄像头状态与队列")
        cameras = data.get("cameras", [])
        if cameras:
            st.dataframe(cameras, use_container_width=True)
        else:
            st.info("当前没有已注册摄像头。")

        operations = data.get("operations", [])
        if operations:
            import pandas as pd

            frame = pd.DataFrame(operations)
            st.subheader("工具时间轴")
            st.line_chart(frame, x="created_at", y="duration_ms")
            st.dataframe(frame, use_container_width=True)
            st.subheader("任务瀑布图")
            st.bar_chart(frame, x="operation", y="duration_ms")

        st.subheader("RGC 调用数对比")
        rgc = data.get("rgc_comparison", [])
        if rgc:
            st.dataframe(rgc, use_container_width=True)
        else:
            st.info("当前日志中没有 RGC 前后调用计数。")

        st.subheader("量化前后对比")
        quantization = data.get("quantization_comparison", [])
        if quantization:
            st.dataframe(quantization, use_container_width=True)
        else:
            st.info("当前日志中没有量化对比记录。")

        st.subheader("导出真实观测数据")
        columns = st.columns(3)
        for column, export_format, label, mime in (
            (columns[0], "csv", "下载 CSV", "text/csv"),
            (columns[1], "json", "下载 JSON", "application/json"),
            (
                columns[2],
                "chart",
                "下载图表截图数据",
                "application/json",
            ),
        ):
            content, filename = client.get_bytes(
                "/runtime/export",
                params={"format": export_format},
            )
            column.download_button(
                label,
                data=content,
                file_name=filename,
                mime=mime,
            )
    except Exception as exc:
        _show_error(exc)


WORKBENCH_PAGES = {
    "📹 实时监控": cameras_page,
    "⚠️ 风险事件": events_page,
    "📚 知识库": knowledge_page,
    "🕘 历史任务": history_page,
    "🔐 权限审计": audit_page,
    "📊 性能概览": performance_page,
}
