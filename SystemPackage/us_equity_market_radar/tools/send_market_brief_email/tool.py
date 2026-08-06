from __future__ import annotations

from datetime import datetime
from email.message import EmailMessage
from email.utils import formatdate, make_msgid, parseaddr
import smtplib
import ssl
from typing import Any
from zoneinfo import ZoneInfo


def run(arguments: dict, resources: dict) -> dict:
    smtp_config = resources.get("smtp")
    if not isinstance(smtp_config, dict):
        raise ValueError("smtp_account resource is required")
    recipients_value = arguments.get("recipients")
    if recipients_value is None:
        recipients_value = smtp_config.get("default_recipients")
    recipients = _recipients(recipients_value)
    subject = _header(arguments.get("subject"), field="subject", max_length=200)
    body = str(arguments.get("body") or "").strip()
    if not body:
        raise ValueError("body is required")
    if len(body) > 100000:
        raise ValueError("body exceeds 100000 characters")

    host = str(smtp_config.get("host") or "").strip()
    port = int(smtp_config.get("port") or 0)
    username = str(smtp_config.get("username") or "").strip()
    password = str(smtp_config.get("password") or "")
    from_address = _address(smtp_config.get("from_address"), field="from_address")
    security = str(smtp_config.get("security") or "").strip().lower()
    if not host or port < 1 or port > 65535 or not username or not password:
        raise ValueError("smtp_account is incomplete")
    if security not in {"ssl", "starttls"}:
        raise ValueError("smtp_account.security must be ssl or starttls")

    message_id = make_msgid()
    message = EmailMessage()
    message["From"] = from_address
    message["To"] = ", ".join(recipients)
    message["Subject"] = subject
    message["Date"] = formatdate(localtime=True)
    message["Message-ID"] = message_id
    message.set_content(body)

    tls_context = ssl.create_default_context()
    if security == "ssl":
        with smtplib.SMTP_SSL(host, port, context=tls_context, timeout=30) as client:
            client.login(username, password)
            client.send_message(message)
    else:
        with smtplib.SMTP(host, port, timeout=30) as client:
            client.ehlo()
            client.starttls(context=tls_context)
            client.ehlo()
            client.login(username, password)
            client.send_message(message)

    return {
        "status": "sent",
        "sent_at": datetime.now(ZoneInfo("Asia/Shanghai")).isoformat(),
        "recipients": recipients,
        "message_id": message_id,
    }


def _recipients(value: Any) -> list[str]:
    if not isinstance(value, list):
        raise ValueError("recipients must be an array")
    recipients = [_address(item, field="recipient") for item in value]
    unique = list(dict.fromkeys(recipients))
    if not unique or len(unique) > 10:
        raise ValueError("recipients must contain 1 to 10 unique addresses")
    return unique


def _address(value: Any, *, field: str) -> str:
    text = str(value or "").strip()
    if "\r" in text or "\n" in text:
        raise ValueError(f"{field} contains a newline")
    display_name, address = parseaddr(text)
    del display_name
    if not address or "@" not in address or address.startswith("@") or address.endswith("@"):
        raise ValueError(f"{field} is not a valid email address")
    return address


def _header(value: Any, *, field: str, max_length: int) -> str:
    text = str(value or "").strip()
    if not text or len(text) > max_length:
        raise ValueError(f"{field} must contain 1 to {max_length} characters")
    if "\r" in text or "\n" in text:
        raise ValueError(f"{field} contains a newline")
    return text
