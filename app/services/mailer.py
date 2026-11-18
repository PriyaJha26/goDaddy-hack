"""Outgoing email through the domain mailbox (GoDaddy Titan / secureserver SMTP).

``Mailer`` is the interface; ``SmtpMailer`` sends for real and ``LoggingMailer`` only logs,
for local development without mailbox credentials.
"""

from __future__ import annotations

import asyncio
import logging
import smtplib
import ssl
from dataclasses import dataclass
from email.message import EmailMessage
from email.utils import formataddr, make_msgid
from typing import Protocol

from app.domain.errors import ExternalServiceError

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class OutgoingEmail:
    to: str
    subject: str
    body: str
    reply_to: str | None = None


def _single_line(value: str) -> str:
    """Header values must never contain line breaks (prevents header injection)."""
    return " ".join(value.split())[:200]


class Mailer(Protocol):
    async def send(self, email: OutgoingEmail) -> None: ...


class SmtpMailer:
    def __init__(
        self, host: str, port: int, username: str, password: str, sender: str, sender_name: str, timeout: float = 20
    ) -> None:
        self._host, self._port = host, port
        self._username, self._password = username, password
        self._sender, self._sender_name = sender, sender_name
        self._timeout = timeout

    def build_message(self, email: OutgoingEmail) -> EmailMessage:
        msg = EmailMessage()
        msg["From"] = formataddr((_single_line(self._sender_name), self._sender))
        msg["To"] = _single_line(email.to)
        msg["Subject"] = _single_line(email.subject)
        msg["Message-ID"] = make_msgid(domain=self._sender.rsplit("@", 1)[-1])
        if email.reply_to:
            msg["Reply-To"] = _single_line(email.reply_to)
        msg.set_content(email.body)
        return msg

    def _send_blocking(self, msg: EmailMessage) -> None:
        context = ssl.create_default_context()
        if self._port == 465:
            with smtplib.SMTP_SSL(self._host, self._port, context=context, timeout=self._timeout) as smtp:
                smtp.login(self._username, self._password)
                smtp.send_message(msg)
        else:
            with smtplib.SMTP(self._host, self._port, timeout=self._timeout) as smtp:
                smtp.starttls(context=context)
                smtp.login(self._username, self._password)
                smtp.send_message(msg)

    async def send(self, email: OutgoingEmail) -> None:
        msg = self.build_message(email)
        try:
            await asyncio.to_thread(self._send_blocking, msg)
        except (smtplib.SMTPException, OSError) as exc:
            logger.exception("SMTP send failed")
            raise ExternalServiceError("Email could not be sent right now.") from exc
        logger.info("Email sent", extra={"subject": msg["Subject"]})


class LoggingMailer:
    """Development stand-in: records and logs messages instead of sending them."""

    def __init__(self) -> None:
        self.sent: list[OutgoingEmail] = []

    async def send(self, email: OutgoingEmail) -> None:
        self.sent.append(email)
        logger.info("[dev mailer] to=%s subject=%s", email.to, email.subject)
