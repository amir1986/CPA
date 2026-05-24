"""Minimal SMTP sender.

In tests we set ``CPA_EMAIL_SINK=memory`` so messages collect in an in-process
list instead of being sent. In dev SMTP is MailHog.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from email.message import EmailMessage

import aiosmtplib

from app.config import get_settings

logger = logging.getLogger(__name__)


@dataclass
class SentMessage:
    to: str
    subject: str
    body: str


_memory_sink: list[SentMessage] = []


def memory_sink() -> list[SentMessage]:
    return _memory_sink


def reset_memory_sink() -> None:
    _memory_sink.clear()


async def send_email(*, to: str, subject: str, body: str) -> None:
    sink = os.environ.get("CPA_EMAIL_SINK", "smtp")
    if sink == "memory":
        _memory_sink.append(SentMessage(to=to, subject=subject, body=body))
        logger.info("email captured (memory sink): to=%s subject=%s", to, subject)
        return

    settings = get_settings()
    msg = EmailMessage()
    msg["From"] = settings.smtp_from
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(body)

    await aiosmtplib.send(
        msg,
        hostname=settings.smtp_host,
        port=settings.smtp_port,
        username=settings.smtp_username or None,
        password=settings.smtp_password.get_secret_value() if settings.smtp_password else None,
        start_tls=settings.smtp_starttls,
    )
