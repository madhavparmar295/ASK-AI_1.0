"""Sending email. The default sender uses SMTP; tests pass in a fake sender."""
import smtplib
from email.message import EmailMessage
from typing import Callable

from ..config import get_settings

Sender = Callable[[str, str, str], None]     # (to_address, subject, body)


def smtp_send(to: str, subject: str, body: str) -> None:
    s = get_settings()
    msg = EmailMessage()
    msg["From"] = s.sender_address
    msg["To"] = to
    msg["Subject"] = subject.replace("\r", " ").replace("\n", " ")[:200]
    msg.set_content(body)
    with smtplib.SMTP(s.smtp_host, s.smtp_port, timeout=15) as server:
        if s.smtp_starttls:
            server.starttls()
        if s.smtp_user:
            server.login(s.smtp_user, s.smtp_password)
        server.send_message(msg)
