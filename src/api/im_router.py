"""IM platform webhook router: WeCom / Feishu / DingTalk.

Reference the routing pattern of lesson 25 integrated_agent_service/app/im_router.py,
adapted to the Insurance intelligent Q&A Agent's query() interface.

Features:
- POST /api/im/webhook?platform=wecom|feishu|dingtalk
- Parse each platform's message format and extract the text
- Call InsuranceAgent.query() to process
- Return the response in the platform's format
- HMAC-SHA256 signature verification placeholder
"""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
from typing import Any, Protocol

logger = logging.getLogger(__name__)


class AgentProvider(Protocol):
    """Agent provider protocol (implemented by AgentHolder in server.py)."""

    async def get(self) -> Any: ...


class IMRouter:
    """IM platform webhook router.

    Unified routing of WeCom / Feishu / DingTalk message callbacks to InsuranceAgent.query(),
    returning the response in each platform's required format.
    """

    def __init__(
        self,
        agent_provider: AgentProvider,
        *,
        sign_key: str | None = None,
        max_message_length: int = 500,
    ) -> None:
        self.agent_provider = agent_provider
        self.sign_key = sign_key
        self.max_message_length = max_message_length

    async def dispatch(self, payload: dict[str, Any], *, platform: str = "wecom") -> dict[str, Any]:
        """Route the message by platform and return the platform-format response.

        Args:
            payload: the raw JSON callback payload from the IM platform.
            platform: the platform identifier wecom | feishu | dingtalk.

        Returns:
            The response dict corresponding to the platform.
        """
        handlers = {
            "wecom": self.handle_wecom,
            "feishu": self.handle_feishu,
            "dingtalk": self.handle_dingtalk,
        }
        handler = handlers.get(platform)
        if handler is None:
            raise ValueError(f"unsupported IM platform: {platform}")

        logger.info("[IM] received %s webhook callback", platform)
        return await handler(payload)

    # ── signature verification placeholder ──

    def verify_signature(self, timestamp: str, nonce: str, payload_raw: str, signature: str) -> bool:
        """HMAC-SHA256 signature verification placeholder.

        In production, configure each platform's signature key and implement complete verification logic.
        Currently returns True only for development/demo purposes.
        """
        if not self.sign_key:
            logger.debug("[IM] signature key not configured, skipping verification (dev mode)")
            return True

        message = f"{timestamp}\n{nonce}\n{payload_raw}"
        expected = hmac.new(
            self.sign_key.encode("utf-8"),
            message.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        return hmac.compare_digest(expected, signature)

    # ── common query ──

    async def _query_agent(self, text: str, session_id: str) -> dict[str, Any]:
        """Call InsuranceAgent.query() and return the result."""
        text = text.strip()
        if not text:
            return {
                "answer": "Received an empty message. Please enter your insurance question.",
                "citations": [],
                "sources": [],
                "status": "skipped",
            }
        if len(text) > self.max_message_length:
            text = text[: self.max_message_length]
            logger.warning("[IM] message too long, truncated to %d characters", self.max_message_length)

        agent = await self.agent_provider.get()
        result = await agent.query(text, session_id=session_id)
        return result

    # ── WeCom ──

    async def handle_wecom(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Handle a WeCom application message callback.

        Callback format (after XML-to-dict conversion)::

            {
                "tousername": "corpid",
                "fromusername": "userid",
                "msgtype": "text",
                "content": "What are the exclusions of Ping An Employer Liability Insurance?",
                "msgid": "12345",
                "createtime": "1348831860"
            }
        """
        msg_type = payload.get("msgtype") or payload.get("MsgType", "")
        if msg_type != "text":
            return {
                "status": "skipped",
                "platform": "wecom",
                "answer": "Only text messages are supported for now. Please send a text question.",
            }

        content = payload.get("content") or payload.get("Content", "")
        user_id = payload.get("fromusername") or payload.get("FromUserName", "wecom-anonymous")
        session_id = f"wecom-{user_id}"

        result = await self._query_agent(content, session_id)

        return {
            "status": "ok",
            "platform": "wecom",
            "answer": result.get("answer", ""),
            "citations": result.get("citations", []),
            "sources": result.get("sources", []),
            "agent_status": result.get("status", "unknown"),
            "session_id": session_id,
            "msg_type": "text",
            "touser": user_id,
        }

    # ── Feishu ──

    async def handle_feishu(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Handle a Feishu im.message.receive_v1 event callback.

        Callback format::

            {
                "schema": "2.0",
                "event": {
                    "sender": {"sender_id": {"open_id": "ou_xxx"}},
                    "message": {
                        "message_type": "text",
                        "content": "{\"text\":\"What are the exclusions of Ping An Employer Liability Insurance?\"}"
                    }
                }
            }
        """
        # URL verification challenge (sent when configuring the Feishu webhook)
        if "challenge" in payload:
            return {"challenge": payload["challenge"]}

        event = payload.get("event", {})
        message = event.get("message", {})
        sender = event.get("sender", {})

        msg_type = message.get("message_type", "")
        if msg_type != "text":
            return {
                "status": "skipped",
                "platform": "feishu",
                "answer": "Only text messages are supported for now. Please send a text question.",
            }

        content_raw = message.get("content", "{}")
        try:
            content_obj = json.loads(content_raw) if isinstance(content_raw, str) else content_raw
        except json.JSONDecodeError:
            content_obj = {}
        text = content_obj.get("text", "") if isinstance(content_obj, dict) else ""

        sender_id = sender.get("sender_id", {})
        open_id = sender_id.get("open_id", "feishu-anonymous")
        session_id = f"feishu-{open_id}"

        result = await self._query_agent(text, session_id)

        # Feishu message-card reply format
        return {
            "status": "ok",
            "platform": "feishu",
            "answer": result.get("answer", ""),
            "citations": result.get("citations", []),
            "sources": result.get("sources", []),
            "agent_status": result.get("status", "unknown"),
            "session_id": session_id,
            "msg_type": "text",
            "receive_id": open_id,
        }

    # ── DingTalk ──

    async def handle_dingtalk(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Handle a DingTalk bot callback.

        Callback format::

            {
                "msgtype": "text",
                "text": {"content": "What are the exclusions of Ping An Employer Liability Insurance?"},
                "senderStaffId": "user123",
                "conversationId": "cidxxx",
                "msgId": "msg123"
            }
        """
        msg_type = payload.get("msgtype", "")
        if msg_type != "text":
            return {
                "status": "skipped",
                "platform": "dingtalk",
                "answer": "Only text messages are supported for now. Please send a text question.",
            }

        text_obj = payload.get("text", {})
        content = text_obj.get("content", "") if isinstance(text_obj, dict) else ""
        staff_id = payload.get("senderStaffId", "dingtalk-anonymous")
        session_id = f"dingtalk-{staff_id}"

        result = await self._query_agent(content, session_id)

        # DingTalk bot markdown reply format
        answer_text = result.get("answer", "")
        citations = result.get("citations", [])
        citation_block = ""
        if citations:
            refs = "\n".join(
                f"- [{c.get('ref_id', '?')}] {c.get('quoted_text', '')[:60]}"
                for c in citations
            )
            citation_block = f"\n\n**Citation sources:**\n{refs}"

        return {
            "status": "ok",
            "platform": "dingtalk",
            "answer": answer_text,
            "citations": citations,
            "sources": result.get("sources", []),
            "agent_status": result.get("status", "unknown"),
            "session_id": session_id,
            "msgtype": "markdown",
            "markdown": {
                "title": "Insurance Intelligent Q&A",
                "text": answer_text + citation_block,
            },
        }
