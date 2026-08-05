import os
import re
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

import requests

import db
import generator
import sender


PLAN_DAILY_LIMITS = {
    "free": 5,
    "basic": 20,
    "standard": 50,
    "premium": 50,
}


def _daily_limit(plan_tier: str) -> int:
    return PLAN_DAILY_LIMITS.get((plan_tier or "free").lower(), 5)


def _plan_name(plan_tier: str) -> str:
    return (plan_tier or "free").strip().upper()


def _status_counts_text(counts: Dict[str, Any]) -> str:
    if not counts:
        return "No contacts loaded yet."
    ordered = ["pending", "drafted", "approved", "sent", "failed", "locked"]
    parts = []
    for key in ordered:
        if key in counts:
            parts.append(f"{key}: {counts[key]}")
    for key, value in counts.items():
        if key not in ordered:
            parts.append(f"{key}: {value}")
    return ", ".join(parts)


def _format_contact(contact: Dict[str, Any]) -> str:
    name = contact.get("name") or "Recruiter"
    company = contact.get("company") or "Unknown company"
    email = contact.get("email") or "no email"
    status = contact.get("status") or "unknown"
    return f"{name} at {company} <{email}> [{status}]"


def _format_contact_line(contact: Dict[str, Any], index: int) -> str:
    name = contact.get("name") or "Recruiter"
    company = contact.get("company") or "Unknown company"
    title = contact.get("title") or "Recruiter"
    email = contact.get("email") or "no email"
    status = contact.get("status") or "unknown"
    return f"{index}. {name} - {title}, {company}\n   Email: {email}\n   Status: {status}"


def send_telegram_message(chat_id: str, text: str) -> bool:
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if not token:
        print(f"[TELEGRAM BOT] TELEGRAM_BOT_TOKEN missing. Would send to {chat_id}: {text}")
        return False

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text[:3900],
        "disable_web_page_preview": True,
    }
    try:
        response = requests.post(url, json=payload, timeout=15)
        response.raise_for_status()
        return True
    except Exception as exc:
        print(f"[TELEGRAM BOT] Failed to send message: {exc}")
        return False


def extract_message(update: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    message = update.get("message") or update.get("edited_message")
    if not message:
        return None

    from_user = message.get("from") or {}
    chat = message.get("chat") or {}
    text = (message.get("text") or "").strip()
    if not text:
        return None

    return {
        "text": text,
        "chat_id": str(chat.get("id")),
        "telegram_user_id": str(from_user.get("id")),
        "telegram_username": from_user.get("username") or "",
        "telegram_first_name": from_user.get("first_name") or "",
    }


def create_link_code(user_id: int) -> Dict[str, Any]:
    return db.create_telegram_link_token(user_id)


def retrieve_outreach_context(user_id: int, include_next: int = 5) -> str:
    user = db.get_user_profile(user_id) or {}
    billing = db.get_billing_info(user_id)
    stats = db.get_stats(user_id=user_id)
    plan = billing.get("plan_tier", "free")
    daily_limit = _daily_limit(plan)
    sent_today = int(billing.get("emails_sent_today") or 0)
    remaining = max(0, daily_limit - sent_today)

    approved = db.get_contacts_by_status("approved", user_id=user_id, limit=include_next)
    pending = db.get_contacts_by_status("pending", user_id=user_id, limit=include_next)
    next_contacts = (approved + pending)[:include_next]

    lines = [
        "PitchDock Outreach Status",
        "",
        "Account",
        f"- Email: {user.get('email', 'unknown')}",
        f"- Candidate: {user.get('full_name') or 'Not set'}",
        f"- Target role: {user.get('target_role') or 'Not set'}",
        f"- Plan: {_plan_name(plan)}",
        "",
        "Daily Quota",
        f"- Used today: {sent_today}/{daily_limit}",
        f"- Remaining today: {remaining}",
        "",
        "Recruiter Pipeline",
        f"- Status: {_status_counts_text(stats.get('status_breakdown', {}))}",
    ]

    if next_contacts:
        lines.extend(["", "Next Sendable Recruiters"])
        for index, contact in enumerate(next_contacts, 1):
            lines.append(_format_contact_line(contact, index))
    else:
        lines.extend(["", "Next Sendable Recruiters", "No pending or approved recruiters are available right now."])

    lines.extend(["", "Available Commands", "- send email", "- send 3 emails", "- status"])

    return "\n".join(lines)


def _get_send_candidates(user_id: int, limit: int) -> List[Dict[str, Any]]:
    approved = db.get_contacts_by_status("approved", user_id=user_id, limit=limit)
    if len(approved) >= limit:
        return approved[:limit]

    pending = db.get_contacts_by_status("pending", user_id=user_id, limit=limit - len(approved))
    return approved + pending


def send_next_email_batch(user_id: int, requested_limit: Optional[int] = None) -> str:
    billing = db.get_billing_info(user_id)
    plan = billing.get("plan_tier", "free")
    daily_limit = _daily_limit(plan)
    sent_today = int(billing.get("emails_sent_today") or 0)
    remaining = max(0, daily_limit - sent_today)

    if remaining <= 0:
        return (
            "PitchDock Send Limit Reached\n\n"
            f"Plan: {_plan_name(plan)}\n"
            f"Used today: {sent_today}/{daily_limit}\n"
            "Remaining today: 0\n\n"
            "Your daily email quota is complete. Try again tomorrow; the next run will continue from the next unsent recruiter."
        )

    batch_limit = remaining
    if requested_limit and requested_limit > 0:
        batch_limit = min(batch_limit, requested_limit)

    contacts = _get_send_candidates(user_id, batch_limit)
    if not contacts:
        return (
            "PitchDock Send Run\n\n"
            "No approved or pending recruiters are available to send right now.\n\n"
            "Next step: add contacts or generate drafts from the PitchDock dashboard."
        )

    profile = db.get_user_profile(user_id) or generator.load_candidate_profile()
    resume_path = profile.get("resume_pdf_path")
    attachment_path = resume_path if resume_path and os.path.exists(resume_path) else None

    gemini_client = None
    sent_rows = []
    failed_rows = []

    for contact in contacts:
        try:
            subject = contact.get("personalized_subject")
            body = contact.get("personalized_body")

            if contact.get("status") == "pending" or not subject or not body:
                if gemini_client is None:
                    gemini_client = generator.get_gemini_client(profile.get("gemini_api_key") or None)
                subject, body = generator.generate_email_draft(contact, profile, gemini_client)
                db.update_contact_draft(contact["id"], subject, body, status="approved", user_id=user_id)

            success, err = sender.send_single_email(
                to_email=contact["email"],
                subject=subject,
                body=body,
                user_id=user_id,
                attachment_path=attachment_path,
            )

            if success:
                sent_at = datetime.now().isoformat()
                db.update_contact_status(contact["id"], "sent", sent_at=sent_at, user_id=user_id)
                db.increment_emails_sent(1, user_id=user_id)
                sent_rows.append(contact)
            else:
                db.update_contact_status(contact["id"], "failed", error_message=err, user_id=user_id)
                failed_rows.append((contact, err or "Unknown sending error"))
        except Exception as exc:
            db.update_contact_status(contact["id"], "failed", error_message=str(exc), user_id=user_id)
            failed_rows.append((contact, str(exc)))

    updated_billing = db.get_billing_info(user_id)
    updated_sent_today = int(updated_billing.get("emails_sent_today") or 0)
    updated_remaining = max(0, daily_limit - updated_sent_today)

    summary = [
        "PitchDock Send Run Complete",
        "",
        "Summary",
        f"- Plan: {_plan_name(plan)}",
        f"- Requested: {batch_limit}",
        f"- Sent: {len(sent_rows)}",
        f"- Failed: {len(failed_rows)}",
        f"- Daily quota: {updated_sent_today}/{daily_limit} used",
        f"- Remaining today: {updated_remaining}",
    ]
    if sent_rows:
        summary.extend(["", "Recipients Sent"])
        for index, contact in enumerate(sent_rows, 1):
            summary.append(_format_contact_line(contact, index))
    if failed_rows:
        summary.extend(["", "Failures"])
        for index, (contact, error) in enumerate(failed_rows[:5], 1):
            summary.append(f"{index}. {_format_contact(contact)}\n   Reason: {error}")
    summary.extend([
        "",
        "Queue Note",
        "Future runs continue from recruiters whose status is still pending or approved.",
    ])
    return "\n".join(summary)


def _parse_requested_limit(text: str) -> Optional[int]:
    match = re.search(r"\b(\d{1,3})\b", text)
    if not match:
        return None
    return max(1, int(match.group(1)))


def _help_text() -> str:
    bot_name = os.environ.get("TELEGRAM_BOT_USERNAME", "your PitchDock bot")
    return (
        "Welcome to PitchDock Agent\n\n"
        "Control recruiter outreach directly from Telegram.\n\n"
        "Link Your Account\n"
        "1. Log in to PitchDock on the website.\n"
        "2. Open Connection Settings.\n"
        "3. Generate a Telegram link code.\n"
        f"4. Send /link CODE here in {bot_name}.\n\n"
        "Available Commands\n"
        "- status: view plan, quota, and next recruiters\n"
        "- send email: send the next quota-safe batch\n"
        "- send 3 emails: send up to 3 emails, subject to plan quota\n"
        "- /unlink: disconnect this Telegram account"
    )


def _run_langchain_agent(user_id: int, text: str) -> str:
    try:
        from langchain.agents import create_agent
        from langchain.tools import tool
        from langchain_google_genai import ChatGoogleGenerativeAI
    except Exception:
        return (
            "I can handle status and send commands now. LangChain packages are not installed yet on this server, "
            "so natural-language planning is using the deterministic fallback."
        )

    profile = db.get_user_profile(user_id) or {}
    api_key = profile.get("gemini_api_key") or os.environ.get("GEMINI_API_KEY")
    if not api_key:
        return (
            "PitchDock Agent Setup Required\n\n"
            "Gemini API key is not configured for this account.\n\n"
            "Next step: open PitchDock Connection Settings and add your Gemini API key."
        )

    @tool
    def retrieve_account_context() -> str:
        """Retrieve the user's PitchDock billing, profile, quota, and recruiter queue context."""
        return retrieve_outreach_context(user_id)

    @tool
    def send_next_recruiter_emails(count: int = 0) -> str:
        """Send the next recruiter emails while respecting the user's subscription quota."""
        requested = count if count and count > 0 else None
        return send_next_email_batch(user_id, requested)

    model = ChatGoogleGenerativeAI(
        model=os.environ.get("TELEGRAM_AGENT_MODEL", "gemini-2.5-flash"),
        api_key=api_key,
        temperature=0.1,
    )
    agent = create_agent(
        model,
        tools=[retrieve_account_context, send_next_recruiter_emails],
        system_prompt=(
            "You are the PitchDock Telegram outreach agent. Use retrieval before answering account, quota, "
            "or recruiter questions. Only send emails when the user clearly asks to send or launch outreach. "
            "When sending, obey subscription quotas and summarize recipients, companies, sent count, and failures."
        ),
    )
    result = agent.invoke({"messages": [{"role": "user", "content": text}]})
    messages = result.get("messages", [])
    if not messages:
        return "I could not produce a response."
    content = getattr(messages[-1], "content", None)
    return content if isinstance(content, str) else str(content)


def handle_text_message(message: Dict[str, Any]) -> str:
    text = message["text"].strip()
    telegram_user_id = message["telegram_user_id"]

    if text.lower() in {"/start", "start", "/help", "help"}:
        return _help_text()

    if text.lower().startswith("/link"):
        parts = text.split(maxsplit=1)
        if len(parts) != 2:
            return (
                "Link Code Required\n\n"
                "Please send the command in this format:\n"
                "/link CODE\n\n"
                "You can generate the code from PitchDock Connection Settings."
            )
        linked_user, err = db.link_telegram_user(
            parts[1],
            telegram_user_id=telegram_user_id,
            telegram_username=message.get("telegram_username", ""),
            telegram_first_name=message.get("telegram_first_name", ""),
        )
        if err:
            return f"PitchDock Link Failed\n\n{err}"
        return (
            "PitchDock Account Linked\n\n"
            f"Connected account: {linked_user['email']}\n\n"
            "You can now send:\n"
            "- status\n"
            "- send email\n"
            "- send 3 emails"
        )

    if text.lower() == "/unlink":
        count = db.unlink_telegram_user(telegram_user_id)
        return (
            "Telegram Account Unlinked\n\nThis Telegram chat no longer controls a PitchDock account."
            if count
            else "No Linked Account\n\nThis Telegram account was not linked to PitchDock."
        )

    user = db.get_user_by_telegram_id(telegram_user_id)
    if not user:
        return "PitchDock Account Not Linked\n\n" + _help_text()

    lowered = text.lower()
    if lowered in {"status", "stats", "summary", "/status", "/stats"} or "quota" in lowered:
        return retrieve_outreach_context(user["id"])

    if "send" in lowered and ("email" in lowered or "mail" in lowered or "outreach" in lowered):
        return send_next_email_batch(user["id"], _parse_requested_limit(text))

    return _run_langchain_agent(user["id"], text)


def handle_telegram_update(update: Dict[str, Any]) -> Dict[str, Any]:
    message = extract_message(update)
    if not message:
        return {"ok": True, "handled": False}

    response_text = handle_text_message(message)
    send_telegram_message(message["chat_id"], response_text)
    return {"ok": True, "handled": True}
