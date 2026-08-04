from __future__ import annotations

import hashlib
import uuid
from datetime import date, timedelta
from typing import Any

import gradio as gr

from .api import ServiceProtocol
from .auth import IdentityError
from .contracts import ChatRequest, ConfirmRequest
from .domain import DomainError
from .model_client import ModelClientError


_DEMO_CHECK_IN = date.today() + timedelta(days=30)
_DEMO_CHECK_OUT = _DEMO_CHECK_IN + timedelta(days=2)
PRIMARY_DEMO_PROMPT = (
    f"我计划从 {_DEMO_CHECK_IN.isoformat()} 入住到 {_DEMO_CHECK_OUT.isoformat()} 退房，"
    "23:30 到店，带一名六岁儿童，有严重花生过敏，"
    "需要安静房和机场接送。请引用酒店政策，查询可用房和准确报价，"
    "并在我确认前只预览保留房间。"
)


def _safe_error(exc: Exception) -> str:
    if isinstance(exc, IdentityError):
        return f"Identity refused: {exc}"
    if isinstance(exc, DomainError):
        return f"Request refused: {exc}"
    if isinstance(exc, ModelClientError):
        return "The local model is unavailable. Check the private model service."
    if isinstance(exc, ValueError):
        return f"Request validation failed: {exc}"
    reference = uuid.uuid4().hex[:10]
    return f"Request failed safely. Local diagnostic reference: {reference}"


def _audit_json(events: list[Any]) -> list[dict[str, Any]]:
    return [
        event.model_dump(mode="json") if hasattr(event, "model_dump") else dict(event)
        for event in events
    ]


def _pending_display(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {key: value for key, value in item.items() if key != "token"}
        for item in items
    ]


def _new_session_id() -> str:
    return f"judge-{uuid.uuid4().hex}"


def _chat_request_id(
    session_id: str,
    message: str,
    history: list[dict[str, str]],
) -> str:
    """Keep browser retries stable while allowing a later repeated prompt."""
    basis = f"{session_id}\x00{len(history)}\x00{message}".encode("utf-8")
    return f"ui-{hashlib.sha256(basis).hexdigest()[:32]}"


def _confirmation_chat_text(receipt: Any) -> str:
    data = receipt.data if isinstance(receipt.data, dict) else {}
    booking = data.get("booking")
    if isinstance(booking, dict) and booking.get("booking_id"):
        return (
            f"已确认执行。订单 {booking['booking_id']}，"
            f"当前状态：{booking.get('status', 'unknown')}。"
        )
    if data.get("ticket_id"):
        return f"已确认执行。服务工单 {data['ticket_id']} 已创建。"
    return f"已确认执行：{receipt.summary}"


def _confirmation_is_permanently_invalid(exc: Exception) -> bool:
    normalized_error = str(exc).casefold()
    return any(
        marker in normalized_error
        for marker in (
            "confirmation token has expired",
            "unknown confirmation token",
            "confirmation expiry is invalid",
            "request a fresh preview",
        )
    )


def _remaining_confirmations_after_error(
    pending_values: list[dict[str, Any]],
    token: str,
    exc: Exception,
) -> list[dict[str, Any]]:
    remaining = list(pending_values)
    if _confirmation_is_permanently_invalid(exc):
        return [item for item in remaining if item.get("token") != token]
    if len(remaining) > 1 and remaining[0].get("token") == token:
        return remaining[1:] + remaining[:1]
    return remaining


def build_ui(service: ServiceProtocol, identity_tokens: dict[str, str]) -> gr.Blocks:
    labels = list(identity_tokens)
    with gr.Blocks(title="RadeonStay") as demo:
        gr.Markdown(
            """
            # RadeonStay
            **Private, auditable hotel guest journeys on AMD Radeon + ROCm**

            Every policy claim is cited. Hotel facts come from typed local tools.
            Consequential writes require an expiring confirmation token.
            """
        )
        with gr.Row():
            identity = gr.Dropdown(
                choices=labels,
                value=labels[0] if labels else None,
                label="Signed demo identity",
            )
            session_id = gr.Textbox(
                value="",
                label="Session",
                interactive=False,
            )
            new_session = gr.Button("New session")
            health = gr.JSON(
                value={
                    "ok": None,
                    "status": "not_checked",
                    "instruction": "Use Refresh health after the local model is ready.",
                },
                label="Local service boundary",
            )
            refresh_health = gr.Button("Refresh health")

        chatbot = gr.Chatbot(label="Guest journey", type="messages", height=390)
        message = gr.Textbox(
            value=PRIMARY_DEMO_PROMPT,
            label="Request",
            lines=3,
        )
        with gr.Row():
            send = gr.Button("Plan and execute safe reads", variant="primary")
            clear = gr.ClearButton([chatbot, message])

        with gr.Tabs():
            with gr.Tab("Plan"):
                plan = gr.JSON(label="Schema-validated plan")
            with gr.Tab("Citations"):
                citations = gr.JSON(label="Local policy evidence")
            with gr.Tab("Tool receipts"):
                receipts = gr.JSON(label="Deterministic tool results")
            with gr.Tab("Pending writes"):
                pending = gr.JSON(label="Preview before confirmation")
            with gr.Tab("Audit"):
                audit = gr.JSON(label="Privacy-minimized events")

        confirmation_token = gr.Textbox(
            label="Pending confirmation token (queued securely; confirm in order)",
            type="password",
            interactive=False,
        )
        pending_state = gr.State([])
        confirm = gr.Button("Confirm exactly this pending action", variant="stop")
        confirmation_result = gr.JSON(label="Confirmation receipt")

        def cleared_ui_state(session: str) -> tuple[Any, ...]:
            return session, [], {}, [], [], [], [], "", [], {}

        def on_new_session() -> tuple[Any, ...]:
            return cleared_ui_state(_new_session_id())

        def on_identity_change(session: str) -> tuple[Any, ...]:
            # Preserve the bound session so the next request visibly exercises
            # server-side identity isolation, but remove all prior identity data.
            return cleared_ui_state(session or _new_session_id())

        def on_chat(
            text: str,
            history: list[dict[str, str]] | None,
            session: str,
            identity_label: str,
            existing_pending: list[dict[str, Any]] | None,
        ) -> tuple[Any, ...]:
            history = list(history or [])
            pending_values = list(existing_pending or [])
            try:
                token = identity_tokens[identity_label]
                response = service.chat(
                    ChatRequest(
                        session_id=session,
                        request_id=_chat_request_id(session, text, history),
                        identity_token=token,
                        message=text,
                    )
                )
                history.extend(
                    [
                        {"role": "user", "content": text},
                        {"role": "assistant", "content": response.answer},
                    ]
                )
                new_pending = [
                    item.model_dump(mode="json") for item in response.pending_actions
                ]
                known_tokens = {item.get("token") for item in pending_values}
                pending_values.extend(
                    item for item in new_pending if item.get("token") not in known_tokens
                )
                token_value = pending_values[0]["token"] if pending_values else ""
                events = _audit_json(service.audit_events(session, token))
                return (
                    history,
                    response.plan.model_dump(mode="json"),
                    [item.model_dump(mode="json") for item in response.citations],
                    [item.model_dump(mode="json") for item in response.receipts],
                    _pending_display(pending_values),
                    events,
                    token_value,
                    pending_values,
                )
            except Exception as exc:  # Gradio displays a bounded error without internals.
                history.extend(
                    [
                        {"role": "user", "content": text},
                        {"role": "assistant", "content": _safe_error(exc)},
                    ]
                )
                try:
                    token = identity_tokens[identity_label]
                    events = _audit_json(service.audit_events(session, token))
                except Exception:
                    events = []
                next_token = pending_values[0]["token"] if pending_values else ""
                return (
                    history,
                    {},
                    [],
                    [],
                    _pending_display(pending_values),
                    events,
                    next_token,
                    pending_values,
                )

        def on_confirm(
            token: str,
            session: str,
            identity_label: str,
            pending_values: list[dict[str, Any]] | None,
            history: list[dict[str, str]] | None,
        ) -> tuple[Any, ...]:
            remaining = list(pending_values or [])
            updated_history = list(history or [])
            try:
                identity_token = identity_tokens[identity_label]
                receipt = service.confirm(
                    ConfirmRequest(
                        session_id=session,
                        identity_token=identity_token,
                        confirmation_token=token,
                    )
                )
                remaining = [item for item in remaining if item.get("token") != token]
                next_token = remaining[0]["token"] if remaining else ""
                events = _audit_json(service.audit_events(session, identity_token))
                updated_history.append(
                    {"role": "assistant", "content": _confirmation_chat_text(receipt)}
                )
                return (
                    receipt.model_dump(mode="json"),
                    events,
                    next_token,
                    _pending_display(remaining),
                    remaining,
                    updated_history,
                )
            except Exception as exc:
                safe_message = _safe_error(exc)
                remaining = _remaining_confirmations_after_error(remaining, token, exc)
                try:
                    identity_token = identity_tokens[identity_label]
                    events = _audit_json(service.audit_events(session, identity_token))
                except Exception:
                    events = []
                updated_history.append(
                    {"role": "assistant", "content": safe_message}
                )
                return (
                    {"status": "denied", "error": safe_message},
                    events,
                    remaining[0]["token"] if remaining else "",
                    _pending_display(remaining),
                    remaining,
                    updated_history,
                )

        send.click(
            fn=on_chat,
            inputs=[message, chatbot, session_id, identity, pending_state],
            outputs=[
                chatbot,
                plan,
                citations,
                receipts,
                pending,
                audit,
                confirmation_token,
                pending_state,
            ],
        )
        message.submit(
            fn=on_chat,
            inputs=[message, chatbot, session_id, identity, pending_state],
            outputs=[
                chatbot,
                plan,
                citations,
                receipts,
                pending,
                audit,
                confirmation_token,
                pending_state,
            ],
        )
        confirm.click(
            fn=on_confirm,
            inputs=[
                confirmation_token,
                session_id,
                identity,
                pending_state,
                chatbot,
            ],
            outputs=[
                confirmation_result,
                audit,
                confirmation_token,
                pending,
                pending_state,
                chatbot,
            ],
        )
        refresh_health.click(fn=service.health, outputs=[health])
        new_session.click(
            fn=on_new_session,
            outputs=[
                session_id,
                chatbot,
                plan,
                citations,
                receipts,
                pending,
                audit,
                confirmation_token,
                pending_state,
                confirmation_result,
            ],
        )
        identity.change(
            fn=on_identity_change,
            inputs=[session_id],
            outputs=[
                session_id,
                chatbot,
                plan,
                citations,
                receipts,
                pending,
                audit,
                confirmation_token,
                pending_state,
                confirmation_result,
            ],
        )
        demo.load(
            fn=_new_session_id,
            outputs=[session_id],
        )

    return demo
